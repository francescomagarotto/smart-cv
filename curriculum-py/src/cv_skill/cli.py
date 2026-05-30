"""Typer CLI for the cv_skill package.

Usage examples::

    cv-skill custom-cv examples/custom_cv_request.json
    cv-skill cv-audit examples/cv_audit_request.json --provider openai
    cv-skill extract-cv examples/extract_cv_request.json --provider deepseek

Provider adapters are loaded lazily so that only the SDK for the chosen
provider needs to be installed.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Annotated

import typer

log = logging.getLogger(__name__)

app = typer.Typer(
    name="cv-skill",
    help="Model-agnostic CV tailoring pipeline for LaTeX CVs.",
    add_completion=False,
)

_PROVIDER_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "qwen": "QWEN_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

_DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-6",
    "qwen": "qwen-plus",
    "deepseek": "deepseek-chat",
}


def _get_api_key(provider: str) -> str:
    """Read the API key for ``provider`` from the environment.

    Args:
        provider: One of ``"openai"``, ``"anthropic"``, ``"qwen"``,
            ``"deepseek"``.

    Returns:
        The API key string.

    Raises:
        typer.Exit: If the environment variable is not set.
    """
    env_var = _PROVIDER_ENV_KEYS[provider]
    key = os.environ.get(env_var, "")
    if not key:
        typer.echo(f"Error: environment variable {env_var} is not set.", err=True)
        raise typer.Exit(code=1)
    return key


def _load_adapter(provider: str, model: str | None) -> object:
    """Lazily load and instantiate the LLM adapter for ``provider``.

    Args:
        provider: Provider name.
        model: Optional model override; falls back to ``_DEFAULT_MODELS``.

    Returns:
        Instantiated adapter implementing the ``LLMAdapter`` Protocol.

    Raises:
        typer.Exit: If the adapter module cannot be imported (SDK not installed).
    """
    effective_model = model or _DEFAULT_MODELS[provider]
    api_key = _get_api_key(provider)

    # Compute path to adapters/ relative to this file's installed location.
    adapters_dir = Path(__file__).parent.parent.parent / "adapters"

    if provider in ("openai", "qwen", "deepseek"):
        adapter_path = adapters_dir / "openai_compatible.py"
        try:
            spec = importlib.util.spec_from_file_location("openai_compatible", adapter_path)
            if spec is None or spec.loader is None:
                raise ImportError("Could not create spec")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except ImportError as exc:
            typer.echo(
                f"Error: could not load OpenAI-compatible adapter. "
                f"Install it with: uv pip install 'cv-skill[openai]'\n{exc}",
                err=True,
            )
            raise typer.Exit(code=1) from exc

        if provider == "qwen":
            return module.make_qwen_adapter(api_key=api_key, model=effective_model)
        if provider == "deepseek":
            return module.make_deepseek_adapter(api_key=api_key, model=effective_model)
        return module.OpenAICompatibleAdapter(model=effective_model, api_key=api_key)

    # provider == "anthropic"
    adapter_path = adapters_dir / "anthropic_tool.py"
    try:
        spec = importlib.util.spec_from_file_location("anthropic_tool", adapter_path)
        if spec is None or spec.loader is None:
            raise ImportError("Could not create spec")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except ImportError as exc:
        typer.echo(
            f"Error: could not load Anthropic adapter. "
            f"Install it with: uv pip install 'cv-skill[anthropic]'\n{exc}",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    return module.AnthropicAdapter(model=effective_model, api_key=api_key)


def _read_request_file(path: Path) -> dict:
    """Parse a JSON request file.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed dict.

    Raises:
        typer.Exit: If the file does not exist or is invalid JSON.
    """
    if not path.exists():
        typer.echo(f"Error: request file not found: {path}", err=True)
        raise typer.Exit(code=1)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        typer.echo(f"Error: invalid JSON in {path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# ── Subcommands ───────────────────────────────────────────────────────────────

_ProviderArg = Annotated[
    str,
    typer.Option(
        "--provider",
        help="LLM provider: openai | anthropic | qwen | deepseek",
        show_default=True,
    ),
]
_ModelArg = Annotated[
    str | None,
    typer.Option("--model", help="Model name override (provider default used if omitted)"),
]


@app.command("custom-cv")
def cmd_custom_cv(
    request_file: Annotated[Path, typer.Argument(help="Path to CustomCVRequest JSON file")],
    provider: _ProviderArg = "anthropic",
    model: _ModelArg = None,
) -> None:
    """Tailor the CV for a specific job posting and run an ATS audit."""
    from cv_skill.core import run_custom_cv
    from cv_skill.schema import CustomCVRequest

    if provider not in _PROVIDER_ENV_KEYS:
        typer.echo(f"Error: unknown provider '{provider}'.", err=True)
        raise typer.Exit(code=1)

    raw = _read_request_file(request_file)
    try:
        request = CustomCVRequest.model_validate(raw)
    except Exception as exc:
        typer.echo(f"Error: invalid request payload: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    llm = _load_adapter(provider, model)
    response = run_custom_cv(request, llm)  # type: ignore[arg-type]
    typer.echo(response.model_dump_json(indent=2))

    if response.status == "error":
        raise typer.Exit(code=1)


@app.command("cv-audit")
def cmd_cv_audit(
    request_file: Annotated[Path, typer.Argument(help="Path to CVAuditRequest JSON file")],
    provider: _ProviderArg = "anthropic",
    model: _ModelArg = None,
) -> None:
    """Read-only ATS audit: scrape the JD and score the current CV."""
    from cv_skill.core import run_cv_audit
    from cv_skill.schema import CVAuditRequest

    if provider not in _PROVIDER_ENV_KEYS:
        typer.echo(f"Error: unknown provider '{provider}'.", err=True)
        raise typer.Exit(code=1)

    raw = _read_request_file(request_file)
    try:
        request = CVAuditRequest.model_validate(raw)
    except Exception as exc:
        typer.echo(f"Error: invalid request payload: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    llm = _load_adapter(provider, model)
    response = run_cv_audit(request, llm)  # type: ignore[arg-type]
    typer.echo(response.model_dump_json(indent=2))

    if response.status == "error":
        raise typer.Exit(code=1)


@app.command("extract-cv")
def cmd_extract_cv(
    request_file: Annotated[Path, typer.Argument(help="Path to ExtractCVRequest JSON file")],
    provider: _ProviderArg = "anthropic",
    model: _ModelArg = None,
) -> None:
    """Extract a CV from a PDF and write structured Markdown files."""
    from cv_skill.core import run_extract_cv
    from cv_skill.schema import ExtractCVRequest

    if provider not in _PROVIDER_ENV_KEYS:
        typer.echo(f"Error: unknown provider '{provider}'.", err=True)
        raise typer.Exit(code=1)

    raw = _read_request_file(request_file)
    try:
        request = ExtractCVRequest.model_validate(raw)
    except Exception as exc:
        typer.echo(f"Error: invalid request payload: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    llm = _load_adapter(provider, model)
    response = run_extract_cv(request, llm)  # type: ignore[arg-type]
    typer.echo(response.model_dump_json(indent=2))

    if response.status == "error":
        raise typer.Exit(code=1)


def main() -> None:
    """Entry point registered in pyproject.toml."""
    logging.basicConfig(
        format="%(levelname)s %(name)s %(message)s",
        level=logging.INFO,
        stream=sys.stderr,
    )
    app()


if __name__ == "__main__":
    main()
