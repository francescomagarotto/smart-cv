# CV Repository

## Purpose

LaTeX-based CV targeting senior data/platform engineering roles. Build and compile with:

```bash
python curriculum-py/template_builder.py && cd tex && pdflatex main.tex
```

## Project layout

```
curriculum-py/template_builder.py     # Build script: parses content/ → renders tex/ via the active template
content/                    # Source of truth — edit these Markdown files, never the tex/ files
  heading.md                # Name, contact, links — NEVER modify without asking
  summary.md                # Professional summary — primary tailoring target
  core_competencies.md      # Competency list — tailoring target
  experience.md             # Work experience + selected projects — tailoring target
  skills.md                 # Categorised skill list — tailoring target
  education.md              # Degrees — NEVER modify without asking
tex/                        # Generated LaTeX — do not edit directly
templates/
  default/
    main.tex                # Document class, packages, layout
    custom-commands.tex     # \resumeItem, \resumeSubheading, etc.
curriculum-py/renderers/
  default.py               # LaTeX generation logic for the default template
curriculum-py/              # uv project: template_builder.py + job_spider.py (venv at curriculum-py/.venv/)
```

## Branching convention

Each tailored application lives on its own branch:

```
cv/<company-slug>-<role-slug>
```

Examples: `cv/stripe-data-engineer`, `cv/anthropic-platform-engineer`

The `main` branch holds the canonical/base CV. Never commit tailored edits to `main`.

## ATS notes

- `\pdfgentounicode=1` is set — PDF is machine-readable
- No images, no multi-column body layout
- fancyhdr is cleared (no hidden header/footer content)
- Lato font is embedded via `[default]{lato}`

## Skills

### `/custom-cv <job-url> [branch-slug]`

Tailor the CV for a specific role:
1. Scrape the job description and infer industry sector + functional area
2. Create `cv/<branch>` branch
3. Tailor summary, competencies, skills, and experience bullets
4. Run ATS keyword audit + structural checks
5. Compile and commit
6. Optionally generate a tailored cover letter

### `/cv-audit <job-url>`

Read-only ATS audit — scrapes the JD and scores the current branch's CV against it. No edits made. Produces a keyword coverage table and gap analysis.

### `/extract-cv <pdf-path>`

Import an existing CV PDF into `content/`:
1. Extract text via `markitdown`
2. Parse into canonical sections (heading, summary, competencies, experience, skills, education)
3. Infer the owner's industry sector and functional area
4. Write clean Markdown files to `content/` (or a test directory with `--output`)
5. Prompt for any fields that could not be extracted (e.g. LinkedIn URL)
