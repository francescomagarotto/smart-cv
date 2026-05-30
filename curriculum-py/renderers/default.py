"""Default template renderer — Jinja2 with LaTeX-safe delimiters (<< >>, <% %>)."""

import re
from pathlib import Path

import jinja2

TEMPLATE_DIR: Path = Path("templates/default")

_SPECIAL = str.maketrans({"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_"})


def esc(s: str) -> str:
    return s.translate(_SPECIAL)


def inline(s: str) -> str:
    parts = re.split(r"\*\*(.+?)\*\*", s)
    return "".join(
        f"\\textbf{{{esc(p)}}}" if i % 2 else esc(p)
        for i, p in enumerate(parts)
    )


def _render(template_name: str, **kwargs) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        variable_start_string="<<",
        variable_end_string=">>",
        block_start_string="<%",
        block_end_string="%>",
        comment_start_string="<#",
        comment_end_string="#>",
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.globals.update(esc=esc, inline=inline)
    return env.get_template(template_name).render(**kwargs)


def render_heading(data: dict) -> str:
    return _render("heading.tex.j2", **data)


def render_summary(paragraphs: list[str]) -> str:
    return _render("summary.tex.j2", paragraphs=paragraphs)


def render_competencies(items: list[str]) -> str:
    rows = []
    for i in range(0, len(items), 3):
        chunk = items[i:i+3]
        cells = [f"$\\bullet$ {esc(c)}" for c in chunk]
        cells += [""] * (3 - len(cells))
        rows.append(cells)
    return _render("core_competencies.tex.j2", rows=rows)


def render_experience(roles: list[dict], projects: list[dict]) -> str:
    return _render("experience.tex.j2", roles=roles, projects=projects)


def render_skills(categories: list[tuple[str, str]]) -> str:
    skill_block = " \\\\\n        ".join(
        f"\\textbf{{{esc(n)}}}: {esc(v)}" for n, v in categories
    )
    return _render("skills.tex.j2", skill_block=skill_block)


def render_education(degrees: list[dict]) -> str:
    return _render("education.tex.j2", degrees=degrees)
