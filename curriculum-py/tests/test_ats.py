"""Tests for cv_skill.ats — pure-Python ATS keyword matching."""

from __future__ import annotations

import pytest

from cv_skill.ats import check_structural_issues, compute_coverage, match_keywords
from cv_skill.schema import KeywordMatch


# ── match_keywords ────────────────────────────────────────────────────────────


class TestMatchKeywords:
    _CV_TEXT = (
        "Summary\n"
        "Experienced data engineer with Apache Kafka expertise.\n\n"
        "Skills\n"
        "Python, SQL, Airflow\n\n"
        "Experience\n"
        "Built streaming pipelines; managed dbt models."
    )

    def test_present_keyword_is_detected(self) -> None:
        results = match_keywords(["Apache Kafka"], self._CV_TEXT)
        assert len(results) == 1
        assert results[0].keyword == "Apache Kafka"
        assert results[0].present is True

    def test_absent_keyword_is_marked_false(self) -> None:
        results = match_keywords(["dbt", "Kubernetes"], self._CV_TEXT)
        kw_map = {m.keyword: m for m in results}
        assert kw_map["dbt"].present is True  # dbt is in experience
        assert kw_map["Kubernetes"].present is False
        assert kw_map["Kubernetes"].location is None

    def test_case_insensitive_matching(self) -> None:
        results = match_keywords(["apache kafka"], self._CV_TEXT)
        assert results[0].present is True

    def test_multi_keyword_mixed_results(self) -> None:
        results = match_keywords(["Apache Kafka", "dbt", "Spark"], self._CV_TEXT)
        kw_map = {m.keyword: m for m in results}
        assert kw_map["Apache Kafka"].present is True
        assert kw_map["dbt"].present is True
        assert kw_map["Spark"].present is False

    def test_empty_keywords_returns_empty_list(self) -> None:
        results = match_keywords([], self._CV_TEXT)
        assert results == []

    def test_empty_cv_text_all_absent(self) -> None:
        results = match_keywords(["Python", "SQL"], "")
        assert all(not m.present for m in results)

    def test_location_set_for_present_keyword(self) -> None:
        results = match_keywords(["Python"], self._CV_TEXT)
        assert results[0].present is True
        assert results[0].location is not None

    def test_returns_list_of_keyword_match_instances(self) -> None:
        results = match_keywords(["Python"], self._CV_TEXT)
        assert all(isinstance(m, KeywordMatch) for m in results)

    def test_preserves_input_keyword_order(self) -> None:
        keywords = ["SQL", "Apache Kafka", "Spark"]
        results = match_keywords(keywords, self._CV_TEXT)
        assert [m.keyword for m in results] == keywords


# ── compute_coverage ──────────────────────────────────────────────────────────


class TestComputeCoverage:
    def test_all_present(self) -> None:
        matches = [
            KeywordMatch(keyword="Python", present=True, location="skills"),
            KeywordMatch(keyword="SQL", present=True, location="skills"),
        ]
        assert compute_coverage(matches) == 100.0

    def test_none_present(self) -> None:
        matches = [
            KeywordMatch(keyword="Rust", present=False),
            KeywordMatch(keyword="Go", present=False),
        ]
        assert compute_coverage(matches) == 0.0

    def test_partial_coverage(self) -> None:
        matches = [
            KeywordMatch(keyword="Python", present=True, location="skills"),
            KeywordMatch(keyword="Kafka", present=False),
            KeywordMatch(keyword="dbt", present=False),
        ]
        # 1 out of 3 → 33.3%
        assert compute_coverage(matches) == pytest.approx(33.3, abs=0.1)

    def test_two_thirds_coverage(self) -> None:
        matches = [
            KeywordMatch(keyword="A", present=True),
            KeywordMatch(keyword="B", present=True),
            KeywordMatch(keyword="C", present=False),
        ]
        assert compute_coverage(matches) == pytest.approx(66.7, abs=0.1)

    def test_empty_list_returns_zero(self) -> None:
        assert compute_coverage([]) == 0.0

    def test_single_present_returns_100(self) -> None:
        assert compute_coverage([KeywordMatch(keyword="X", present=True)]) == 100.0

    def test_returns_float(self) -> None:
        result = compute_coverage([KeywordMatch(keyword="X", present=True)])
        assert isinstance(result, float)


# ── check_structural_issues ───────────────────────────────────────────────────


class TestCheckStructuralIssues:
    def test_em_dash_detected(self) -> None:
        issues = check_structural_issues("Led platform — delivered results.")
        assert any("em-dash" in i.lower() or "em dash" in i.lower() for i in issues)

    def test_en_dash_detected(self) -> None:
        # En-dash (–) should also be flagged.
        issues = check_structural_issues("Jan 2020 – Dec 2022")
        assert any("em-dash" in i.lower() or "em dash" in i.lower() for i in issues)

    def test_clean_text_no_issues(self) -> None:
        clean = (
            "Python developer with 5 years of experience in data engineering.\n"
            "Jan 2020 - Dec 2022\n"
            "- Built streaming pipelines using Apache Kafka."
        )
        issues = check_structural_issues(clean)
        assert issues == []

    def test_tab_character_detected(self) -> None:
        issues = check_structural_issues("Column1\tColumn2\tColumn3")
        assert any("tab" in i.lower() for i in issues)

    def test_multi_column_indicator_detected(self) -> None:
        issues = check_structural_issues("Name || Location || Phone")
        assert any("multi-column" in i.lower() or "column" in i.lower() for i in issues)

    def test_returns_list_of_strings(self) -> None:
        issues = check_structural_issues("Some — text")
        assert isinstance(issues, list)
        assert all(isinstance(i, str) for i in issues)

    def test_empty_string_no_issues(self) -> None:
        assert check_structural_issues("") == []

    def test_multiple_issues_all_returned(self) -> None:
        # Both em-dash and tab present.
        issues = check_structural_issues("Led team — shipped features.\tExtra")
        assert len(issues) >= 2
