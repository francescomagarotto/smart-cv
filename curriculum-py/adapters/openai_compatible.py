"""OpenAI-compatible LLM adapter.

Works for:
- OpenAI (default ``base_url=None``)
- Qwen via DashScope (``base_url=QWEN_BASE_URL``)
- DeepSeek (``base_url=DEEPSEEK_BASE_URL``)

Requires: ``openai>=1.0`` (install with ``uv pip install 'cv-skill[openai]'``).

Structured outputs are requested via ``response_format`` where the model
supports it. For models that do not advertise JSON-schema support we fall back
to a plain ``json_object`` response format and parse manually.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from cv_skill.schema import CVContent, GapAnalysis, KeywordMatch, ParsedJD, TailoredCV

log = logging.getLogger(__name__)

# ── Provider base-URL constants ───────────────────────────────────────────────

QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"


# ── System prompts ────────────────────────────────────────────────────────────

_PARSE_JD_SYSTEM = """\
You are an expert technical recruiter and ATS specialist.
Given the raw text of a job posting, extract structured information and return
it as a JSON object matching the schema provided.

Rules:
- Extract only what is explicitly stated — do not infer or fabricate.
- ats_keywords must be a deduplicated flat list of all ATS-relevant terms
  (tools, skills, methodologies, certifications) found in the posting.
- tech_stack should list specific technologies only (no soft skills).
- must_haves and nice_to_haves should be concise bullet strings.
"""

_TAILOR_CV_SYSTEM = """\
You are an expert CV writer specialising in technical roles.
Rewrite the provided CV sections to maximise keyword alignment with the job
description. Return a JSON object with the four rewritten sections.

Strict rules — violations will be rejected:
1. NEVER fabricate skills, tools, achievements, or experiences not present in
   the original CV.
2. Preserve all factual claims; you may rephrase but not invent.
3. Prioritise ATS keywords from the job description naturally within the text.
4. Keep the same Markdown formatting conventions as the originals.
5. Do not add new bullet points that describe work never done.
"""

_ANALYZE_GAPS_SYSTEM = """\
You are an ATS gap analyst. Given a parsed job description and a list of
keywords not found in the CV, classify each missing keyword as one of:
- "fillable": The CV holder likely has this skill but did not mention it.
  Suggest where to add it.
- "stretchable": Adjacent skill the candidate could reasonably claim with
  minimal context.
- "genuine_gap": Skill genuinely absent; no actionable suggestion.

Return a JSON array of objects matching the GapAnalysis schema.
"""

_PARSE_CV_SYSTEM = """\
You are a CV parser. Given raw text or Markdown extracted from a CV PDF,
identify and extract the four canonical sections. Return a JSON object with:
- summary: professional summary or profile paragraph(s)
- core_competencies: bullet list of core competencies/skills
- skills: categorised skill list
- experience: work experience entries with bullets

If a section cannot be found, return an empty string for that field.
"""

_INFER_SECTOR_SYSTEM = """\
You are an industry classifier. Given CV or job description text, infer:
1. The industry sector (e.g. "Technology / Software", "Finance / FinTech").
2. The functional area (e.g. "Data Engineering", "Platform Engineering").

