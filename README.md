# smart-cv

A LaTeX CV pipeline with AI-assisted tailoring. Edit plain Markdown — get a clean, ATS-friendly PDF. Apply to a job in minutes with a single slash command.

---

## How it works

```
content/*.md  →  template_builder.py  →  tex/  →  pdflatex  →  PDF
```

The `content/` directory is your single source of truth. You never touch the generated LaTeX directly. To tailor the CV for a specific role, Claude Code scrapes the job posting, creates a dedicated branch, rewrites the relevant sections, and runs an ATS keyword audit — all automatically.

---

## Quick start

### Build (Docker — recommended)

```bash
docker build -t curriculum .
docker run --rm -v $(pwd):/cv curriculum \
  bash -c "python3 curriculum-py/template_builder.py && cd tex && texliveonfly main.tex"
```

`texliveonfly` auto-installs any missing LaTeX packages on the first run.

### Build (locally)

Requires Python 3 and a TeX Live installation with `pdflatex`.

```bash
python curriculum-py/template_builder.py
cd tex && pdflatex main.tex
```

---

## Project layout

```
content/                     # Edit these — never touch tex/
  heading.md                 #   Name, contact info, links
  summary.md                 #   Professional summary
  core_competencies.md       #   Competency list
  experience.md              #   Work history + selected projects
  skills.md                  #   Categorised skill list
  education.md               #   Degrees
tex/                         # Generated LaTeX (auto-overwritten on each build)
templates/
  default/
    main.tex                 # Document class, packages, layout
    custom-commands.tex      # \resumeItem, \resumeSubheading, etc.
    *.tex.j2                 # Jinja2 section templates
curriculum-py/
  template_builder.py        # ContentParser + build orchestration
  renderers/default.py       # Jinja2 rendering logic for the default template
  job_spider.py              # Job description scraper (JobScraper class)
```

---

## Tailoring for a role

Each application lives on its own branch:

```
cv/<company-slug>-<role-slug>
```

Examples: `cv/stripe-data-engineer`, `cv/anthropic-platform-engineer`

`main` holds the canonical CV. Tailored edits never touch it.

### Claude Code skills

Open this repo in Claude Code and use the built-in slash commands:

| Command | What it does |
|---------|-------------|
| `/custom-cv <job-url>` | Scrape the JD, create a branch, tailor all CV sections, ATS audit, compile |
| `/cv-audit <job-url>` | Score the current CV against a posting — no edits |
| `/extract-cv <pdf-path>` | Import an existing CV PDF into `content/` |

`/custom-cv` infers the **industry sector** and **functional area** of the target role and applies sector-specific tailoring — compliance keywords for regulated industries, velocity language for startups, domain vocabulary for specialist fields.

---

## Adding a new LaTeX template

A template is a folder under `templates/` paired with a renderer module under `curriculum-py/renderers/`.

### 1 — Create the template folder

```
templates/
  my-template/
    main.tex              # Document class, packages, page geometry
    custom-commands.tex   # Any custom LaTeX commands the sections rely on
    heading.tex.j2        # Jinja2 template for the heading section
    summary.tex.j2        # Jinja2 template for the summary
    core_competencies.tex.j2
    experience.tex.j2
    skills.tex.j2
    education.tex.j2
```

Copy `templates/default/` as a starting point and modify to taste.

### 2 — Write the Jinja2 section templates

Templates use `<< var >>` for variables and `<% for / if %>` for control flow — chosen to avoid conflicts with LaTeX braces. Two helpers are available in every template:

| Helper | What it does |
|--------|-------------|
| `esc(s)` | Escapes LaTeX special characters (`&`, `%`, `$`, `#`, `_`) |
| `inline(s)` | Converts `**bold**` Markdown to `\textbf{...}` |

Example section template:

```latex
\section{Skills}
    \begin{itemize}
<% for name, value in categories %>
        \item \textbf{<< esc(name) >>}: << esc(value) >>
<% endfor %>
    \end{itemize}
```

### 3 — Create the renderer module

Add `curriculum-py/renderers/my-template.py`. The renderer must expose six functions with these exact signatures:

```python
def render_heading(data: dict) -> str: ...
def render_summary(paragraphs: list[str]) -> str: ...
def render_competencies(items: list[str]) -> str: ...
def render_experience(roles: list[dict], projects: list[dict]) -> str: ...
def render_skills(categories: list[tuple[str, str]]) -> str: ...
def render_education(degrees: list[dict]) -> str: ...
```

Copy `curriculum-py/renderers/default.py` and update the template filenames. The `_render()` helper and `esc`/`inline` utilities can be reused as-is.

### 4 — Build with the new template

```bash
python curriculum-py/template_builder.py --template my-template
cd tex && pdflatex main.tex
```

Or with Docker:

```bash
docker run --rm -v $(pwd):/cv curriculum \
  bash -c "python3 curriculum-py/template_builder.py --template my-template && cd tex && texliveonfly main.tex"
```

---

## ATS compatibility

- `\pdfgentounicode=1` — machine-readable text layer
- Lato font embedded via `[default]{lato}`
- No images, no multi-column body, no hidden header/footer content
- All URLs use `\href` with readable link text

---

## Guardrails

The tailoring pipeline only reorders, reframes, and emphasises existing content. It never fabricates experience, tools, or credentials. If a keyword gap cannot be filled honestly, it says so.
