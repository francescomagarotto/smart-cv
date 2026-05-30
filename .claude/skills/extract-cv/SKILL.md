---
name: extract-cv
description: Extracts content from an existing CV PDF using markitdown, parses it into structured sections, and writes clean Markdown files to the content/ directory. Use this to onboard a new CV (your own or someone else's) into the LaTeX pipeline.
---

# Extract CV

The user invokes this as `/extract-cv <pdf-path> [--output <dir>]`.

- `pdf-path` (required): absolute or relative path to the CV PDF file
- `--output <dir>` (optional): directory to write the `.md` files into. Defaults to `content/`. Use `content-test/` to do a dry run without touching the real content.

This skill is **non-destructive by default**: if the output directory already has `.md` files, it will warn before overwriting. If a `--force` flag is passed, overwrite silently.

The output directory is referred to as `<out>` throughout these steps.

---

## Step 1 — Validate input

Check the PDF exists:
```bash
test -f "<pdf-path>" && echo "ok" || echo "NOT_FOUND"
```

If not found, tell the user and abort.

Check the file is a PDF (magic bytes or extension). If it's not a PDF, warn and ask to confirm before proceeding — markitdown can handle DOCX too, but results vary.

---

## Step 2 — Ensure markitdown is installed

Reuse the scraper venv:
```bash
curriculum-py/.venv/bin/python -c "import markitdown; print(markitdown.__version__)" 2>/dev/null \
  || curriculum-py/.venv/bin/pip install "markitdown[pdf]" -q
```

If the venv doesn't exist yet, create it first:
```bash
python3 -m venv curriculum-py/.venv && curriculum-py/.venv/bin/pip install -r curriculum-py/requirements.txt -q
```

If installation fails, tell the user to run:
```
curriculum-py/.venv/bin/pip install markitdown
```
Then abort.

---

## Step 3 — Run markitdown

```bash
curriculum-py/.venv/bin/python -c "
from markitdown import MarkItDown
md = MarkItDown()
result = md.convert('<pdf-path>')
print(result.text_content)
" 2>/dev/null
```

Capture the full output as `raw_md`.

Quality checks:
- If `raw_md` is shorter than 500 characters: warn that the PDF may be image-based or encrypted; ask the user if they want to proceed with the partial content or abort
- If `raw_md` contains obvious OCR garbage (repeated symbols, encoding artifacts): warn the user

Print:
```
📄 Extracted <N> characters from <filename>
```

---

## Step 4 — Parse into sections

Analyze `raw_md` and identify the following sections. Use context clues (headings, labels, formatting) to locate each one. The CV may use different section names — map them to the canonical ones below.

| Canonical section | Common headings to look for |
|-------------------|-----------------------------|
| heading | name at top, contact block (email, phone, LinkedIn, GitHub) |
| summary | Summary, Profile, About, Objective |
| core_competencies | Core Competencies, Key Skills, Highlights, Areas of Expertise |
| experience | Experience, Work Experience, Employment, Career |
| skills | Skills, Technical Skills, Technologies |
| education | Education, Academic Background, Degrees |

For each section, extract the content and clean it:
- Remove page numbers, header/footer artifacts, repeated name/contact lines on page 2+
- Normalize dashes and bullets to `-`
- Preserve meaningful bold/emphasis where inferable (e.g., company names, tool names)
- Dates: normalize to `Month YYYY – Month YYYY` or `Month YYYY – Present`

If a section is not found, note it and write an empty file with a comment so the user knows it's missing.

**No work experience** — if the CV has no experience section (student, career-starter, or career-changer), look for substitute content to populate `experience.md` instead:

| Substitute section | Common headings |
|--------------------|-----------------|
| Internships | Internships, Placements, Industrial Experience |
| Academic projects | Projects, University Projects, Capstone, Thesis |
| Volunteer work | Volunteering, Community, Non-profit |
| Extracurriculars | Activities, Leadership, Clubs |
| Freelance / side work | Freelance, Consulting, Independent |

Map each substitute to the same `## Company / ## Project` format as regular roles, using the organisation or project name as the heading and "Intern", "Student Project", "Volunteer", etc. as the role title. If no substitutes exist either, write `experience.md` empty with the comment `<!-- no work experience found -->` and flag it clearly in the Step 8 report.

### Step 4a — Infer sector

From the parsed CV content (summary, experience titles, skills, company names), infer:

**Industry sector** — the broad domain the person has primarily worked in. Examples:
- Technology / Software
- Financial Services / Fintech
- Healthcare / Life Sciences
- E-commerce / Retail
- Energy / Utilities
- Media / Entertainment
- Manufacturing / Industrial
- Education / EdTech
- Government / Public Sector
- Consulting / Professional Services

**Functional area** — the specific discipline the person specialises in. Examples:
- Data Engineering / Analytics Engineering
- Platform / Infrastructure Engineering
- Machine Learning / AI
- Software / Backend Engineering
- DevOps / Site Reliability
- Product Management
- Cybersecurity
- Business Analysis / BI

Use signals in order of confidence: explicit job titles > company types > skill categories > summary language.

If the person has worked across multiple sectors, list the primary one and note the others (e.g., "Technology — with stints in Finance and Consulting").

Store these as `inferred_sector` and `inferred_functional_area` to include in the Step 8 report and to pre-populate context for any subsequent `/custom-cv` or `/cv-audit` run.

---

## Step 5 — Check for existing files in <out>

```bash
ls <out>/*.md 2>/dev/null | wc -l
```

Create `<out>/` if it doesn't exist yet (`mkdir -p <out>`).

If any `.md` files exist and `--force` was not passed:
```
⚠️  <out>/ already contains X file(s). Overwriting will replace the current CV content.
Files that will be overwritten: <list>
Proceed? (y/n)
```

Wait for user confirmation before continuing.

---

## Step 6 — Resolve missing fields

Before writing any files, identify every heading field that could not be extracted from the PDF (common ones: `linkedin`, `github`, sometimes `phone` or `location`). For each missing field, ask the user to provide it in a single consolidated prompt:

```
⚠️ The following fields could not be extracted from the PDF. Please provide them:

  • linkedin URL: 
  • github URL: 
```

Wait for the user's reply and fill in the values before proceeding. If the user explicitly says to leave a field blank, write it as an empty string.

---

## Step 7 — Write <out>/ files

Write each section to its canonical file using this format:

### `<out>/heading.md`
YAML frontmatter only:
```markdown
---
name: <full name>
phone: "<phone>"
location: <city, country>
email: <email>
linkedin: <url>
github: <url>
---
```

### `<out>/summary.md`
Plain prose paragraphs. Preserve paragraph breaks. Use `**bold**` for tool/technology names if emphasis was present in the original.

### `<out>/core_competencies.md`
One bullet per competency:
```markdown
- <Competency 1>
- <Competency 2>
```
If this section is absent in the source CV, write an empty file with a note: `<!-- no core competencies section found — add manually -->`.

### `<out>/experience.md`
One `##` heading per employer, with role, dates, and location on the next line, then bullets:
```markdown
## <Company Name>
**<Role Title>**
<Start Month YYYY> – <End Month YYYY or Present> | <Location or Remote>

- <bullet>
- <bullet>

---

## Selected Projects

### <Project Name>
<Type: Personal Project / Open Source / etc.>

- <bullet>
```

### `<out>/skills.md`
One `##` heading per category, comma-separated items on the next line:
```markdown
## <Category>
<item 1>, <item 2>, <item 3>
```

### `<out>/education.md`
One `##` heading per institution:
```markdown
## <Institution Name>
**<Degree>**
<Start Month YYYY> – <End Month YYYY> | <City>

- <thesis or coursework note>
```

---

## Step 8 — Validation report

After writing all files, print a structured summary:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 EXTRACTION REPORT
Source: <filename>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏭 Sector: <inferred_sector> — <inferred_functional_area>
✅ heading.md       — name, email, phone, linkedin, github
✅ summary.md       — X paragraphs
✅ core_competencies.md — X items
✅ experience.md    — X roles, X projects
✅ skills.md        — X categories
✅ education.md     — X degrees
⚠️  <section>.md   — could not identify section; file written empty

🔍 Things to verify manually:
  • Dates — check for any that parsed incorrectly
  • Bold emphasis — markitdown may not preserve all formatting
  • Multi-column layouts — content may have merged across columns
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Next steps:
  • Review and edit <out>/*.md if anything looks wrong
  • To verify it compiles (replace <out> with your output dir):
      docker run --rm -v $(pwd):/cv curriculum \
        bash -c "python3 curriculum-py/template_builder.py --content-dir <out> && cd tex && texliveonfly main.tex"
    or with podman, or locally: python curriculum-py/template_builder.py --content-dir <out> && cd tex && pdflatex main.tex
  • If satisfied, copy files to content/ and rebuild
  • Run /custom-cv <url> to tailor this CV for a specific role
  • Run /cv-audit <url> to score it against a job posting as-is
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Guardrails

- **Never fabricate content**: if a section cannot be parsed, write it empty with a comment — do not invent bullets
- **Preserve factual accuracy**: do not rephrase or improve extracted content; write it exactly as parsed
- **Multi-column caveat**: if the PDF used a multi-column layout, markitdown often merges columns left-to-right; flag this in the report so the user can check the experience section manually
- **No LaTeX written**: this skill only writes `.md` files; the LaTeX templates are untouched
