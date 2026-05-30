"""Orchestration layer for the three cv_skill workflows.

Each ``run_*`` function is the single entry point for one skill. They:
- Accept a typed request and an :class:`~adapters._base.LLMAdapter`.
- Return a fully typed response; never raise to the caller.
- Log all errors; never print to stdout/stderr.

No LLM SDK is imported here — all provider-specific logic lives in the
``adapters/`` package and is injected via the ``LLMAdapter`` Protocol.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from cv_skill.ats import check_structural_issues, compute_coverage, match_keywords
from cv_skill.errors import FileSystemError, LLMError, ScrapingError, SkillError
from cv_skill.schema import (
    ATSReport,
    CVAuditRequest,
    CVAuditResponse,
    CVContent,
    CustomCVRequest,
    CustomCVResponse,
    ExtractCVRequest,
    ExtractCVResponse,
    TailoredCV,
)

if TYPE_CHECKING:
    # Imported only for type checking to keep the runtime dependency optional.
    from adapters._base import LLMAdapter

log = logging.getLogger(__name__)

# Path to the curriculum-py package root (one level up from src/cv_skill/).
_PKG_ROOT = Path(__file__).parent.parent.parent


# ── Private helpers ───────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    """Slugify a string for use as a git branch component.

    Lowercases, replaces non-alphanumeric characters with hyphens, and
    collapses consecutive hyphens.

    Args:
        text: Raw string (company name or job title).

    Returns:
        URL-safe, hyphen-separated lowercase slug.
    """
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _read_cv_content(cv_dir: str) -> CVContent:
    """Read the four tailorable Markdown files from ``cv_dir``.

    Args:
        cv_dir: Path (relative or absolute) to the ``content/`` directory.

    Returns:
        :class:`~cv_skill.schema.CVContent` populated from disk.

    Raises:
        FileSystemError: If any of the four required files is missing or
            cannot be read.
    """
    base = Path(cv_dir)
    files: dict[str, str] = {
        "summary": "summary.md",
        "core_competencies": "core_competencies.md",
        "skills": "skills.md",
        "experience": "experience.md",
    }
    sections: dict[str, str] = {}
    for field, filename in files.items():
        path = base / filename
        if not path.exists():
            raise FileSystemError(
                f"Required file not found: {path}",
                detail=f"cv_dir={cv_dir}",
            )
        try:
            sections[field] = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise FileSystemError(
                f"Cannot read {path}: {exc}",
                detail=str(exc),
            ) from exc
    return CVContent(**sections)


def _load_job_scraper_class():  # type: ignore[return]
    """Dynamically import ``JobScraper`` from the sibling ``job_spider`` module.

    We use ``importlib`` rather than a direct import to avoid making
    ``job_spider.py`` part of the installed package, keeping its Scrapy /
    requests dependencies truly optional for consumers of ``cv_skill`` alone.

    Returns:
        The ``JobScraper`` class.

    Raises:
        ScrapingError: If the module cannot be loaded.
    """
    spider_path = _PKG_ROOT / "job_spider.py"
    if not spider_path.exists():
        raise ScrapingError(
            "job_spider.py not found",
            detail=f"Expected at {spider_path}",
        )
    try:
        spec = importlib.util.spec_from_file_location("job_spider", spider_path)
        if spec is None or spec.loader is None:
            raise ImportError("Could not create module spec")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module.JobScraper
    except ScrapingError:
        raise
    except Exception as exc:
        raise ScrapingError(
            "Failed to load job_spider module",
            detail=str(exc),
        ) from exc


def _scrape_job(url: str) -> dict:
    """Scrape a job posting URL using ``JobScraper``.

    Args:
        url: Public URL of the job posting.

    Returns:
        Raw scrape result dict from ``JobScraper.scrape``.

    Raises:
        ScrapingError: On any failure.
    """
    try:
        scraper_cls = _load_job_scraper_class()
        return scraper_cls().scrape(url)
    except ScrapingError:
        raise
    except Exception as exc:
        raise ScrapingError(
            f"Scraping failed for {url}",
            detail=str(exc),
        ) from exc


def _run_markitdown(pdf_path: Path) -> str:
    """Convert a PDF to Markdown text via ``markitdown`` subprocess.

    We invoke ``markitdown`` through a subprocess call (using the same venv)
    rather than importing it directly. This keeps the ``cv_skill`` package
    import-clean and avoids pulling in ``markitdown``'s heavy PDF dependencies
    at import time.

    Args:
        pdf_path: Absolute path to the source PDF file.

    Returns:
        Markdown text extracted from the PDF.

    Raises:
        FileSystemError: If the PDF does not exist or markitdown fails.
    """
    if not pdf_path.exists():
        raise FileSystemError(
            f"PDF not found: {pdf_path}",
            detail=str(pdf_path),
        )

    # Resolve the markitdown executable in the same venv as this process.
    venv_bin = Path(sys.executable).parent
    markitdown_exe = venv_bin / "markitdown"

    if not markitdown_exe.exists():
        raise FileSystemError(
            "markitdown executable not found in venv",
            detail=f"Looked in {venv_bin}",
        )

    try:
        result = subprocess.run(
            [str(markitdown_exe), str(pdf_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise FileSystemError("markitdown timed out", detail=str(exc)) from exc
    except OSError as exc:
        raise FileSystemError(f"Failed to run markitdown: {exc}", detail=str(exc)) from exc

    if result.returncode != 0:
        raise FileSystemError(
            "markitdown returned non-zero exit code",
            detail=result.stderr.strip(),
        )
    return result.stdout


def _build_ats_report(
    jd_keywords: list[str],
    cv_content: CVContent,
    gap_analysis: list,
) -> ATSReport:
    """Build an :class:`~cv_skill.schema.ATSReport` from keywords and CV text.

    Args:
        jd_keywords: Flat list of ATS keywords from the parsed JD.
        cv_content: Structured CV sections.
        gap_analysis: Pre-computed gap analysis from the LLM.

    Returns:
        Populated :class:`~cv_skill.schema.ATSReport`.
    """
    cv_text = "\n\n".join([
        cv_content.summary,
        cv_content.core_competencies,
        cv_content.skills,
        cv_content.experience,
    ])
    keyword_table = match_keywords(jd_keywords, cv_text)
    coverage = compute_coverage(keyword_table)
    structural_issues = check_structural_issues(cv_text)
    matched = sum(1 for m in keyword_table if m.present)

    return ATSReport(
        coverage_score=coverage,
        total_keywords=len(keyword_table),
        matched_keywords=matched,
        keyword_table=keyword_table,
        gap_analysis=gap_analysis,
        structural_issues=structural_issues,
    )


def _write_extracted_sections(extracted: CVContent, output_dir: Path, *, force: bool) -> None:
    """Write extracted CV sections to Markdown files.

    Args:
        extracted: Parsed CV content.
        output_dir: Directory to write files into.
        force: If ``False``, skip files that already exist.

    Raises:
        FileSystemError: If a write fails.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {
        "summary.md": extracted.summary,
        "core_competencies.md": extracted.core_competencies,
        "skills.md": extracted.skills,
        "experience.md": extracted.experience,
    }
    for filename, content in mapping.items():
        dest = output_dir / filename
        if dest.exists() and not force:
            log.info("extract_cv: skipping existing file %s", dest)
            continue
        try:
            dest.write_text(content, encoding="utf-8")
            log.info("extract_cv: wrote %s", dest)
        except OSError as exc:
            raise FileSystemError(f"Cannot write {dest}: {exc}", detail=str(exc)) from exc


