"""Anthropic Claude adapter.

Implements the :class:`adapters._base.LLMAdapter` Protocol using the
``anthropic`` Python SDK.

Because Anthropic's Messages API does not offer a ``response_format`` field
for JSON-schema enforcement, structured data is extracted by:
1. Instructing the model to wrap its JSON in ``<json>...</json>`` XML tags.
2. Parsing the content of that tag after the response arrives.

This is more reliable than asking for raw JSON because Claude is trained to
respect XML tag demarcation even when the surrounding prose varies.

Requires: ``anthropic>=0.40`` (install with ``uv pip install 'cv-skill[anthropic]'``).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from cv_skill.schema import CVContent, GapAnalysis, KeywordMatch, ParsedJD, TailoredCV

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096

# ── System prompts ────────────────────────────────────────────────────────────

_PARSE_JD_SYSTEM = """\
You are an expert technical recruiter and ATS specialist.
Extract structured information from the raw job posting text and return it
inside <json>...</json> tags as a JSON object with these fields:
  url, title, company, sector, functional_area,
  must_haves (array), nice_to_haves (array), tech_stack (array), ats_keywords (array)

Rules:
- Extract only what is explicitly stated — do not infer or fabricate.
- ats_keywords must be a deduplicated flat list of all ATS-relevant terms.
- tech_stack should list specific technologies only (no soft skills).
"""

_TAILOR_CV_SYSTEM = """\
You are an expert CV writer specialising in technical roles.
Rewrite the provided CV sections to maximise keyword alignment with the job
description. Return only a JSON object inside <json>...</json> tags with keys:
  summary, core_competencies, skills, experience

Strict rules — violations will be rejected:
1. NEVER fabricate skills, tools, achievements, or experiences not present in
   the original CV.
2. Preserve all factual claims; you may rephrase but not invent.
3. Prioritise ATS keywords from the job description naturally within the text.
4. Keep the same Markdown formatting conventions as the originals.
5. Do not add bullet points that describe work never done.
"""

_ANALYZE_GAPS_SYSTEM = """\
You are an ATS gap analyst. Classify each missing keyword inside
<json>...</json> tags as a JSON array of objects, each with:
  keyword, classification ("fillable"|"stretchable"|"genuine_gap"), suggestion (string|null)

Definitions:
- fillable: candidate likely has the skill but did not mention it.
- stretchable: adjacent skill they could reasonably claim.
- genuine_gap: skill genuinely absent.
"""

_PARSE_CV_SYSTEM = """\
You are a CV parser. Extract the four canonical sections from the CV text
and return them inside <json>...</json> tags as a JSON object with keys:
  summary, core_competencies, skills, experience

Use empty strings for sections that cannot be found.
"""

_INFER_SECTOR_SYSTEM = """\
You are an industry classifier. Return a JSON object inside <json>...</json>
tags with exactly two keys:
  sector       — e.g. "Technology / Software"
  functional_area — e.g. "Data Engineering"
