"""Tests for cv_skill.schema — Pydantic model validation."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from cv_skill.schema import (
    ATSReport,
    CVAuditRequest,
    CVAuditResponse,
    CVContent,
    CustomCVRequest,
    CustomCVResponse,
    ExtractCVRequest,
    ExtractCVResponse,
    GapAnalysis,
    KeywordMatch,
    ParsedJD,
    TailoredCV,
)


# ── CustomCVRequest ───────────────────────────────────────────────────────────


class TestCustomCVRequest:
    def test_valid_minimal(self) -> None:
        req = CustomCVRequest(job_url="https://example.com/jobs/1")
        assert req.task == "custom_cv"
        assert req.job_url == "https://example.com/jobs/1"
        assert req.branch_slug is None
        assert req.cv_dir == "content"

    def test_valid_with_all_fields(self) -> None:
        req = CustomCVRequest(
            job_url="https://boards.greenhouse.io/stripe/jobs/123",
            branch_slug="stripe-data-engineer",
            cv_dir="/custom/content",
        )
        assert req.branch_slug == "stripe-data-engineer"

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CustomCVRequest.model_validate({})  # job_url missing
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("job_url",) for e in errors)

    def test_task_literal_is_enforced(self) -> None:
        # task must be "custom_cv" — passing another value should fail.
        with pytest.raises(ValidationError):
            CustomCVRequest.model_validate({"task": "wrong", "job_url": "https://x.com"})

    def test_round_trip_json(self) -> None:
        req = CustomCVRequest(job_url="https://example.com/job")
        reloaded = CustomCVRequest.model_validate_json(req.model_dump_json())
        assert reloaded == req


# ── CustomCVResponse ──────────────────────────────────────────────────────────


class TestCustomCVResponse:
    def _make_full_response(self) -> CustomCVResponse:
        tailored = TailoredCV(
            summary="Summary text",
            core_competencies="- Python\n- SQL",
            skills="## Languages\nPython, SQL",
            experience="## Acme\n- Built pipelines",
        )
        parsed_jd = ParsedJD(
            url="https://example.com/jobs/1",
            title="Data Engineer",
            company="Acme",
            sector="Technology / Software",
            functional_area="Data Engineering",
            must_haves=["Python", "SQL"],
            nice_to_haves=["Spark"],
            tech_stack=["Python", "SQL", "Kafka"],
            ats_keywords=["Python", "SQL", "Kafka"],
        )
        keyword_table = [
            KeywordMatch(keyword="Python", present=True, location="skills"),
            KeywordMatch(keyword="SQL", present=True, location="skills"),
            KeywordMatch(keyword="Kafka", present=False, location=None),
        ]
        gap_analysis = [
            GapAnalysis(keyword="Kafka", classification="fillable", suggestion="Add to skills."),
        ]
        ats_report = ATSReport(
            coverage_score=66.7,
            total_keywords=3,
            matched_keywords=2,
            keyword_table=keyword_table,
            gap_analysis=gap_analysis,
            structural_issues=[],
        )
        return CustomCVResponse(
            status="ok",
            tailored_cv=tailored,
            parsed_jd=parsed_jd,
            ats_report=ats_report,
            branch_name="cv/acme-data-engineer",
        )

    def test_valid_ok_response(self) -> None:
        resp = self._make_full_response()
        assert resp.status == "ok"
        assert resp.tailored_cv is not None
        assert resp.ats_report is not None
        assert resp.branch_name == "cv/acme-data-engineer"

    def test_valid_error_response(self) -> None:
        resp = CustomCVResponse(status="error", errors=["Something went wrong"])
        assert resp.status == "error"
        assert resp.tailored_cv is None
        assert resp.errors == ["Something went wrong"]

    def test_warnings_and_errors_default_to_empty_list(self) -> None:
        resp = CustomCVResponse(status="ok")
        assert resp.warnings == []
        assert resp.errors == []

    def test_round_trip_json(self) -> None:
        resp = self._make_full_response()
        json_str = resp.model_dump_json()
        reloaded = CustomCVResponse.model_validate_json(json_str)
        assert reloaded.status == resp.status
        assert reloaded.branch_name == resp.branch_name
        assert reloaded.ats_report is not None
        assert reloaded.ats_report.coverage_score == resp.ats_report.coverage_score  # type: ignore[union-attr]

    def test_round_trip_dict(self) -> None:
        resp = self._make_full_response()
        raw_dict = json.loads(resp.model_dump_json())
        reloaded = CustomCVResponse.model_validate(raw_dict)
        assert reloaded == resp


# ── CVAuditRequest / CVAuditResponse ─────────────────────────────────────────


class TestCVAuditSchemas:
    def test_audit_request_defaults(self) -> None:
        req = CVAuditRequest(job_url="https://example.com/job")
        assert req.task == "cv_audit"
        assert req.cv_dir == "content"

    def test_audit_request_missing_url_raises(self) -> None:
        with pytest.raises(ValidationError):
            CVAuditRequest.model_validate({})

    def test_audit_response_ok(self) -> None:
        resp = CVAuditResponse(status="ok")
        assert resp.parsed_jd is None
        assert resp.ats_report is None

    def test_audit_response_error(self) -> None:
        resp = CVAuditResponse(status="error", errors=["scrape failed"])
        assert resp.status == "error"


# ── ExtractCVRequest / ExtractCVResponse ──────────────────────────────────────


class TestExtractCVSchemas:
    def test_extract_request_defaults(self) -> None:
        req = ExtractCVRequest(pdf_path="/path/to/cv.pdf")
        assert req.task == "extract_cv"
        assert req.output_dir == "content"
        assert req.force is False

    def test_extract_request_missing_pdf_raises(self) -> None:
        with pytest.raises(ValidationError):
            ExtractCVRequest.model_validate({})

    def test_extract_response_ok(self) -> None:
        content = CVContent(
            summary="A summary",
            core_competencies="- Python",
            skills="## Languages\nPython",
            experience="## Acme\n- Did stuff",
        )
        resp = ExtractCVResponse(
            status="ok",
            extracted_sections=content,
            sector="Technology / Software",
            functional_area="Data Engineering",
        )
        assert resp.status == "ok"
        assert resp.extracted_sections is not None
        assert resp.sector == "Technology / Software"

    def test_extract_response_missing_fields_list(self) -> None:
        resp = ExtractCVResponse(status="ok", missing_fields=["summary"])
        assert "summary" in resp.missing_fields
