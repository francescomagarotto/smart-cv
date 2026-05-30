---
name: custom-cv
description: Tailors the owner's LaTeX CV to a specific job description. Takes a URL, scrapes the job posting, creates a new git branch, rewrites CV sections to match the role, and runs an ATS compatibility audit.
---

# Custom CV Generator

The user provides a **job posting URL** (and optionally a company/role slug for the branch name). This skill:

1. Fetches and parses the job description from the URL
2. Creates a dedicated git branch for this application
3. Rewrites the CV LaTeX sections to match the role
4. Runs an ATS compatibility audit with a scored report

---

## Step 0 — Parse arguments

The user invokes this as `/custom-cv <url> [company-role-slug]`.

- `url` (required): the full job posting URL
- `company-role-slug` (optional): used as the branch suffix, e.g. `stripe-data-engineer`. If omitted, infer it from the company name and job title extracted from the page.

---

## Step 1 — Scrape the job description

### 1a — Ensure Scrapy is installed

The project uses a virtualenv at `curriculum-py/.venv/`. Check it exists and has Scrapy:

```bash
curriculum-py/.venv/bin/python -c "import scrapy; print(scrapy.__version__)" 2>/dev/null \
  || (python3 -m venv curriculum-py/.venv && curriculum-py/.venv/bin/pip install -r curriculum-py/requirements.txt -q)
```

If the venv creation fails, tell the user to run from the repo root:
```
python3 -m venv curriculum-py/.venv && curriculum-py/.venv/bin/pip install scrapy
```
Then abort.

For JS-heavy boards (Workday, LinkedIn), check whether `scrapy-playwright` is available:

```bash
curriculum-py/.venv/bin/python -c "import scrapy_playwright" 2>/dev/null \
  && echo "playwright available" || echo "playwright not installed"
```

If it's not installed and the URL is a Workday or LinkedIn URL, warn the user:
> ⚠️ This board renders via JavaScript. For full extraction run:
> `curriculum-py/.venv/bin/pip install scrapy-playwright && curriculum-py/.venv/bin/playwright install chromium`
> Proceeding with raw HTML — content may be incomplete.

**Ashby boards**: `jobs.ashbyhq.com` URLs render via JavaScript but expose a public JSON API. If the URL matches `jobs.ashbyhq.com/<company>/<job-id>`, extract the company slug and job ID, then fetch:
```bash
curl -s "https://api.ashbyhq.com/posting-api/job-board/<company-slug>" \
  | python3 -c "
import json, sys
jobs = json.load(sys.stdin).get('jobs', [])
match = next((j for j in jobs if j['id'] == '<job-id>'), None)
print(json.dumps(match) if match else 'NOT_FOUND')
"
```
Use `descriptionPlain` as the content field. Skip the spider entirely for Ashby URLs.

### 1b — Run the spider

```bash
curriculum-py/.venv/bin/python curriculum-py/job_spider.py "<url>" 2>/dev/null
```

The spider outputs a single JSON line to stdout:
```json
{
  "url": "...",
  "title": "Senior Data Engineer",
  "company": "Stripe",
  "content": "... full plain-text job description ...",
  "engine": "scrapy"
}
```

Capture this output and parse it. If `content` is shorter than 300 characters or empty:
- Try running without `2>/dev/null` to see Scrapy logs and diagnose
- Inform the user the page may require JS rendering or authentication
- Ask whether to proceed with a manually pasted JD or abort

### 1c — Extract and structure

