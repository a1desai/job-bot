#!/usr/bin/env python3
"""
Simplify.jobs → Telegram Job Alert Bot
Monitors Simplify for Fall/Summer 2026 AI/ML + SWE internships every 60 seconds.
Fetches full job details and matches against Aryan's resume.
"""

import asyncio
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

SIMPLIFY_URL = (
    "https://simplify.jobs/jobs"
    "?jobType=Internship"
    "&category=Software%20Engineering%3BData%20%26%20Analytics"
)

TARGET_SEASONS = ["fall 2026", "summer 2026"]

KEYWORD_FILTER = [
    "software engineer", "software developer", "swe", "full stack", "fullstack",
    "backend", "frontend", "front-end", "back-end", "web developer",
    "machine learning", "ml engineer", "ai engineer", "artificial intelligence",
    "deep learning", "data scientist", "data engineer", "nlp", "computer vision",
    "research engineer", "applied scientist",
    "engineer intern", "engineering intern",
]

POLL_INTERVAL = 60
SEEN_FILE     = Path(__file__).parent / "seen_jobs.json"

# ── ARYAN'S RESUME SKILLS ────────────────────────────────────────────────────
# Used for match scoring against job requirements
RESUME_SKILLS = {
    # Languages
    "javascript", "typescript", "python", "java", "c++", "c/c++",
    # AI/ML
    "pytorch", "reinforcement learning", "rag", "langchain", "langgraph",
    "machine learning", "nlp", "transformers", "llm", "large language model",
    "gcp", "vertex ai", "gcp vertex ai",
    # Frameworks & Tools
    "react", "next.js", "nextjs", "node.js", "nodejs", "express", "express.js",
    "postgresql", "postgres", "rest", "restful api", "tailwind", "tailwind css",
    "jwt", "supabase", "git", "docker", "firebase", "aws", "aws s3",
    "jest", "ci/cd", "github actions",
    # Concepts
    "full stack", "fullstack", "backend", "frontend", "api", "web development",
    "reinforcement learning", "rl", "deep learning", "computer vision",
    "rag pipeline", "embeddings", "vector database", "pgvector",
}

RESUME_EXPERIENCE = """
- AI Project Lead at Computing Councils of Canada: LangGraph, Docker, cybersecurity AI agents
- Software Engineer at FlipPilot: TypeScript, Playwright, GPT-4, PostgreSQL, HTML parsing
- Technology Director at Google Developer Groups: React, TypeScript, workshops
- Projects: EchoBase (React, Node.js, Supabase, LLM), BeaverBuddy (Next.js, PostgreSQL, OpenAI),
  AI Racer (PyTorch, RL, GDScript), SentinAI (transformers, RAG, NLP)
- Education: TMU Computer Science Co-op (2024–2029)
"""
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
    return re.sub(r"\s+", " ", f"{company}|{title}").lower().strip()


def matches_keywords(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in KEYWORD_FILTER)


def matches_season(text: str) -> bool:
    t = text.lower()
    if not any(s in t for s in ["summer", "fall", "spring", "winter"]):
        return True
    return any(s in t for s in TARGET_SEASONS)


def fetch_job_details(job_id: str) -> dict:
    """Fetch full job details from Simplify API."""
    url = f"https://api.simplify.jobs/v2/job-posting/:id/{job_id}/company"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Origin": "https://simplify.jobs",
        "Referer": "https://simplify.jobs/",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [detail fetch error] {e}")
        return {}


def score_match(details: dict) -> tuple[str, str, list[str]]:
    """
    Returns (match_label, match_emoji, matched_skills).
    Compares job requirements/skills against resume.
    """
    # Collect all text from the job posting
    job_text = " ".join([
        details.get("title", ""),
        details.get("description", ""),
        details.get("requirements", ""),
        details.get("responsibilities", ""),
        " ".join(s.get("name", "") for s in details.get("skills", [])),
    ]).lower()

    # Find which resume skills appear in the job text
    matched = [skill for skill in RESUME_SKILLS if skill in job_text]
    matched_display = [s.title() for s in sorted(set(matched))]

    # Score based on match count relative to job's skill demands
    total_skills_in_job = len(re.findall(
        r'\b(?:python|javascript|typescript|react|node|java|c\+\+|sql|aws|docker|'
        r'pytorch|tensorflow|machine learning|nlp|api|git|ci/cd|kubernetes)\b',
        job_text
    ))
    total_skills_in_job = max(total_skills_in_job, 1)

    score = len(matched) / min(total_skills_in_job, 10)

    if score >= 0.7 or len(matched) >= 6:
        return "Perfect Match", "🟢", matched_display
    elif score >= 0.4 or len(matched) >= 3:
        return "Strong Match", "🟡", matched_display
    elif len(matched) >= 1:
        return "Moderate Match", "🟠", matched_display
    else:
        return "Low Match", "🔴", matched_display