# ── Public orchestration functions ────────────────────────────────────────────


def run_custom_cv(request: CustomCVRequest, llm: "LLMAdapter") -> CustomCVResponse:
    """Run the full custom-cv workflow.

    Steps:
    1. Scrape the job posting at ``request.job_url``.
    2. Parse the raw text into a :class:`~cv_skill.schema.ParsedJD` via the LLM.
    3. Read the current CV from ``request.cv_dir``.
    4. Tailor CV sections via the LLM.
    5. Run a pure-Python ATS keyword audit.
    6. Ask the LLM to classify keyword gaps.
    7. Return a fully populated :class:`~cv_skill.schema.CustomCVResponse`.

    All exceptions are caught and returned as ``status="error"`` responses.
    Nothing is written to disk here — the caller is responsible for committing
    results to git.

    Args:
        request: Validated :class:`~cv_skill.schema.CustomCVRequest`.
        llm: Injected :class:`~adapters._base.LLMAdapter` implementation.

    Returns:
        :class:`~cv_skill.schema.CustomCVResponse` with ``status="ok"`` on
        success or ``status="error"`` on failure.
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        log.info("custom_cv: scraping %s", request.job_url)
        scrape_result = _scrape_job(request.job_url)
        raw_jd = scrape_result.get("content", "")
        if not raw_jd:
            warnings.append("Scraper returned empty content — JD parsing may be incomplete.")

        log.info("custom_cv: parsing JD via LLM")
        try:
            parsed_jd = llm.parse_jd(raw_jd, request.job_url)
        except Exception as exc:
            raise LLMError("LLM failed to parse JD", detail=str(exc)) from exc

        log.info("custom_cv: reading CV from %s", request.cv_dir)
        cv_content = _read_cv_content(request.cv_dir)

        log.info("custom_cv: tailoring CV via LLM")
        try:
            tailored = llm.tailor_cv(parsed_jd, cv_content)
        except Exception as exc:
            raise LLMError("LLM failed to tailor CV", detail=str(exc)) from exc

        # Use tailored content for ATS scoring so the report reflects
        # the rewritten CV rather than the original.
        tailored_as_content = CVContent(
            summary=tailored.summary,
            core_competencies=tailored.core_competencies,
            skills=tailored.skills,
            experience=tailored.experience,
        )

        log.info("custom_cv: running ATS keyword match")
        keyword_table = match_keywords(
            parsed_jd.ats_keywords,
            "\n\n".join([
                tailored.summary,
                tailored.core_competencies,
                tailored.skills,
                tailored.experience,
            ]),
        )

        log.info("custom_cv: analysing %d keyword gaps via LLM", len(parsed_jd.ats_keywords))
        try:
            gap_analysis = llm.analyze_gaps(parsed_jd, tailored_as_content, keyword_table)
        except Exception as exc:
            warnings.append(f"Gap analysis failed — skipped: {exc}")
            gap_analysis = []

        ats_report = _build_ats_report(parsed_jd.ats_keywords, tailored_as_content, gap_analysis)

        # Derive branch name from the parsed JD when no slug is supplied.
        if request.branch_slug:
            branch_name: str = f"cv/{request.branch_slug}"
        else:
            company_slug = _slugify(parsed_jd.company)
            title_slug = _slugify(parsed_jd.title)
            branch_name = f"cv/{company_slug}-{title_slug}"

        log.info(
            "custom_cv: complete — branch=%s coverage=%.1f%%",
            branch_name,
            ats_report.coverage_score,
        )
        return CustomCVResponse(
            status="ok",
            tailored_cv=tailored,
            parsed_jd=parsed_jd,
            ats_report=ats_report,
            branch_name=branch_name,
            warnings=warnings,
            errors=errors,
        )

    except SkillError as exc:
        log.error("custom_cv failed: %s — %s", exc.message, exc.detail)
        errors.append(str(exc.to_dict()))
        return CustomCVResponse(status="error", warnings=warnings, errors=errors)
    except Exception as exc:
        log.exception("custom_cv: unexpected error")
        errors.append(str(exc))
        return CustomCVResponse(status="error", warnings=warnings, errors=errors)


def run_cv_audit(request: CVAuditRequest, llm: "LLMAdapter") -> CVAuditResponse:
    """Run a read-only ATS audit — no files are written or committed.

    Steps:
    1. Scrape the job posting at ``request.job_url``.
    2. Parse the raw text into a :class:`~cv_skill.schema.ParsedJD` via the LLM.
    3. Read the current CV from ``request.cv_dir``.
    4. Run a pure-Python ATS keyword audit.
    5. Ask the LLM to classify keyword gaps.
    6. Return a fully populated :class:`~cv_skill.schema.CVAuditResponse`.

    Args:
        request: Validated :class:`~cv_skill.schema.CVAuditRequest`.
        llm: Injected :class:`~adapters._base.LLMAdapter` implementation.

    Returns:
        :class:`~cv_skill.schema.CVAuditResponse` with ``status="ok"`` on
        success or ``status="error"`` on failure.
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        log.info("cv_audit: scraping %s", request.job_url)
        scrape_result = _scrape_job(request.job_url)
        raw_jd = scrape_result.get("content", "")
        if not raw_jd:
            warnings.append("Scraper returned empty content — audit results may be incomplete.")

        log.info("cv_audit: parsing JD via LLM")
        try:
            parsed_jd = llm.parse_jd(raw_jd, request.job_url)
        except Exception as exc:
            raise LLMError("LLM failed to parse JD", detail=str(exc)) from exc

        log.info("cv_audit: reading CV from %s", request.cv_dir)
        cv_content = _read_cv_content(request.cv_dir)

        log.info("cv_audit: running ATS keyword match")
        keyword_table = match_keywords(
            parsed_jd.ats_keywords,
            "\n\n".join([
                cv_content.summary,
                cv_content.core_competencies,
                cv_content.skills,
                cv_content.experience,
            ]),
        )

        log.info("cv_audit: analysing gaps via LLM")
        try:
            gap_analysis = llm.analyze_gaps(parsed_jd, cv_content, keyword_table)
        except Exception as exc:
            warnings.append(f"Gap analysis failed — skipped: {exc}")
            gap_analysis = []

        ats_report = _build_ats_report(parsed_jd.ats_keywords, cv_content, gap_analysis)

        log.info("cv_audit: complete — coverage=%.1f%%", ats_report.coverage_score)
        return CVAuditResponse(
            status="ok",
            parsed_jd=parsed_jd,
            ats_report=ats_report,
            warnings=warnings,
            errors=errors,
        )

    except SkillError as exc:
        log.error("cv_audit failed: %s — %s", exc.message, exc.detail)
        errors.append(str(exc.to_dict()))
        return CVAuditResponse(status="error", warnings=warnings, errors=errors)
    except Exception as exc:
        log.exception("cv_audit: unexpected error")
        errors.append(str(exc))
        return CVAuditResponse(status="error", warnings=warnings, errors=errors)


