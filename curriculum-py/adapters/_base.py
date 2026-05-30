"""LLMAdapter Protocol — the minimal interface every provider adapter must satisfy.

Importing this module carries zero third-party dependencies. The Protocol is
structural (duck-typed), so adapters do not need to subclass it — they only
need to implement the five methods below.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# These imports are from the core package — no LLM SDK involved.
from cv_skill.schema import CVContent, GapAnalysis, KeywordMatch, ParsedJD, TailoredCV


@runtime_checkable
class LLMAdapter(Protocol):
    """Minimal interface every provider adapter must implement.

    All methods are synchronous. Async adapters are out of scope for this
    first version; the orchestration layer in ``core.py`` is synchronous.

    Implementations should:
    - Raise standard Python exceptions (not SDK-specific ones) on failure so
      ``core.py`` can catch ``Exception`` uniformly.
    - Never write to stdout/stderr — use the standard ``logging`` module.
    - Never fabricate facts that are not present in the input text.
    """

    def parse_jd(self, raw_text: str, url: str) -> ParsedJD:
        """Extract structured data from raw job description text.

        Args:
            raw_text: Plain text content of the job posting.
            url: Canonical URL of the posting (stored verbatim in ParsedJD).

        Returns:
            Fully populated :class:`~cv_skill.schema.ParsedJD`.
        """
        ...

    def tailor_cv(self, jd: ParsedJD, cv: CVContent) -> TailoredCV:
        """Rewrite CV sections to match the job description.

        The LLM must never fabricate skills, technologies, or achievements that
        are absent from the original ``cv`` content.

        Args:
            jd: Parsed job description with keywords and requirements.
            cv: Current CV sections read from ``content/``.

        Returns:
            :class:`~cv_skill.schema.TailoredCV` with all four sections
            rewritten.
        """
        ...

    def analyze_gaps(
        self,
        jd: ParsedJD,
        cv: CVContent,
        matches: list[KeywordMatch],
    ) -> list[GapAnalysis]:
        """Classify each missing ATS keyword.

        Only keywords where ``match.present == False`` need to be classified;
        implementations may ignore already-matched keywords.

        Args:
            jd: Parsed job description.
            cv: Current (or tailored) CV content for context.
            matches: Per-keyword match results from the ATS step.

        Returns:
            List of :class:`~cv_skill.schema.GapAnalysis` items, one per
            missing keyword.
        """
        ...

    def parse_cv_text(self, raw_text: str) -> CVContent:
        """Parse raw extracted CV text into structured sections.

        Args:
            raw_text: Plain text or Markdown produced by markitdown from a
                PDF CV.

        Returns:
            :class:`~cv_skill.schema.CVContent` with all four fields
            populated (may be empty strings for sections that cannot be found).
        """
        ...

    def infer_sector(self, raw_text: str) -> tuple[str, str]:
        """Return the industry sector and functional area from CV or JD text.

        Args:
            raw_text: Plain text of the CV or job description.

        Returns:
            A ``(sector, functional_area)`` tuple, e.g.
            ``("Technology / Software", "Data Engineering")``.
        """
        ...
