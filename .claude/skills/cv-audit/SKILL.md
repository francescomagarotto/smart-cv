---
name: cv-audit
description: Audits how well the current branch's CV matches a job posting. Scrapes the JD, reads the CV as-is, and produces a scored ATS keyword report with gap analysis — no edits made.
---

# CV Audit

The user invokes this as `/cv-audit <job-url>`.

This skill is **read-only**: it never modifies files, creates branches, or commits. It answers the question: "how well does my current CV match this role?"

---

## Step 1 — Scrape the job description

Follow the same scraping logic as the `custom-cv` skill (steps 1a–1c):

### 1a — Ensure Scrapy is available

```bash
curriculum-py/.venv/bin/python -c "import scrapy; print(scrapy.__version__)" 2>/dev/null \
  || (python3 -m venv curriculum-py/.venv && curriculum-py/.venv/bin/pip install -r curriculum-py/requirements.txt -q)
```

For JS-heavy boards (Workday, LinkedIn), check `scrapy-playwright`. Warn but proceed with raw HTML if unavailable.

**Ashby boards** (`jobs.ashbyhq.com`): use the public JSON API instead of the spider:
```bash
curl -s "https://api.ashbyhq.com/posting-api/job-board/<company-slug>" \
  | python3 -c "
import json, sys
jobs = json.load(sys.stdin).get('jobs', [])
match = next((j for j in jobs if j['id'] == '<job-id>'), None)
print(json.dumps(match) if match else 'NOT_FOUND')
"
```
Use `descriptionPlain` as the content. Skip the spider for Ashby URLs.

### 1b — Run the spider

```bash
curriculum-py/.venv/bin/python curriculum-py/job_spider.py "<url>" 2>/dev/null
```

If `content` is shorter than 300 characters, try without `2>/dev/null` and report the error. Offer to proceed with a manually pasted JD.

### 1c — Extract and structure

From the scraped content extract:
- **Company name** and **job title**
- **Must-have requirements**
- **Nice-to-have requirements**
- **Tech stack** (tools, languages, frameworks, platforms)
- **Domain keywords** ("observability", "data mesh", "real-time", etc.)
- **ATS keyword targets**: deduplicated flat list of every noun/phrase the ATS will likely scan for

Print a brief summary:
```
🔍 Job: <Title> @ <Company>
🌐 Scraped via: scrapy | scrapy-playwright | ashby-api
📋 Key requirements: <bullet list>
🛠  Tech stack: <comma list>
🎯 ATS keywords detected: <count>
```

---

## Step 2 — Read the current CV

Read all source files **from the current branch** without modifying them:
- `content/summary.md`
- `content/core_competencies.md`
- `content/experience.md`
- `content/skills.md`

Note which branch is currently checked out — the audit is relative to that branch's state.

---

## Step 3 — ATS keyword audit

### 3a — Keyword coverage

For each ATS keyword target, check whether it appears in the CV text.

Output a table:

| Keyword | Present? | Location |
|---------|----------|----------|
| Apache Kafka | ✅ | skills.tex, experience |
| dbt | ❌ | not present |

Calculate a **coverage score**: `(keywords present / total ATS keywords) × 100`

### 3b — Structural ATS checks

Verify:
- [ ] `\pdfgentounicode=1` is set in `templates/default/main.tex`
- [ ] No images or graphics
- [ ] All URLs use `\href` with readable link text
- [ ] Section headings use plain text (no unicode symbols or emojis)
- [ ] Date formats are consistent (Month YYYY throughout)
- [ ] No headers/footers with critical content (fancyhdr empty — confirm)
- [ ] Font embedded via `[default]{lato}`

Then attempt a compile to verify the PDF builds cleanly:

```bash
CONTAINER_RUNTIME=$(command -v docker 2>/dev/null || command -v podman 2>/dev/null)
if [ -n "$CONTAINER_RUNTIME" ]; then
  python curriculum-py/template_builder.py \
  && $CONTAINER_RUNTIME run --rm -v "$(pwd)":/cv curriculum \
       bash -c "cd /cv/tex && texliveonfly main.tex" 2>&1 | tail -5
else
  python curriculum-py/template_builder.py && cd tex && pdflatex -interaction=nonstopmode main.tex 2>&1 | tail -5
fi
```

Add `✅ PDF compiles cleanly` or `⚠️ Compile failed: <error>` to the structural checks list.

### 3c — Gap analysis

For missing keywords, classify each as:
- **Fillable** — the owner has the experience but the CV doesn't use that exact language; suggest where to add it
- **Stretchable** — adjacent experience exists; flag it so the user can decide if it's honest to claim
- **Genuine gap** — owner has no matching experience; note it plainly, suggest a personal project if relevant

### 3d — Score summary

Print:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 ATS AUDIT REPORT
Branch: <current-branch>
Role:   <Title> @ <Company>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Keyword coverage : XX/YY (ZZ%)
Structural checks: ✅ all passed / ⚠️ N issues

✅ Strong matches:
  • <keyword> — found in <location>
  • ...

🟡 Fillable gaps (language only):
  • <keyword> — you have <related experience>, add to <file>

🔴 Genuine gaps:
  • <keyword> — not present in background

⚠️ Structural issues:
  • <specific issue if any>

💡 Next step: run /custom-cv <url> to tailor the CV for this role
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Guardrails

- **Read-only**: never write, edit, or stage any file
- **No branch switching**: audit always runs against the current checked-out branch
- **Honest gaps**: do not suggest adding keywords the owner cannot genuinely claim
