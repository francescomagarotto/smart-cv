"""Pydantic models for all three cv_skill request/response pairs.

No LLM SDK is imported here — this module is intentionally provider-agnostic
and safe to import in any context.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── Shared building blocks ────────────────────────────────────────────────────


class CVContent(BaseModel):
    """The four tailorable sections read from ``content/``.

    Attributes:
        summary: Raw text of ``summary.md``.
        core_competencies: Raw text of ``core_competencies.md``.
        skills: Raw text of ``skills.md``.
        experience: Raw text of ``experience.md``.
    """

    summary: str
    core_competencies: str
    skills: str
    experience: str


class ParsedJD(BaseModel):
    """Structured representation of a parsed job description.

    Attributes:
        url: Canonical URL of the job posting.
        title: Job title extracted from the posting.
        company: Company name.
        sector: Industry sector, e.g. ``"Technology / Software"``.
        functional_area: Functional role area, e.g. ``"Data Engineering"``.
        must_haves: Hard requirements listed in the JD.
        nice_to_haves: Preferred but not required qualifications.
        tech_stack: Specific technologies, frameworks, and tools mentioned.
        ats_keywords: Deduplicated flat list of all ATS-relevant keywords.
    """

    url: str
    title: str
    company: str
    sector: str
    functional_area: str
    must_haves: list[str]
    nice_to_haves: list[str]
    tech_stack: list[str]
    ats_keywords: list[str]


class TailoredCV(BaseModel):
    """Rewritten CV sections produced by the LLM tailoring step.

    Attributes:
        summary: Rewritten summary paragraph.
        core_competencies: Rewritten competency list.
        skills: Rewritten skills section.
        experience: Rewritten experience bullets.
    """

    summary: str
    core_competencies: str
    skills: str
    experience: str


class KeywordMatch(BaseModel):
    """Result of matching a single ATS keyword against the CV text.

    Attributes:
        keyword: The keyword that was searched for.
        present: Whether the keyword was found in the CV text.
        location: Which CV section contained the first match, or ``None``.
    """

    keyword: str
    present: bool
    location: str | None = None


class GapAnalysis(BaseModel):
    """Classification of a missing ATS keyword.

    Attributes:
        keyword: The missing keyword.
        classification: One of ``"fillable"``, ``"stretchable"``, or
            ``"genuine_gap"``.
        suggestion: Optional actionable suggestion for the candidate.
    """

    keyword: str
    classification: Literal["fillable", "stretchable", "genuine_gap"]
    suggestion: str | None = None


class ATSReport(BaseModel):
    """Full ATS audit result.

    Attributes:
        coverage_score: Percentage of JD keywords found in the CV (0–100).
        total_keywords: Total number of JD keywords checked.
        matched_keywords: Number of keywords found in the CV.
        keyword_table: Per-keyword match details.
        gap_analysis: Classification of missing keywords.
        structural_issues: Human-readable list of structural problems.
    """

    coverage_score: float
    total_keywords: int
    matched_keywords: int
    keyword_table: list[KeywordMatch]
    gap_analysis: list[GapAnalysis]
    structural_issues: list[str]


# ── custom-cv ─────────────────────────────────────────────────────────────────


class CustomCVRequest(BaseModel):
    """Request payload for the ``custom-cv`` skill.

    Attributes:
        task: Discriminator literal; always ``"custom_cv"``.
        job_url: Public URL of the target job posting.
        branch_slug: Optional git branch suffix. Inferred from company/title
            if omitted.
        cv_dir: Path to the ``content/`` directory containing Markdown files.
    """

    task: Literal["custom_cv"] = "custom_cv"
    job_url: str
    branch_slug: str | None = None
    cv_dir: str = "content"


class CustomCVResponse(BaseModel):
    """Response payload for the ``custom-cv`` skill.

    Attributes:
        status: ``"ok"`` on success, ``"error"`` on failure.
        tailored_cv: Rewritten CV sections, populated on success.
        parsed_jd: Parsed job description, populated on success.
        ats_report: ATS audit result, populated on success.
        branch_name: Name of the git branch created for this application.
        warnings: Non-fatal notices.
        errors: Structured error messages if ``status == "error"``.
    """

    status: Literal["ok", "error"]
    tailored_cv: TailoredCV | None = None
    parsed_jd: ParsedJD | None = None
    ats_report: ATSReport | None = None
    branch_name: str | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ── cv-audit ──────────────────────────────────────────────────────────────────


class CVAuditRequest(BaseModel):
    """Request payload for the read-only ``cv-audit`` skill.

    Attributes:
        task: Discriminator literal; always ``"cv_audit"``.
        job_url: Public URL of the target job posting.
        cv_dir: Path to the ``content/`` directory containing Markdown files.
    """

    task: Literal["cv_audit"] = "cv_audit"
    job_url: str
    cv_dir: str = "content"


class CVAuditResponse(BaseModel):
    """Response payload for the ``cv-audit`` skill.

    Attributes:
        status: ``"ok"`` on success, ``"error"`` on failure.
        parsed_jd: Parsed job description, populated on success.
        ats_report: ATS audit result, populated on success.
        warnings: Non-fatal notices.
        errors: Structured error messages if ``status == "error"``.
    """

    status: Literal["ok", "error"]
    parsed_jd: ParsedJD | None = None
    ats_report: ATSReport | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ── extract-cv ────────────────────────────────────────────────────────────────


class ExtractCVRequest(BaseModel):
    """Request payload for the ``extract-cv`` skill.

    Attributes:
        task: Discriminator literal; always ``"extract_cv"``.
        pdf_path: Absolute or relative path to the source CV PDF.
        output_dir: Directory where Markdown files will be written.
        force: If ``True``, overwrite existing files in ``output_dir``.
    """

    task: Literal["extract_cv"] = "extract_cv"
    pdf_path: str
    output_dir: str = "content"
    force: bool = False


class ExtractCVResponse(BaseModel):
    """Response payload for the ``extract-cv`` skill.

    Attributes:
        status: ``"ok"`` on success, ``"error"`` on failure.
        extracted_sections: Parsed CV content, populated on success.
        sector: Inferred industry sector.
        functional_area: Inferred functional role area.
        missing_fields: Fields that could not be extracted from the PDF.
        warnings: Non-fatal notices.
        errors: Structured error messages if ``status == "error"``.
    """

    status: Literal["ok", "error"]
    extracted_sections: CVContent | None = None
    sector: str | None = None
    functional_area: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
