#!/usr/bin/env python3
"""Build tex/*.tex from content/*.md.  Run: python curriculum-py/template_builder.py [--template <name>] [--content-dir <dir>]"""

import argparse
import importlib.util
import logging
import re
import shutil
import sys
from pathlib import Path

logging.basicConfig(format="%(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)


class ContentParser:
    """Parses content/*.md files into plain Python data structures — no LaTeX."""

    def __init__(self, content_dir: Path) -> None:
        self._dir = content_dir

    def heading(self) -> dict[str, str]:
        raw = (self._dir / "heading.md").read_text()
        m = re.search(r"^---\n(.+?)\n---", raw, re.DOTALL)
        if not m:
            log.error("heading.md missing frontmatter")
            sys.exit(1)
        fields: dict[str, str] = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fields[k.strip()] = v.strip().strip('"')
        return fields

    def summary(self) -> list[str]:
        text = (self._dir / "summary.md").read_text().strip()
        return [p.strip() for p in text.split("\n\n") if p.strip()]

    def competencies(self) -> list[str]:
        text = (self._dir / "core_competencies.md").read_text()
        return [l[2:].strip() for l in text.splitlines() if l.startswith("- ")]

    def experience(self) -> tuple[list[dict], list[dict]]:
        text = (self._dir / "experience.md").read_text()
        raw_blocks = re.split(r"\n\n---\n\n|\n---\n", text)

        roles: list[dict] = []
        projects: list[dict] = []

        for block in raw_blocks:
            block = block.strip()
            if not block:
                continue
            pagebreak = "<!-- pagebreak -->" in block
            block = block.replace("<!-- pagebreak -->", "").strip()

            if block.startswith("## Selected Projects"):
                proj_body = re.sub(r"^## Selected Projects\s*", "", block).strip()
                for pb in re.split(r"\n###\s+", proj_body):
                    pb = pb.strip()
                    if not pb:
                        continue
                    lines = pb.splitlines()
                    name = re.sub(r"^#{1,6}\s+", "", lines[0]).strip()
                    kind = ""
                    bullets: list[str] = []
                    for l in lines[1:]:
                        if re.match(r"^- ", l):
                            bullets.append(l[2:].strip())
                        elif l.strip() and not kind:
                            kind = l.strip()
                    projects.append({"name": name, "kind": kind, "bullets": bullets})

            elif block.startswith("## "):
                lines = block.splitlines()
                company = re.sub(r"^##\s+", "", lines[0]).strip()
                role = lines[1].strip("* ") if len(lines) > 1 else ""
                date_loc = lines[2].strip() if len(lines) > 2 else ""
                dates, _, location = date_loc.partition("|")
                roles.append({
                    "company": company,
                    "role": role,
                    "dates": dates.strip(),
                    "location": location.strip(),
                    "bullets": self._strip_bullets(lines),
                    "pagebreak": pagebreak,
                })

        return roles, projects

    def skills(self) -> list[tuple[str, str]]:
        text = (self._dir / "skills.md").read_text()
        categories: list[tuple[str, str]] = []
        name, items = "", []
        for line in text.splitlines():
            if line.startswith("## "):
                if name:
                    categories.append((name, " ".join(items)))
                name, items = line[3:].strip(), []
            elif line.strip():
                items.append(line.strip())
        if name:
            categories.append((name, " ".join(items)))
        return categories

    def education(self) -> list[dict]:
        text = (self._dir / "education.md").read_text()
        raw_blocks = re.split(r"\n\n---\n\n|\n---\n", text)
        degrees: list[dict] = []
        for block in raw_blocks:
            block = block.strip()
            if not block or not block.startswith("## "):
                continue
            lines = block.splitlines()
            institution = re.sub(r"^##\s+", "", lines[0]).strip()
            degree = lines[1].strip("* ") if len(lines) > 1 else ""
            date_loc = lines[2].strip() if len(lines) > 2 else ""
            dates, _, location = date_loc.partition("|")
            degrees.append({
                "institution": institution,
                "degree": degree,
                "dates": dates.strip(),
                "location": location.strip(),
                "bullets": self._strip_bullets(lines),
            })
        return degrees

    @staticmethod
    def _strip_bullets(lines: list[str]) -> list[str]:
        return [l[2:].strip() for l in lines if re.match(r"^- ", l)]


# ── template loading ──────────────────────────────────────────────────────────

def _load_renderer(template_name: str):
    renderer_path = Path(__file__).parent / "renderers" / f"{template_name}.py"
    if not renderer_path.exists():
        log.error(f"renderer not found: {renderer_path}")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("renderer", renderer_path)
    if spec is None or spec.loader is None:
        log.error(f"could not load renderer: {renderer_path}")
        sys.exit(1)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _apply_template(template_dir: Path, tex_dir: Path, template_name: str) -> None:
    for fname in ("main.tex", "custom-commands.tex"):
        src = template_dir / fname
        if src.exists():
            shutil.copy2(src, tex_dir / fname)
            log.info(f"tex/{fname} <- templates/{template_name}")


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Build tex/*.tex from content/*.md")
    ap.add_argument("--content-dir", default="content", help="Source markdown directory (default: content)")
    ap.add_argument("--template", default="default", help="Template name under templates/ (default: default)")
    args = ap.parse_args()

    content_dir = Path(args.content_dir)
    tex_dir = Path("tex")
    template_dir = Path("templates") / args.template

    if not template_dir.exists():
        log.error(f"template not found: {template_dir}")
        sys.exit(1)

    parser = ContentParser(content_dir)
    renderer = _load_renderer(args.template)
    setattr(renderer, "TEMPLATE_DIR", template_dir)

    sections = [
        ("heading.tex",                lambda: renderer.render_heading(parser.heading())),
        ("summary.tex",                lambda: renderer.render_summary(parser.summary())),
        ("core_competencies.tex",      lambda: renderer.render_competencies(parser.competencies())),
        ("experience_platform_ai.tex", lambda: renderer.render_experience(*parser.experience())),
        ("skills.tex",                 lambda: renderer.render_skills(parser.skills())),
        ("education.tex",              lambda: renderer.render_education(parser.education())),
    ]

    for filename, render in sections:
        (tex_dir / filename).write_text(render())
        log.info(filename)

    _apply_template(template_dir, tex_dir, args.template)
    log.info(f"done (template: {args.template}) — run: cd tex && pdflatex main.tex")


if __name__ == "__main__":
    main()
