#!/usr/bin/env python3
"""
Job description scraper.

Uses requests + parsel (Scrapy's selector library) for static pages.
For JS-heavy boards (Workday, LinkedIn) it optionally falls back to
playwright-fetch when playwright is installed.

Usage:
    curriculum-py/.venv/bin/python curriculum-py/job_spider.py <url>

Prints a single JSON line to stdout:
    {
      "url": "...",
      "title": "...",
      "company": "...",
      "content": "...",
      "engine": "requests" | "playwright"
    }

Supported boards (static, no JS needed):
    Greenhouse, Lever, Ashby, SmartRecruiters, Indeed, BambooHR, Jobvite

JS-heavy boards (need: pip install playwright && playwright install chromium):
    Workday, LinkedIn
"""
from __future__ import annotations

import json
import logging
import re
import sys
from typing import Protocol, runtime_checkable
from typing import TypedDict
from urllib.parse import urlparse

import requests
from parsel import Selector

log = logging.getLogger(__name__)


class ScrapeResult(TypedDict):
    url: str
    title: str
    company: str
    content: str
    engine: str


@runtime_checkable
class Scraper(Protocol):
    def scrape(self, url: str) -> ScrapeResult:
        ...


class JobScraper:
    BOARD_SELECTORS: dict[str, list[str]] = {
        "greenhouse.io": ["#app_body", "#content", ".app-body"],
        "lever.co": [".posting-content", ".content"],
        "ashbyhq.com": [
            "[data-testid='job-description']",
            ".ashby-job-posting-brief-description",
            "main section",
            "main",
        ],
        "smartrecruiters.com": [".job-description", "[class*='jobad-body']"],
        "indeed.com": ["#jobDescriptionText", ".jobsearch-jobDescriptionText"],
        "bamboohr.com": ["#BambooHR-ATS", ".BambooHR-ATS"],
        "jobvite.com": [".jv-job-detail-description", "#jobvite-job"],
        "workday.com": [
            "[data-automation-id='jobPostingDescription']",
            "[data-automation-id='job-posting-details']",
        ],
        "linkedin.com": [
            ".description__text",
            ".show-more-less-html__markup",
            "[class*='description']",
        ],
        "careers.anthropic.com": ["main", "article", "[class*='description']"],
        "stripe.com": [".job-details", "main article", "main"],
    }

    FALLBACK_SELECTORS: list[str] = [
        "main article",
        "article",
        "main",
        "#job-description",
        "#jobDescription",
        ".job-description",
        "[class*='job-description']",
        "[class*='jobDescription']",
        "[class*='posting-description']",
        "[class*='description-body']",
        "[id*='description']",
        "section.content",
        ".content",
    ]

    JS_HEAVY_BOARDS: set[str] = {"workday.com", "linkedin.com"}

    MIN_LEN: int = 300

    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def scrape(self, url: str) -> ScrapeResult:
        """Fetch and parse a job posting.

        Selects the fetch engine automatically: Playwright for JS-heavy boards
        (Workday, LinkedIn) when available, requests otherwise. CSS selectors
        are chosen per job board with a generic fallback chain.

        Args:
            url: Public URL of the job posting.

        Returns:
            ScrapeResult with url, title, company, content, and engine fields.
            content may be shorter than MIN_LEN if the page required JS or auth;
            a warning is logged in that case.

        Raises:
            requests.HTTPError: if the HTTP response status is 4xx/5xx.
        """
        html, engine = self._fetch(url)
        sel = Selector(text=html)
        content = self._extract_text(sel, self._board_selectors(url))
        title = (sel.css("h1::text").get("") or sel.css("title::text").get("")).strip()
        company = self._infer_company(sel.css("title::text").get("").strip())

        if len(content) < self.MIN_LEN:
            log.warning("Only %d chars extracted — page may require JS rendering or auth.", len(content))

        return {"url": url, "title": title, "company": company, "content": content, "engine": engine}

    def _fetch(self, url: str) -> tuple[str, str]:
        if self._needs_playwright(url):
            if self._has_playwright():
                return self._fetch_playwright(url)
            log.warning(
                "%s renders via JavaScript. For full extraction install playwright:\n"
                "  curriculum-py/.venv/bin/pip install playwright\n"
                "  curriculum-py/.venv/bin/playwright install chromium\n"
                "Falling back to raw HTML (content may be incomplete).",
                urlparse(url).netloc,
            )
        return self._fetch_requests(url)

    def _fetch_requests(self, url: str) -> tuple[str, str]:
        resp = requests.get(url, headers=self.HEADERS, timeout=20, allow_redirects=True)
        resp.raise_for_status()
        return resp.text, "requests"

    def _fetch_playwright(self, url: str) -> tuple[str, str]:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=self.HEADERS["User-Agent"])
            page.goto(url, wait_until="networkidle", timeout=30_000)
            html = page.content()
            browser.close()
        return html, "playwright"

    def _board_selectors(self, url: str) -> list[str]:
        domain = urlparse(url).netloc.lower()
        for board, sels in self.BOARD_SELECTORS.items():
            if board in domain:
                return sels + self.FALLBACK_SELECTORS
        return self.FALLBACK_SELECTORS

    def _extract_text(self, sel: Selector, selectors: list[str]) -> str:
        for css in selectors:
            nodes = sel.css(css)
            if not nodes:
                continue
            text = self._clean(" ".join(nodes.css("*::text").getall()))
            if len(text) >= self.MIN_LEN:
                return text
        return ""

    def _infer_company(self, title_tag: str) -> str:
        for sep in [" at ", " @ ", " - ", " | ", " — "]:
            if sep in title_tag:
                rest = title_tag.split(sep, 1)[1]
                return rest.split(" | ")[0].split(" - ")[0].strip()
        return ""

    def _needs_playwright(self, url: str) -> bool:
        domain = urlparse(url).netloc.lower()
        return any(board in domain for board in self.JS_HEAVY_BOARDS)

    @staticmethod
    def _has_playwright() -> bool:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _clean(text: str) -> str:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def main(scraper: Scraper | None = None) -> None:
    logging.basicConfig(format="%(levelname)s %(message)s", level=logging.INFO)
    if len(sys.argv) < 2:
        log.error("Usage: curriculum-py/.venv/bin/python curriculum-py/job_spider.py <url>")
        sys.exit(1)

    result = (scraper or JobScraper()).scrape(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
