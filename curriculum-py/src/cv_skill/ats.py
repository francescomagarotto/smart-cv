"""Pure-Python ATS keyword matching and structural analysis.

No LLM calls, no external HTTP — all logic is deterministic string matching.
Suitable for offline use and fast unit testing.
"""

from __future__ import annotations

import logging
import re

from cv_skill.schema import KeywordMatch

log = logging.getLogger(__name__)

# Section header tokens used for location hinting.
# Keys are the labels returned in KeywordMatch.location.
_SECTION_HEADERS: dict[str, tuple[str, ...]] = {
    "summary": ("summary", "profile", "about"),
    "competencies": ("competencies", "core competencies", "key skills", "highlights"),
    "skills": ("skills", "technologies", "tech stack", "tools"),
    "experience": ("experience", "employment", "work history", "projects"),
}


def _split_sections(cv_text: str) -> dict[str, str]:
    """Split CV text into named sections based on common header patterns.

    The split is best-effort: if no recognisable headers are found the entire
    text is placed under the ``"body"`` key.

    Args:
        cv_text: Full concatenated CV text.

    Returns:
        Dict mapping section label to the text that belongs to that section.
    """
    # Normalise line endings and collapse excessive whitespace.
    normalised = re.sub(r"\r\n", "\n", cv_text)

    sections: dict[str, str] = {}
    current_label = "body"
    current_lines: list[str] = []

    for line in normalised.splitlines():
        stripped = line.strip().lower()
        matched_label: str | None = None
        for label, tokens in _SECTION_HEADERS.items():
            if any(stripped == token or stripped.startswith(token + ":") for token in tokens):
                matched_label = label
                break

        if matched_label is not None:
            if current_lines:
                sections[current_label] = "\n".join(current_lines)
            current_label = matched_label
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_label] = "\n".join(current_lines)

    return sections


def match_keywords(keywords: list[str], cv_text: str) -> list[KeywordMatch]:
    """Case-insensitive substring match of each keyword against ``cv_text``.

    Searches each keyword in the full CV text and, on a hit, determines
    which named section (summary / competencies / skills / experience) it
    appeared in first.

    Args:
        keywords: ATS keywords to search for.
        cv_text: Full concatenated CV text.

    Returns:
        A :class:`~cv_skill.schema.KeywordMatch` for every keyword in
        ``keywords``.
    """
    sections = _split_sections(cv_text)
    cv_lower = cv_text.lower()

    results: list[KeywordMatch] = []
    for keyword in keywords:
        kw_lower = keyword.lower()
        present = kw_lower in cv_lower
        location: str | None = None

        if present:
            # Find the section where the keyword appears earliest.
            earliest_pos = len(cv_lower)
            for label, section_text in sections.items():
                pos = section_text.lower().find(kw_lower)
                if pos != -1 and pos < earliest_pos:
                    earliest_pos = pos
                    location = label

        results.append(KeywordMatch(keyword=keyword, present=present, location=location))
        log.debug("keyword=%r present=%s location=%s", keyword, present, location)

    return results


def compute_coverage(matches: list[KeywordMatch]) -> float:
    """Compute keyword coverage as a percentage.

    Args:
        matches: List of :class:`~cv_skill.schema.KeywordMatch` instances.

    Returns:
        ``(matched / total) * 100`` rounded to one decimal place.
        Returns ``0.0`` when ``matches`` is empty.
    """
    if not matches:
        return 0.0
    matched = sum(1 for m in matches if m.present)
    return round(matched / len(matches) * 100, 1)


# Patterns that indicate structural ATS problems.
_STRUCTURAL_CHECKS: list[tuple[str, re.Pattern[str]]] = [
    # Em-dashes used instead of hyphens (bad for some ATS parsers).
    ("Em-dash detected; replace with a plain hyphen (-) for ATS compatibility.", re.compile(r"[—–]")),
    # Multi-column table indicators (LaTeX / HTML artefacts).
    ("Multi-column layout indicator detected; use a single-column layout.", re.compile(r"\|\s*\|")),
    # Mixed date formats — e.g. "Jan 2020" mixed with "01/2020".
    (
        "Inconsistent date formats detected; standardise to 'Month YYYY' throughout.",
        re.compile(r"\b\d{2}/\d{4}\b.*\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\b", re.DOTALL),
    ),
    # Tab characters (can misalign text in ATS plain-text parsers).
    ("Tab character detected; prefer spaces for alignment.", re.compile(r"\t")),
]


def check_structural_issues(cv_text: str) -> list[str]:
    """Detect common ATS structural problems in ``cv_text``.

    Checks for:
    - Em-dashes (should be plain hyphens)
    - Multi-column layout indicators
    - Inconsistent date formats
    - Tab characters

    Args:
        cv_text: Full concatenated CV text.

    Returns:
        List of human-readable issue strings; empty list means no issues found.
    """
    issues: list[str] = []
    for message, pattern in _STRUCTURAL_CHECKS:
        if pattern.search(cv_text):
            issues.append(message)
            log.debug("structural issue found: %s", message)
    return issues
