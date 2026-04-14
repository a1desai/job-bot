#!/usr/bin/env python3
"""
Simplify.jobs → Telegram Job Alert Bot
Monitors Simplify for Fall 2026 AI/ML + SWE internships every 60 seconds.
Sends a Telegram message the moment a new listing appears.

Setup:
  export TELEGRAM_TOKEN='your_bot_token'
  export TELEGRAM_CHAT_ID='your_chat_id'
  ./venv/bin/python3 bot.py
"""

import asyncio
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Simplify URL — Internship, Software Engineering + Data & Analytics categories
# Season filter (Fall 2026) is applied client-side since the UI filter isn't URL-driven
SIMPLIFY_URL = (
    "https://simplify.jobs/jobs"
    "?jobType=Internship"
    "&category=Software%20Engineering%3BData%20%26%20Analytics"
)

# Only alert on these seasons (case-insensitive substring match against card text)
TARGET_SEASONS = ["fall 2026"]

# Only alert if card text contains at least one of these keywords
# (matches title or company name)
KEYWORD_FILTER = [
    # SWE roles
    "software engineer", "software developer", "swe", "full stack", "fullstack",
    "backend", "frontend", "front-end", "back-end", "web developer",
    # AI/ML roles
    "machine learning", "ml engineer", "ai engineer", "artificial intelligence",
    "deep learning", "data scientist", "data engineer", "nlp", "computer vision",
    "research engineer", "applied scientist",
    # General internship catch-all (remove if too noisy)
    "engineer intern", "engineering intern",
]

POLL_INTERVAL = 60   # seconds between checks
SEEN_FILE     = Path(__file__).parent / "seen_jobs.json"
# ─────────────────────────────────────────────────────────────────────────────


def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(sorted(seen)))


def send_telegram(text: str):
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id":                  TELEGRAM_CHAT_ID,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": False,
    }).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"[Telegram error] {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"[Telegram error] {e}")


def job_key(company: str, title: str) -> str:
    """Stable unique key for a job posting."""
    return re.sub(r"\s+", " ", f"{company}|{title}").lower().strip()


def matches_keywords(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in KEYWORD_FILTER)


def matches_season(text: str) -> bool:
    t = text.lower()
    # "internship" with no season label = always show (some postings don't specify)
    if not any(s in t for s in ["summer", "fall", "spring", "winter"]):
        return True
    return any(s in t for s in TARGET_SEASONS)


def format_message(company: str, title: str, lines: list[str]) -> str:
    # lines = [company, title, season?, salary?, location?, work_type?]
    season   = next((l for l in lines if any(s in l.lower() for s in ["2026", "2027", "internship"])), "")
    salary   = next((l for l in lines if "$" in l), "")
    location = next((l for l in lines if any(c in l for c in [", ", " USA", " Canada", " Remote"])), "")

    search_q = urllib.parse.quote_plus(f"{company} {title}")
    search_url = f"https://simplify.jobs/jobs?search={search_q}&jobType=Internship"

    parts = [f"🔔 <b>New Fall 2026 Internship!</b>\n"]
    parts.append(f"<b>{title}</b>")
    parts.append(f"🏢 {company}")
    if season:   parts.append(f"🗓 {season}")
    if salary:   parts.append(f"💰 {salary}")
    if location: parts.append(f"📍 {location}")
    parts.append(f"\n<a href=\"{search_url}\">View on Simplify →</a>")
    return "\n".join(parts)


# need urllib.parse for the URL encoding above
import urllib.parse


async def scrape_jobs(browser) -> list[dict]:
    """Open Simplify, return list of {company, title, lines} dicts."""
    page = await browser.new_page()
    await page.set_extra_http_headers({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    })

    try:
        await page.goto(SIMPLIFY_URL, wait_until="domcontentloaded", timeout=30000)
        # Wait for job cards to render
        await page.wait_for_selector('[data-testid="job-card"]', timeout=15000)
        await asyncio.sleep(2)  # let the full list settle
    except Exception as e:
        print(f"  [page load error] {e}")
        await page.close()
        return []

    # Extract all visible job cards
    raw_jobs = await page.evaluate('''() => {
        const cards = document.querySelectorAll('[data-testid="job-card"]');
        const jobs = [];
        for (const card of cards) {
            const lines = card.innerText
                .split("\\n")
                .map(l => l.trim())
                .filter(Boolean);
            if (lines.length >= 2) {
                jobs.push(lines);
            }
        }
        return jobs;
    }''')

    await page.close()

    jobs = []
    for lines in raw_jobs:
        company = lines[0] if lines else ""
        title   = lines[1] if len(lines) > 1 else ""
        card_text = " ".join(lines)

        if not company or not title:
            continue

        jobs.append({"company": company, "title": title, "lines": lines, "text": card_text})

    return jobs


async def check_once(browser, seen: set) -> tuple[set, int]:
    jobs = await scrape_jobs(browser)
    if not jobs:
        return seen, 0

    new_count = 0
    for job in jobs:
        key = job_key(job["company"], job["title"])

        if key in seen:
            continue

        seen.add(key)

        # Apply filters
        if not matches_season(job["text"]):
            continue
        if not matches_keywords(job["text"]):
            continue

        # New match — send alert
        msg = format_message(job["company"], job["title"], job["lines"])
        print(f"  [ALERT] {job['company']} — {job['title']}")
        send_telegram(msg)
        new_count += 1

    return seen, new_count


async def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID before running.")
        print("  export TELEGRAM_TOKEN='7483920:AAHxyz...'")
        print("  export TELEGRAM_CHAT_ID='123456789'")
        return

    print("=" * 60)
    print("  Simplify.jobs → Telegram Bot")
    print(f"  Target: Fall 2026 SWE / AI / ML Internships")
    print(f"  Polling every {POLL_INTERVAL}s")
    print("=" * 60)

    send_telegram(
        "✅ <b>Job Alert Bot is running!</b>\n"
        "Watching Simplify.jobs for <b>Fall 2026 SWE / AI / ML internships</b>.\n"
        "I'll ping you the moment something new appears 🔔"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        seen = load_seen()

        # First run: seed existing jobs so we only alert on genuinely NEW ones
        if not seen:
            print("\nFirst run — seeding current listings (no alerts yet)...")
            jobs = await scrape_jobs(browser)
            for job in jobs:
                seen.add(job_key(job["company"], job["title"]))
            save_seen(seen)
            print(f"Seeded {len(seen)} existing jobs. Future new postings will trigger alerts.\n")

        while True:
            ts = datetime.now().strftime("%H:%M:%S")
            seen, n = await check_once(browser, seen)
            save_seen(seen)
            print(f"[{ts}] Checked Simplify — {n} new alert(s). Total tracked: {len(seen)}")
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
