"""Skill-specific exception hierarchy.

All exceptions carry a human-readable message and a machine-readable
``to_dict`` representation so callers can embed errors in structured
response objects without re-parsing string messages.
"""

from __future__ import annotations


class SkillError(Exception):
    """Base class for all cv_skill errors.

    Args:
        message: Human-readable description of the failure.
        detail: Optional extra context (e.g. upstream error message).
    """

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, str]:
        """Serialise the error to a plain dict suitable for JSON responses.

        Returns:
            Dict with ``error``, ``message``, and optional ``detail`` keys.
        """
        result: dict[str, str] = {
            "error": type(self).__name__,
            "message": self.message,
        }
        if self.detail:
            result["detail"] = self.detail
        return result


class ScrapingError(SkillError):
    """Raised when a job posting cannot be fetched or parsed."""


class LLMError(SkillError):
    """Raised when the LLM adapter fails to produce a valid response."""


class ValidationError(SkillError):
    """Raised when input or LLM output fails Pydantic validation."""


class FileSystemError(SkillError):
    """Raised when reading CV content files or writing output fails."""