"""


# ── Adapter ───────────────────────────────────────────────────────────────────


class AnthropicAdapter:
    """LLM adapter backed by the Anthropic Claude API.

    Args:
        model: Claude model identifier. Defaults to ``"claude-sonnet-4-6"``.
        api_key: Anthropic API key.
        max_tokens: Maximum tokens to request per completion.
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_key: str = "",
        max_tokens: int = _MAX_TOKENS,
    ) -> None:
        try:
            import anthropic  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "anthropic package is required for AnthropicAdapter. "
                "Install it with: uv pip install 'cv-skill[anthropic]'"
            ) from exc

        self._model = model
        self._max_tokens = max_tokens
        self._client = anthropic.Anthropic(api_key=api_key)

    def _chat(self, system: str, user: str) -> str:
        """Call the Anthropic Messages endpoint.

        Args:
            system: System prompt instructing the model to wrap output in
                ``<json>...</json>`` tags.
            user: User message containing the task data.

        Returns:
            Raw content text from the first content block.

        Raises:
            RuntimeError: If the API call fails or returns no content.
        """
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if not response.content:
            raise RuntimeError("Anthropic API returned empty content")
        # Content is a list of blocks; collect all text blocks.
        parts = [block.text for block in response.content if hasattr(block, "text")]
        return "\n".join(parts)

    def _extract_json(self, raw: str) -> Any:
        """Extract and parse JSON from inside ``<json>...</json>`` tags.

        Falls back to parsing the entire string as JSON when tags are absent
        (e.g. when the model ignores the instruction).

        Args:
            raw: Raw response text from the LLM.

        Returns:
            Parsed Python object.

        Raises:
            ValueError: If no valid JSON can be extracted.
        """
        # Prefer the tagged form.
        match = re.search(r"<json>(.*?)</json>", raw, re.DOTALL)
        candidate = match.group(1).strip() if match else raw.strip()

        # Strip Markdown code fences just in case.
        if candidate.startswith("```"):
            lines = candidate.splitlines()
            candidate = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            ).strip()

        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Could not parse JSON from LLM response: {exc}\nRaw: {raw[:500]}"
            ) from exc

    # ── LLMAdapter protocol methods ───────────────────────────────────────────

    def parse_jd(self, raw_text: str, url: str) -> ParsedJD:
        """Extract structured data from raw job description text.

        Args:
            raw_text: Plain text of the job posting.
            url: Canonical URL of the posting.

        Returns:
            Populated :class:`~cv_skill.schema.ParsedJD`.
        """
        user_msg = f"Job posting URL: {url}\n\n---\n\n{raw_text}"
        raw = self._chat(_PARSE_JD_SYSTEM, user_msg)
        data = self._extract_json(raw)
        data.setdefault("url", url)
        return ParsedJD.model_validate(data)

    def tailor_cv(self, jd: ParsedJD, cv: CVContent) -> TailoredCV:
        """Rewrite CV sections to match the job description.

        Args:
            jd: Parsed job description.
            cv: Original CV sections.

        Returns:
            :class:`~cv_skill.schema.TailoredCV` with all four sections.
        """
        user_msg = (
            f"## Job Description\n\n"
            f"Title: {jd.title}\nCompany: {jd.company}\n"
            f"Must-haves: {', '.join(jd.must_haves)}\n"
            f"Tech stack: {', '.join(jd.tech_stack)}\n"
            f"ATS keywords: {', '.join(jd.ats_keywords)}\n\n"
            f"## Current CV\n\n"
            f"### Summary\n{cv.summary}\n\n"
            f"### Core Competencies\n{cv.core_competencies}\n\n"
            f"### Skills\n{cv.skills}\n\n"
            f"### Experience\n{cv.experience}"
        )
        raw = self._chat(_TAILOR_CV_SYSTEM, user_msg)
        data = self._extract_json(raw)
        return TailoredCV.model_validate(data)

    def analyze_gaps(
        self,
        jd: ParsedJD,
        cv: CVContent,
        matches: list[KeywordMatch],
    ) -> list[GapAnalysis]:
        """Classify each missing ATS keyword.

        Args:
            jd: Parsed job description.
            cv: CV content for context.
            matches: Per-keyword match results; only missing ones are sent.

        Returns:
            List of :class:`~cv_skill.schema.GapAnalysis` items.
        """
        missing = [m.keyword for m in matches if not m.present]
        if not missing:
            return []

        user_msg = (
            f"## Job: {jd.title} at {jd.company}\n\n"
            f"## CV Summary (excerpt)\n{cv.summary[:500]}\n\n"
            f"## Missing Keywords\n"
            + "\n".join(f"- {kw}" for kw in missing)
        )
        raw = self._chat(_ANALYZE_GAPS_SYSTEM, user_msg)
        data = self._extract_json(raw)
        if isinstance(data, dict):
            # Model may wrap array in a container key.
            data = next(iter(data.values())) if len(data) == 1 else data.get("gap_analysis", [])
        return [GapAnalysis.model_validate(item) for item in data]

    def parse_cv_text(self, raw_text: str) -> CVContent:
        """Parse raw extracted CV text into structured sections.

        Args:
            raw_text: Markdown text from markitdown.

        Returns:
            :class:`~cv_skill.schema.CVContent`.
        """
        raw = self._chat(_PARSE_CV_SYSTEM, raw_text[:8000])
        data = self._extract_json(raw)
        return CVContent.model_validate(data)

    def infer_sector(self, raw_text: str) -> tuple[str, str]:
        """Return ``(sector, functional_area)`` from CV or JD text.

        Args:
            raw_text: Plain text of the CV or job description.

        Returns:
            ``(sector, functional_area)`` tuple.
        """
        raw = self._chat(_INFER_SECTOR_SYSTEM, raw_text[:4000])
        data = self._extract_json(raw)
        return data.get("sector", ""), data.get("functional_area", "")