Return a JSON object with exactly two keys: "sector" and "functional_area".
"""


# ── Adapter ───────────────────────────────────────────────────────────────────


class OpenAICompatibleAdapter:
    """LLM adapter for OpenAI and OpenAI-compatible APIs.

    Args:
        model: Model identifier (e.g. ``"gpt-4o"``, ``"qwen-plus"``).
        api_key: Provider API key.
        base_url: Optional API base URL. Pass ``QWEN_BASE_URL`` or
            ``DEEPSEEK_BASE_URL`` for third-party providers. Defaults to the
            standard OpenAI endpoint when ``None``.
        max_tokens: Maximum tokens to request per completion.
        temperature: Sampling temperature. Defaults to ``0`` for deterministic
            outputs.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> None:
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "openai package is required for OpenAICompatibleAdapter. "
                "Install it with: uv pip install 'cv-skill[openai]'"
            ) from exc

        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)

    def _chat(self, system: str, user: str, schema: dict | None = None) -> str:
        """Call the chat completions endpoint and return the raw content string.

        Args:
            system: System prompt.
            user: User message.
            schema: Optional JSON schema dict for structured output. When
                provided, ``response_format`` is set to ``json_schema`` if
                supported, otherwise falls back to ``json_object``.

        Returns:
            Raw content string from the first choice.

        Raises:
            RuntimeError: If the API call fails or returns no content.
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if schema is not None:
            # Prefer json_schema (structured outputs) when a schema is given;
            # fall back to json_object for providers that don't support it.
            try:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "response",
                        "strict": True,
                        "schema": schema,
                    },
                }
                response = self._client.chat.completions.create(**kwargs)
            except Exception:
                # Provider does not support json_schema — fall back.
                log.debug("json_schema not supported by %s — falling back to json_object", self._model)
                kwargs["response_format"] = {"type": "json_object"}
                response = self._client.chat.completions.create(**kwargs)
        else:
            response = self._client.chat.completions.create(**kwargs)

        content = response.choices[0].message.content
        if content is None:
            raise RuntimeError("LLM returned empty content")
        return content

    def _parse_json(self, raw: str) -> Any:
        """Parse a JSON string, stripping Markdown code fences if present.

        Args:
            raw: Raw string from the LLM, possibly wrapped in ```json...```.

        Returns:
            Parsed Python object.

        Raises:
            ValueError: If the string cannot be parsed as JSON.
        """
        stripped = raw.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            # Drop opening ``` line and closing ``` line.
            inner = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            stripped = inner.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM response is not valid JSON: {exc}\nRaw: {raw[:500]}") from exc

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
        schema = ParsedJD.model_json_schema()
        raw = self._chat(_PARSE_JD_SYSTEM, user_msg, schema=schema)
        data = self._parse_json(raw)
        # Ensure the url field is set even if the model omitted it.
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
        schema = TailoredCV.model_json_schema()
        raw = self._chat(_TAILOR_CV_SYSTEM, user_msg, schema=schema)
        data = self._parse_json(raw)
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
        data = self._parse_json(raw)
        if isinstance(data, dict) and "gap_analysis" in data:
            data = data["gap_analysis"]
        return [GapAnalysis.model_validate(item) for item in data]

    def parse_cv_text(self, raw_text: str) -> CVContent:
        """Parse raw extracted CV text into structured sections.

        Args:
            raw_text: Markdown text from markitdown.

        Returns:
            :class:`~cv_skill.schema.CVContent`.
        """
        schema = CVContent.model_json_schema()
        raw = self._chat(_PARSE_CV_SYSTEM, raw_text[:8000], schema=schema)
        data = self._parse_json(raw)
        return CVContent.model_validate(data)

    def infer_sector(self, raw_text: str) -> tuple[str, str]:
        """Return ``(sector, functional_area)`` from CV or JD text.

        Args:
            raw_text: Plain text of the CV or job description.

        Returns:
            ``(sector, functional_area)`` tuple.
        """
        raw = self._chat(_INFER_SECTOR_SYSTEM, raw_text[:4000])
        data = self._parse_json(raw)
        return data.get("sector", ""), data.get("functional_area", "")


# ── Convenience constructors ──────────────────────────────────────────────────


def make_qwen_adapter(api_key: str, model: str = "qwen-plus") -> OpenAICompatibleAdapter:
    """Create an :class:`OpenAICompatibleAdapter` pre-configured for Qwen.

    Args:
        api_key: DashScope API key.
        model: Qwen model identifier. Defaults to ``"qwen-plus"``.

    Returns:
        Configured :class:`OpenAICompatibleAdapter` instance.
    """
    return OpenAICompatibleAdapter(model=model, api_key=api_key, base_url=QWEN_BASE_URL)


def make_deepseek_adapter(api_key: str, model: str = "deepseek-chat") -> OpenAICompatibleAdapter:
    """Create an :class:`OpenAICompatibleAdapter` pre-configured for DeepSeek.

    Args:
        api_key: DeepSeek API key.
        model: DeepSeek model identifier. Defaults to ``"deepseek-chat"``.

    Returns:
        Configured :class:`OpenAICompatibleAdapter` instance.
    """
    return OpenAICompatibleAdapter(model=model, api_key=api_key, base_url=DEEPSEEK_BASE_URL)