def run_extract_cv(request: ExtractCVRequest, llm: "LLMAdapter") -> ExtractCVResponse:
    """Extract and parse a CV from a PDF file.

    Steps:
    1. Convert the PDF to Markdown text via ``markitdown`` (subprocess).
    2. Ask the LLM to parse the raw text into structured :class:`~cv_skill.schema.CVContent`.
    3. Ask the LLM to infer the owner's industry sector and functional area.
    4. Write Markdown files to ``request.output_dir`` if it exists or ``force=True``.
    5. Return a fully populated :class:`~cv_skill.schema.ExtractCVResponse`.

    Args:
        request: Validated :class:`~cv_skill.schema.ExtractCVRequest`.
        llm: Injected :class:`~adapters._base.LLMAdapter` implementation.

    Returns:
        :class:`~cv_skill.schema.ExtractCVResponse` with ``status="ok"`` on
        success or ``status="error"`` on failure.
    """
    errors: list[str] = []
    warnings: list[str] = []
    missing_fields: list[str] = []

    try:
        pdf_path = Path(request.pdf_path)
        log.info("extract_cv: converting %s via markitdown", pdf_path)
        raw_text = _run_markitdown(pdf_path)

        if not raw_text.strip():
            raise FileSystemError("markitdown produced empty output", detail=str(pdf_path))

        log.info("extract_cv: parsing CV sections via LLM")
        try:
            extracted = llm.parse_cv_text(raw_text)
        except Exception as exc:
            raise LLMError("LLM failed to parse CV text", detail=str(exc)) from exc

        # Identify fields that appear empty after parsing.
        for field in ("summary", "core_competencies", "skills", "experience"):
            if not getattr(extracted, field, "").strip():
                missing_fields.append(field)
                warnings.append(f"Field '{field}' could not be extracted from the PDF.")

        log.info("extract_cv: inferring sector via LLM")
        try:
            sector, functional_area = llm.infer_sector(raw_text)
        except Exception as exc:
            warnings.append(f"Sector inference failed — skipped: {exc}")
            sector, functional_area = "", ""

        output_dir = Path(request.output_dir)
        if output_dir.exists() or request.force:
            _write_extracted_sections(extracted, output_dir, force=request.force)
        else:
            warnings.append(
                f"Output directory '{output_dir}' does not exist. "
                "Pass force=True or create it manually before writing."
            )

        log.info(
            "extract_cv: complete — sector=%r functional_area=%r",
            sector,
            functional_area,
        )
        return ExtractCVResponse(
            status="ok",
            extracted_sections=extracted,
            sector=sector or None,
            functional_area=functional_area or None,
            missing_fields=missing_fields,
            warnings=warnings,
            errors=errors,
        )

    except SkillError as exc:
        log.error("extract_cv failed: %s — %s", exc.message, exc.detail)
        errors.append(str(exc.to_dict()))
        return ExtractCVResponse(status="error", warnings=warnings, errors=errors)
    except Exception as exc:
        log.exception("extract_cv: unexpected error")
        errors.append(str(exc))
        return ExtractCVResponse(status="error", warnings=warnings, errors=errors)
