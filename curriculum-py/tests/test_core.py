"""Tests for cv_skill.core — orchestration functions with mocked LLM adapters."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cv_skill.core import run_custom_cv, run_cv_audit, run_extract_cv
from cv_skill.schema import (
    CVAuditRequest,
    CVContent,
    CustomCVRequest,
    ExtractCVRequest,
    GapAnalysis,
    KeywordMatch,
    ParsedJD,
    TailoredCV,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def parsed_jd() -> ParsedJD:
    return ParsedJD(
        url="https://boards.greenhouse.io/acme/jobs/1",
        title="Senior Data Engineer",
        company="Acme",
        sector="Technology / Software",
        functional_area="Data Engineering",
        must_haves=["Python", "SQL"],
        nice_to_haves=["Spark"],
        tech_stack=["Python", "SQL", "Kafka"],
        ats_keywords=["Python", "SQL", "Kafka"],
    )


@pytest.fixture()
def tailored_cv() -> TailoredCV:
    return TailoredCV(
        summary="Experienced data engineer with Python and SQL expertise.",
        core_competencies="- Python\n- SQL\n- Kafka",
        skills="## Languages\nPython, SQL",
        experience="## Acme\n- Built Kafka pipelines with Python and SQL.",
    )


@pytest.fixture()
def mock_llm(parsed_jd: ParsedJD, tailored_cv: TailoredCV) -> MagicMock:
    """Mock LLM adapter that returns plausible objects for every method."""
    llm = MagicMock()
    llm.parse_jd.return_value = parsed_jd
    llm.tailor_cv.return_value = tailored_cv
    llm.analyze_gaps.return_value = [
        GapAnalysis(keyword="Kafka", classification="fillable", suggestion="Add to skills."),
    ]
    extracted_content = CVContent(
        summary="A data engineer.",
        core_competencies="- Python",
        skills="## Languages\nPython",
        experience="## Job\n- Did things",
    )
    llm.parse_cv_text.return_value = extracted_content
    llm.infer_sector.return_value = ("Technology / Software", "Data Engineering")
    return llm


@pytest.fixture()
def content_dir(tmp_path: Path) -> Path:
    """Populate a temporary content directory with all required Markdown files."""
    (tmp_path / "summary.md").write_text("Data engineer summary.", encoding="utf-8")
    (tmp_path / "core_competencies.md").write_text("- Python\n- SQL", encoding="utf-8")
    (tmp_path / "skills.md").write_text("## Languages\nPython, SQL", encoding="utf-8")
    (tmp_path / "experience.md").write_text("## Acme\n- Built things.", encoding="utf-8")
    return tmp_path


# ── run_custom_cv ─────────────────────────────────────────────────────────────


class TestRunCustomCV:
    def test_ok_response_with_mock_scraper(
        self, mock_llm: MagicMock, content_dir: Path
    ) -> None:
        request = CustomCVRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/1",
            branch_slug="acme-data-engineer",
            cv_dir=str(content_dir),
        )
        scrape_result = {
            "url": request.job_url,
            "title": "Senior Data Engineer",
            "company": "Acme",
            "content": "We need a Python and SQL data engineer with Kafka experience.",
            "engine": "requests",
        }
        with patch("cv_skill.core._scrape_job", return_value=scrape_result):
            response = run_custom_cv(request, mock_llm)

        assert response.status == "ok"
        assert response.tailored_cv is not None
        assert response.parsed_jd is not None
        assert response.ats_report is not None
        assert response.branch_name == "cv/acme-data-engineer"
        assert response.errors == []

    def test_branch_name_inferred_from_jd_when_slug_omitted(
        self, mock_llm: MagicMock, content_dir: Path
    ) -> None:
        request = CustomCVRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/1",
            cv_dir=str(content_dir),
        )
        scrape_result = {
            "url": request.job_url,
            "content": "Python data engineer role.",
            "engine": "requests",
        }
        with patch("cv_skill.core._scrape_job", return_value=scrape_result):
            response = run_custom_cv(request, mock_llm)

        assert response.status == "ok"
        assert response.branch_name is not None
        assert response.branch_name.startswith("cv/")

    def test_scraping_failure_returns_error_status(
        self, mock_llm: MagicMock, content_dir: Path
    ) -> None:
        request = CustomCVRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/1",
            cv_dir=str(content_dir),
        )
        from cv_skill.errors import ScrapingError

        with patch("cv_skill.core._scrape_job", side_effect=ScrapingError("Network timeout")):
            response = run_custom_cv(request, mock_llm)

        assert response.status == "error"
        assert len(response.errors) > 0
        assert response.tailored_cv is None

    def test_missing_cv_dir_returns_error_status(self, mock_llm: MagicMock) -> None:
        request = CustomCVRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/1",
            cv_dir="/nonexistent/path/content",
        )
        scrape_result = {"url": request.job_url, "content": "Some JD text.", "engine": "requests"}
        with patch("cv_skill.core._scrape_job", return_value=scrape_result):
            response = run_custom_cv(request, mock_llm)

        assert response.status == "error"
        assert len(response.errors) > 0

    def test_llm_parse_jd_failure_returns_error(
        self, mock_llm: MagicMock, content_dir: Path
    ) -> None:
        mock_llm.parse_jd.side_effect = RuntimeError("LLM API unavailable")
        request = CustomCVRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/1",
            cv_dir=str(content_dir),
        )
        scrape_result = {"url": request.job_url, "content": "Some JD text.", "engine": "requests"}
        with patch("cv_skill.core._scrape_job", return_value=scrape_result):
            response = run_custom_cv(request, mock_llm)

        assert response.status == "error"

    def test_ats_report_coverage_in_response(
        self, mock_llm: MagicMock, content_dir: Path
    ) -> None:
        request = CustomCVRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/1",
            cv_dir=str(content_dir),
        )
        scrape_result = {"url": request.job_url, "content": "Python SQL Kafka.", "engine": "requests"}
        with patch("cv_skill.core._scrape_job", return_value=scrape_result):
            response = run_custom_cv(request, mock_llm)

        assert response.status == "ok"
        assert 0.0 <= response.ats_report.coverage_score <= 100.0  # type: ignore[union-attr]

    def test_gap_analysis_failure_is_warned_not_errored(
        self, mock_llm: MagicMock, content_dir: Path
    ) -> None:
        mock_llm.analyze_gaps.side_effect = RuntimeError("gap analysis broken")
        request = CustomCVRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/1",
            cv_dir=str(content_dir),
        )
        scrape_result = {"url": request.job_url, "content": "Python SQL.", "engine": "requests"}
        with patch("cv_skill.core._scrape_job", return_value=scrape_result):
            response = run_custom_cv(request, mock_llm)

        # Gap analysis failures are non-fatal — status should still be ok.
        assert response.status == "ok"
        assert any("gap" in w.lower() for w in response.warnings)


# ── run_cv_audit ──────────────────────────────────────────────────────────────


class TestRunCVAudit:
    def test_ok_response(self, mock_llm: MagicMock, content_dir: Path) -> None:
        request = CVAuditRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/1",
            cv_dir=str(content_dir),
        )
        scrape_result = {"url": request.job_url, "content": "Python Kafka data eng.", "engine": "requests"}
        with patch("cv_skill.core._scrape_job", return_value=scrape_result):
            response = run_cv_audit(request, mock_llm)

        assert response.status == "ok"
        assert response.parsed_jd is not None
        assert response.ats_report is not None
        assert response.errors == []

    def test_scraping_failure_returns_error(self, mock_llm: MagicMock, content_dir: Path) -> None:
        from cv_skill.errors import ScrapingError

        request = CVAuditRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/1",
            cv_dir=str(content_dir),
        )
        with patch("cv_skill.core._scrape_job", side_effect=ScrapingError("DNS failure")):
            response = run_cv_audit(request, mock_llm)

        assert response.status == "error"
        assert response.parsed_jd is None

    def test_missing_cv_dir_returns_error(self, mock_llm: MagicMock) -> None:
        request = CVAuditRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/1",
            cv_dir="/no/such/dir",
        )
        scrape_result = {"url": request.job_url, "content": "JD text.", "engine": "requests"}
        with patch("cv_skill.core._scrape_job", return_value=scrape_result):
            response = run_cv_audit(request, mock_llm)

        assert response.status == "error"

    def test_no_files_written(self, mock_llm: MagicMock, content_dir: Path, tmp_path: Path) -> None:
        """cv-audit must never modify the CV directory."""
        import os

        before = set(os.listdir(content_dir))
        request = CVAuditRequest(
            job_url="https://boards.greenhouse.io/acme/jobs/1",
            cv_dir=str(content_dir),
        )
        scrape_result = {"url": request.job_url, "content": "Python.", "engine": "requests"}
        with patch("cv_skill.core._scrape_job", return_value=scrape_result):
            run_cv_audit(request, mock_llm)

        after = set(os.listdir(content_dir))
        assert before == after


# ── run_extract_cv ────────────────────────────────────────────────────────────


class TestRunExtractCV:
    def test_ok_response(self, mock_llm: MagicMock, tmp_path: Path) -> None:
        fake_pdf = tmp_path / "cv.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        request = ExtractCVRequest(
            pdf_path=str(fake_pdf),
            output_dir=str(output_dir),
            force=True,
        )
        mock_markdown = "# Jane Doe\nData engineer.\n\n## Summary\nExperienced.\n"
        with patch("cv_skill.core._run_markitdown", return_value=mock_markdown):
            response = run_extract_cv(request, mock_llm)

        assert response.status == "ok"
        assert response.extracted_sections is not None
        assert response.sector == "Technology / Software"
        assert response.functional_area == "Data Engineering"

    def test_missing_pdf_returns_error(self, mock_llm: MagicMock, tmp_path: Path) -> None:
        request = ExtractCVRequest(
            pdf_path=str(tmp_path / "nonexistent.pdf"),
            output_dir=str(tmp_path / "output"),
        )
        response = run_extract_cv(request, mock_llm)
        assert response.status == "error"
        assert any("markitdown" in e or "not found" in e.lower() for e in response.errors)

    def test_markitdown_failure_returns_error(self, mock_llm: MagicMock, tmp_path: Path) -> None:
        fake_pdf = tmp_path / "cv.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")

        from cv_skill.errors import FileSystemError

        request = ExtractCVRequest(
            pdf_path=str(fake_pdf),
            output_dir=str(tmp_path / "output"),
        )
        with patch("cv_skill.core._run_markitdown", side_effect=FileSystemError("markitdown failed")):
            response = run_extract_cv(request, mock_llm)

        assert response.status == "error"

    def test_output_files_written_when_dir_exists(
        self, mock_llm: MagicMock, tmp_path: Path
    ) -> None:
        fake_pdf = tmp_path / "cv.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        request = ExtractCVRequest(
            pdf_path=str(fake_pdf),
            output_dir=str(output_dir),
            force=True,
        )
        mock_markdown = "# Jane Doe\n\n## Summary\nExperienced data engineer."
        with patch("cv_skill.core._run_markitdown", return_value=mock_markdown):
            response = run_extract_cv(request, mock_llm)

        assert response.status == "ok"
        written = list(output_dir.iterdir())
        # At least one Markdown file should have been written.
        assert len(written) > 0
        assert all(f.suffix == ".md" for f in written)

    def test_llm_parse_cv_text_failure_returns_error(
        self, mock_llm: MagicMock, tmp_path: Path
    ) -> None:
        fake_pdf = tmp_path / "cv.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4 fake")
        mock_llm.parse_cv_text.side_effect = RuntimeError("LLM broken")

        request = ExtractCVRequest(
            pdf_path=str(fake_pdf),
            output_dir=str(tmp_path / "output"),
        )
        mock_markdown = "Some extracted text."
        with patch("cv_skill.core._run_markitdown", return_value=mock_markdown):
            response = run_extract_cv(request, mock_llm)

        assert response.status == "error"