def format_message(company: str, title: str, lines: list[str], details: dict, job_id: str) -> str:
    season   = next((l for l in lines if any(s in l for s in ["2026", "2027", "Internship"])), "")
    salary   = next((l for l in lines if "$" in l), "")
    location = next((l for l in lines if "," in l or "Remote" in l), "")

    # Match scoring
    match_label, match_emoji, matched_skills = score_match(details)

    # Required skills from API
    api_skills = [s.get("name", "") for s in details.get("skills", [])][:8]
    skills_str = ", ".join(api_skills) if api_skills else "Not listed"

    # Job URL
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    job_url = f"https://simplify.jobs/p/{job_id}/{slug}" if job_id else \
              f"https://simplify.jobs/jobs?search={urllib.parse.quote_plus(f'{company} {title}')}&jobType=Internship"

    lines_out = []
    lines_out.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines_out.append(f"🔔  <b>NEW INTERNSHIP ALERT</b>")
    lines_out.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines_out.append(f"\n<b>{title}</b>")
    lines_out.append(f"<i>{company}</i>")
    lines_out.append("")
    if season:   lines_out.append(f"🗓  <b>Season</b>    <i>{season}</i>")
    if location: lines_out.append(f"📍  <b>Location</b>  <i>{location}</i>")
    if salary:   lines_out.append(f"💰  <b>Pay</b>       <i>{salary}</i>")
    lines_out.append("")
    lines_out.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
    lines_out.append(f"{match_emoji}  <b>Resume Match — {match_label}</b>")
    lines_out.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
    if matched_skills:
        lines_out.append(f"✅  <b>Your skills:</b>  <i>{', '.join(matched_skills[:6])}</i>")
    lines_out.append(f"🛠  <b>Required:</b>     <i>{skills_str}</i>")
    lines_out.append("")
    lines_out.append(f"🔗  <a href=\"{job_url}\"><b>View on Simplify →</b></a>")
    lines_out.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines_out)


async def scrape_jobs(browser) -> list[dict]:
    """Open Simplify, return list of job dicts."""
    page = await browser.new_page()
    await page.set_extra_http_headers({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    })

    try:
        await page.goto(SIMPLIFY_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector('[data-testid="job-card"]', timeout=15000)
        await asyncio.sleep(2)
    except Exception as e:
        print(f"  [page load error] {e}")
        await page.close()
        return []

    # Get job ID from the auto-selected first card (it's in the URL)
    first_job_id = ""
    url_match = re.search(r'jobId=([a-f0-9-]+)', page.url)
    if url_match:
        first_job_id = url_match.group(1)

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

    # For each new job card, click it to get its jobId from the URL
    job_buttons = await page.query_selector_all('[data-testid="job-card"]')

    jobs = []
    for i, lines in enumerate(raw_jobs):
        company = lines[0] if lines else ""
        title   = lines[1] if len(lines) > 1 else ""
        if not company or not title:
            continue

        # First card's ID is already in URL
        job_id = first_job_id if i == 0 else ""

        jobs.append({
            "company": company,
            "title":   title,
            "lines":   lines,
            "text":    " ".join(lines),
            "job_id":  job_id,
            "button":  job_buttons[i] if i < len(job_buttons) else None,
        })

    await page.close()
    return jobs


async def get_job_id_by_clicking(browser, job: dict) -> str:
    """Click a job card in a fresh page to get its jobId from the URL."""
    if job.get("job_id"):
        return job["job_id"]

    page = await browser.new_page()
    await page.set_extra_http_headers({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    })
    try:
        await page.goto(SIMPLIFY_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector('[data-testid="job-card"]', timeout=15000)
        await asyncio.sleep(2)

        # Find and click the matching card
        cards = await page.query_selector_all('[data-testid="job-card"]')
        for card in cards:
            text = await card.inner_text()
            if job["company"] in text and job["title"] in text:
                await card.click()
                await asyncio.sleep(2)
                m = re.search(r'/p/([a-f0-9-]+)/', page.url)
                if m:
                    await page.close()
                    return m.group(1)
                break
    except Exception as e:
        print(f"  [click error] {e}")
    finally:
        try:
            await page.close()
        except:
            pass
    return ""


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

        if not matches_season(job["text"]) or not matches_keywords(job["text"]):
            continue

        # Get job ID (click to navigate if needed)
        job_id = await get_job_id_by_clicking(browser, job)

        # Fetch full details if we have an ID
        details = fetch_job_details(job_id) if job_id else {}

        msg = format_message(job["company"], job["title"], job["lines"], details, job_id)
        print(f"  [ALERT] {job['company']} — {job['title']} ({job_id or 'no id'})")
        send_telegram(msg)
        new_count += 1

    return seen, new_count


async def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID before running.")
        return

    print("=" * 60)
    print("  Simplify.jobs → Telegram Bot")
    print(f"  Target: Summer/Fall 2026 SWE / AI / ML Internships")
    print(f"  Polling every {POLL_INTERVAL}s")
    print("=" * 60)

    send_telegram(
        "✅ <b>Job Alert Bot is running!</b>\n"
        "Watching Simplify.jobs for <b>Summer &amp; Fall 2026 SWE / AI / ML internships</b>.\n"
        "Each alert includes a <b>match score</b> based on your resume 🎯"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        seen = load_seen()

        if not seen:
            print("\nFirst run — seeding current listings...")
            jobs = await scrape_jobs(browser)
            for job in jobs:
                seen.add(job_key(job["company"], job["title"]))
            save_seen(seen)
            print(f"Seeded {len(seen)} jobs. Future new postings will trigger alerts.\n")

        while True:
            ts = datetime.now().strftime("%H:%M:%S")
            seen, n = await check_once(browser, seen)
            save_seen(seen)
            print(f"[{ts}] Checked Simplify — {n} new alert(s). Total tracked: {len(seen)}")
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