From the scraped `content`, extract:
- **Company name** and **job title** (use spider's `company`/`title` fields, fall back to parsing the content)
- **Team / department** (if mentioned)
- **Role summary** (what the role is about, in 2–4 sentences)
- **Must-have requirements** (hard requirements, years of experience, certifications)
- **Nice-to-have requirements**
- **Tech stack** (explicit tools, languages, frameworks, platforms mentioned)
- **Domain keywords** (domain-specific language: "observability", "data mesh", "real-time", "ML platform", etc.)
- **Soft skills / culture signals** (collaboration style, scale, methodologies)
- **ATS keyword targets**: a deduplicated flat list of every noun/phrase the ATS will likely scan for — titles, tools, methodologies, certifications, and high-signal verbs like "design", "architect", "lead", "build"

Print a brief summary to the user:
```
🔍 Job: <Title> @ <Company>
🌐 Scraped via: scrapy | scrapy-playwright
📋 Key requirements: <bullet list>
🛠 Tech stack: <comma list>
🎯 ATS keywords detected: <count>
```

### 1d — Identify the sector

From the structured JD, classify the role along two dimensions:

**Industry sector** — the broad domain the employer operates in. Examples:
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

**Functional area** — the specific discipline of the role. Examples:
- Data Engineering / Analytics Engineering
- Platform / Infrastructure Engineering
- Machine Learning / AI
- Software / Backend Engineering
- DevOps / Site Reliability
- Product Management
- Cybersecurity
- Business Analysis / BI

Output:
```
🏭 Sector: <Industry sector> — <Functional area>
```

Use the sector to guide tailoring in Step 4:
- **Regulated sectors** (Finance, Healthcare, Government): emphasise compliance, auditability, data governance, and security keywords even if not explicitly listed in the JD — ATS systems in these industries weight them heavily.
- **Startup / scale-up tech**: lead with velocity, ownership, and full-stack breadth.
- **Enterprise tech**: emphasise scale, reliability, incident management, and cross-team collaboration.
- **Domain-specific language**: mirror the sector's vocabulary (e.g., "claims data" for Healthcare, "tick data" for Finance, "telemetry" for SaaS).

---

## Step 2 — Create a git branch

Be sure you're on the `main` branch and have no uncommitted changes before creating a new branch.
Run:
```bash
git checkout main
git pull origin main
git checkout -b cv/<company-slug>-<role-slug>
```

Where `company-slug` and `role-slug` are lowercase, hyphenated, ASCII-only versions of the company name and job title.

If the branch already exists, check it out with `git checkout cv/...` and note that changes will be amended.

---

## Step 3 — Read the current CV

Read all source files:
- `content/summary.md`
- `content/core_competencies.md`
- `content/experience.md`
- `content/skills.md`
- `content/heading.md`
- `content/education.md`

Do NOT modify `content/heading.md` or `content/education.md` unless explicitly asked — personal details and structure are stable.

---

## Step 4 — Tailor the CV sections

Apply targeted, honest edits. **Never fabricate experience, tools, or credentials.** Only reorder, reframe, emphasize, or add/remove existing content.

### 4a — Summary (`content/summary.md`)

Rewrite the summary (3–5 sentences) to:
- Mirror the job title or role framing used in the JD (e.g., "Data Platform Engineer" if that's the JD's term)
- Echo 2–3 ATS keywords from the JD naturally
- Emphasize the most relevant aspect of the owner's background (read from the CV files)
- Keep it factual and quantification-consistent with the rest of the CV
- Do not use the dash character (—); switch to commas or semicolons if needed for ATS compatibility

### 4b — Core Competencies (`content/core_competencies.md`)

Rewrite the competency section to:
- Lead with the 4–5 most JD-relevant competencies
- Include exact phrasing from the JD where it matches real skills (e.g., if JD says "Stream Processing" and we have Flink, use that term)
- Keep total count under 12 items to avoid clutter
- Use a two/three column layout and bullet points, but ensure it remains ATS-friendly (no complex tables)
- Do not use the dash character (—); switch to commas or semicolons if needed for ATS compatibility

### 4c — Skills (`content/skills.md`)

- Reorder skill categories so the most relevant ones appear first
- Highlight tools mentioned in the JD that are already in the CV (no additions of tools the owner hasn't used)
- If the JD mentions a tool in a category and it's absent from that category but the owner has it, move it to the right category
- Do not add tools the owner hasn't used

### 4d — Experience (`content/experience.md`)

**If `experience.md` is empty or absent** (student, career-starter, career-changer):
- Do not fabricate roles. Instead, check whether any of the following substitute sections exist in other content files and can be surfaced here: academic projects, internships, volunteer work, freelance work, open-source contributions, or extracurricular leadership.
- If substitutes exist, reframe them using role-adjacent language from the JD (e.g., a university project becomes a bullet that uses the JD's terminology for the relevant skill). Label them honestly ("Academic Project", "Internship", "Volunteer").
- If no substitutes exist, leave the section empty and note in the ATS report that the keyword gap cannot be filled without fabricating. Recommend the user adds a personal or open-source project as a concrete next step.

**If `experience.md` has content**, for each `\resumeItem` bullet:
- Reorder bullets within each role to put the most JD-relevant ones first
- If a bullet is factually accurate but could use a keyword swap (e.g., "data pipelines" → "ETL/ELT pipelines" if the JD uses "ETL/ELT"), apply it
- If the JD emphasizes something (e.g., "data quality", "observability", "cost optimization") and there are existing bullets that cover it but don't use that language, lightly rephrase to match
- Do not use the dash character (—); switch to commas or semicolons if needed for ATS compatibility
- **Do not fabricate metrics, tools, or responsibilities**

If the role is dramatically different from the owner's current framing (e.g., a pure ML role vs. data engineering), note which experience sections are least relevant and explain what cannot be tailored without fabricating.

---

## Step 5 — ATS compatibility audit

After making changes, perform a structured ATS audit:

### 5a — Keyword coverage

For each ATS keyword target from Step 1, check whether it appears somewhere in the final CV text.

Output a table:

| Keyword | Present? | Location |
|---------|----------|----------|
| Apache Kafka | ✅ | skills.tex, experience |
| dbt | ❌ | not present |
| ... | | |

Calculate a **coverage score**: `(keywords present / total ATS keywords) × 100`

### 5b — Structural ATS checks

Verify:
- [ ] No multi-column layout (LaTeX `tabular` is only used for heading — this is fine)
- [ ] `\pdfgentounicode=1` is set in `main.tex` (already present — confirm)
- [ ] No images or graphics (LaTeX-based CVs in this repo have none — confirm)
- [ ] All URLs use `\href` with readable link text (not raw URLs)
- [ ] Section headings use plain text (no unicode symbols, emojis, or decorative characters)
- [ ] Date formats are consistent (Month YYYY throughout)
- [ ] No headers/footers with critical content (fancyhdr is set to empty — confirm)
- [ ] Font is embedded (Lato via `[default]{lato}` — confirm)

### 5c — ATS score summary

Print:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 ATS COMPATIBILITY REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Keyword coverage : XX/YY (ZZ%)
Structural checks: ✅ all passed / ⚠️ N issues

🔑 Top missing keywords:
  • <keyword 1> — consider adding if you have genuine experience
  • <keyword 2>
  • ...

✅ Strong matches:
  • <keyword> — found in <location>
  • ...

⚠️ Suggestions:
  • <specific improvement without fabricating>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Step 6 — Compile and commit

### 6a — Detect container runtime

Check whether Docker or Podman is available:
```bash
CONTAINER_RUNTIME=$(command -v docker 2>/dev/null || command -v podman 2>/dev/null)
```

### 6b — Try to compile

If a container runtime is available, compile inside the `curriculum` image (installs missing LaTeX packages automatically via `texliveonfly`):
```bash
$CONTAINER_RUNTIME run --rm -v "$(pwd)":/cv curriculum \
  bash -c "cd /cv/tex && texliveonfly main.tex" 2>&1 | tail -20
```

If no runtime is available, fall back to local pdflatex:
```bash
cd tex && pdflatex -interaction=nonstopmode main.tex 2>&1 | tail -20
```

If compilation fails either way, show the error and fix any LaTeX syntax issues before committing.

### 6b.1 — Rename the PDF
If the PDF is generated successfully, rename it for easy reference. The PDF is at `tex/main.pdf`.
`<username>` can be inferred from `content/heading.md`; ask the user if not available.
```bash
mv tex/main.pdf <username>-<company-slug>-<role-slug>-cv.pdf
```



### 6b — Commit

```bash
git add content/summary.md content/core_competencies.md content/experience.md content/skills.md
git commit -m "cv: tailor for <Title> @ <Company>

- Rewritten summary to align with <role focus>
- Core competencies reordered to lead with <top skills>
- Skills section prioritised: <top categories>
- Experience bullets reordered/reframed for <key JD themes>
- ATS keyword coverage: XX%

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

## Step 7 — Cover letter

Ask the user if they want to generate a tailored cover letter using the same JD insights. If yes, create `cover_letters/<company-slug>-<role-slug>.tex`. Create the `cover_letters/` directory if it does not exist.

### 7a — Cover letter content

Use this LaTeX preamble so the cover letter matches the CV's font and margins:

```latex
\documentclass[letterpaper,11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[default]{lato}
\usepackage[empty]{fullpage}
\usepackage[hidelinks]{hyperref}
\usepackage[english]{babel}
\addtolength{\oddsidemargin}{-0.5in}
\addtolength{\evensidemargin}{-0.5in}
\addtolength{\textwidth}{1in}
\addtolength{\topmargin}{-.5in}
\addtolength{\textheight}{1.0in}
\pdfgentounicode=1
\begin{document}
% content here
\end{document}
```

Structure the body as:
- **Introduction**: 1–2 sentences on why this company and role are compelling, referencing specific JD themes or company values
- **Body**: 2–3 paragraphs expanding on the most relevant experience, with concrete examples aligned to the JD's focus areas
- **Conclusion**: polite closing that reiterates interest and invites further discussion

Do not use em-dashes (—) anywhere in the cover letter text.

### 7b — ATS audit for cover letter

Run the same keyword check used in step 5a on the cover letter content, ensuring relevant keywords appear without overstuffing.

### 7c — Compile and commit the cover letter

If a container runtime is available:
```bash
$CONTAINER_RUNTIME run --rm -v "$(pwd)":/cv curriculum \
  bash -c "cd /cv && texliveonfly cover_letters/<company-slug>-<role-slug>.tex" 2>&1 | tail -10
```

Otherwise fall back to:
```bash
pdflatex -interaction=nonstopmode cover_letters/<company-slug>-<role-slug>.tex 2>&1 | tail -10
```

Fix any LaTeX errors before committing. Then:

```bash
git add cover_letters/<company-slug>-<role-slug>.tex
git commit -m "cv: add tailored cover letter for <Title> @ <Company>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
---

## Guardrails

- **Honesty first**: if a keyword gap cannot be filled without fabricating, say so explicitly and suggest what to do (e.g., add a brief personal project)
- **Minimal diff**: prefer surgical edits over full rewrites to preserve authenticity
- **Preserve structure**: always maintain valid LaTeX; do not break `\resumeItem`, `\resumeSubheading`, or other custom commands defined in `custom-commands.tex`
- **Branch isolation**: all changes live on the feature branch — `main` is never touched
- **Ask before drastic changes**: if tailoring would require removing more than 2 bullet points from any role, confirm with the user first
