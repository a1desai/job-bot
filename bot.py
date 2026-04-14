#!/usr/bin/env python3
"""
Simplify.jobs → Telegram Job Alert Bot
No browser needed — uses Simplify's public API directly.
Polls every 60 seconds. Runs on any free cloud tier.
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

TARGET_SEASONS   = ["fall 2026", "summer 2026"]
POLL_INTERVAL    = 60
SEEN_FILE        = Path(__file__).parent / "seen_jobs.json"

KEYWORD_FILTER = [
    "software engineer", "software developer", "swe", "full stack", "fullstack",
    "backend", "frontend", "front-end", "back-end", "web developer",
    "machine learning", "ml engineer", "ai engineer", "artificial intelligence",
    "deep learning", "data scientist", "data engineer", "nlp", "computer vision",
    "research engineer", "applied scientist", "engineer intern", "engineering intern",
]

# ── ARYAN'S RESUME SKILLS ─────────────────────────────────────────────────────
RESUME_SKILLS = {
    "javascript", "typescript", "python", "java", "c++", "c/c++",
    "pytorch", "reinforcement learning", "rag", "langchain", "langgraph",
    "machine learning", "nlp", "transformers", "llm", "large language model",
    "gcp", "vertex ai",
    "react", "next.js", "nextjs", "node.js", "nodejs", "express", "express.js",
    "postgresql", "postgres", "rest", "restful api", "tailwind", "tailwind css",
    "jwt", "supabase", "git", "docker", "firebase", "aws", "aws s3",
    "jest", "ci/cd", "github actions",
    "full stack", "fullstack", "backend", "frontend", "api", "web development",
    "deep learning", "computer vision", "rag pipeline", "embeddings", "pgvector",
}
# ─────────────────────────────────────────────────────────────────────────────

HEADERS = {
    "Accept":     "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Origin":     "https://simplify.jobs",
    "Referer":    "https://simplify.jobs/",
}


def api_get(url: str) -> dict | list | None:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [API error] {url[:80]} — {e}")
        return None


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
        "disable_web_page_preview": True,
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


def job_key(job_id: str) -> str:
    return job_id.lower().strip()


def matches_keywords(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in KEYWORD_FILTER)


def matches_season(seasons: list) -> bool:
    """seasons is a list like [{'name': 'Fall 2026'}, ...]"""
    if not seasons:
        return True  # no season listed = always include
    season_names = [s.get("name", "").lower() for s in seasons]
    return any(t in name for t in TARGET_SEASONS for name in season_names)


def score_match(details: dict) -> tuple[str, str, list[str]]:
    job_text = " ".join([
        details.get("title", ""),
        details.get("description", ""),
        details.get("requirements", ""),
        details.get("responsibilities", ""),
        " ".join(s.get("name", "") for s in details.get("skills", [])),
    ]).lower()

    matched = [skill for skill in RESUME_SKILLS if skill in job_text]
    matched_display = [s.title() for s in sorted(set(matched))]

    total = max(len(re.findall(
        r'\b(?:python|javascript|typescript|react|node|java|c\+\+|sql|aws|docker|'
        r'pytorch|tensorflow|machine learning|nlp|api|git|ci/cd|kubernetes)\b',
        job_text
    )), 1)

    score = len(matched) / min(total, 10)
    if score >= 0.7 or len(matched) >= 6:
        return "Perfect Match", "🟢", matched_display
    elif score >= 0.4 or len(matched) >= 3:
        return "Strong Match", "🟡", matched_display
    elif len(matched) >= 1:
        return "Moderate Match", "🟠", matched_display
    else:
        return "Low Match", "🔴", matched_display


def format_message(details: dict) -> str:
    title    = details.get("title", "Unknown Role")
    company  = (details.get("job") or {}).get("company", {}).get("name", "Unknown Company")
    seasons  = details.get("seasons", [])
    season   = ", ".join(s.get("name", "") for s in seasons) if seasons else "Internship"
    locs     = details.get("locations", [])
    location = locs[0].get("name", "") if locs else ""
    min_sal  = details.get("min_salary")
    max_sal  = details.get("max_salary")
    currency = details.get("currency_type", "USD")
    period   = details.get("salary_period", "")
    salary   = ""
    if min_sal and max_sal:
        salary = f"{currency} ${min_sal:,.0f}–${max_sal:,.0f}/{period or 'yr'}"
    elif min_sal:
        salary = f"{currency} ${min_sal:,.0f}/{period or 'yr'}"

    job_id   = details.get("id", "")
    slug     = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    job_url  = f"https://simplify.jobs/p/{job_id}/{slug}"

    match_label, match_emoji, matched_skills = score_match(details)
    api_skills = [s.get("name", "") for s in details.get("skills", [])][:6]
    skills_str = ", ".join(api_skills) if api_skills else "Not listed"

    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🔔  <b>NEW INTERNSHIP ALERT</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"\n<b>{title}</b>")
    lines.append(f"<i>{company}</i>\n")
    if season:   lines.append(f"🗓  <b>Season</b>    <i>{season}</i>")
    if location: lines.append(f"📍  <b>Location</b>  <i>{location}</i>")
    if salary:   lines.append(f"💰  <b>Pay</b>       <i>{salary}</i>")
    lines.append("")
    lines.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
    lines.append(f"{match_emoji}  <b>Resume Match — {match_label}</b>")
    lines.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
    if matched_skills:
        lines.append(f"✅  <b>Your skills:</b>  <i>{', '.join(matched_skills[:6])}</i>")
    lines.append(f"🛠  <b>Required:</b>     <i>{skills_str}</i>")
    lines.append("")
    lines.append(f"🔗  <a href=\"{job_url}\"><b>View on Simplify →</b></a>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def fetch_job_listings(size: int = 50) -> list[dict]:
    """
    Fetch job postings from Simplify's public job-list API.
    Uses the curated internship lists which are publicly accessible.
    """
    # Get all job lists tagged as internship
    lists_url = f"https://api.simplify.jobs/v2/job-list/?page=1&size=100&value="
    data = api_get(lists_url)
    if not data or not data.get("items"):
        return []

    # Filter to internship lists
    internship_lists = [
        item for item in data["items"]
        if item.get("internship") or "intern" in item.get("title", "").lower()
           or "co-op" in item.get("title", "").lower()
    ]

    all_postings = []
    seen_ids = set()

    for lst in internship_lists[:10]:  # check top 10 internship lists
        list_id = lst["id"]
        url = (
            f"https://api.simplify.jobs/v2/job-list/:id/{list_id}"
            f"/job-with-job-posting/active?page=1&size={size}&value="
        )
        result = api_get(url)
        if not result or not result.get("items"):
            continue
        for item in result["items"]:
            posting = item.get("job_posting") or item
            pid = posting.get("id")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                all_postings.append(posting)

    return all_postings


def fetch_recent_postings() -> list[dict]:
    """
    Directly fetch recent job postings using the company search + posting endpoint.
    Falls back to job-list approach.
    """
    # Try fetching from known active job lists
    postings = fetch_job_listings()

    # Also try fetching individual job details for SWE/AI roles via company search
    if not postings:
        print("  [warn] job-list approach returned nothing, trying company search...")
        companies = ["Google", "Microsoft", "Amazon", "Meta", "Apple", "Shopify",
                     "TD Bank", "RBC", "Stripe", "Cloudflare", "Databricks"]
        for company in companies:
            url = f"https://api.simplify.jobs/v2/company/?page=1&size=3&value={urllib.parse.quote(company)}&workflow_completed=true"
            result = api_get(url)
            if result and result.get("items"):
                for c in result["items"][:1]:
                    cid = c.get("id")
                    if cid:
                        jp_url = f"https://api.simplify.jobs/v2/company/:id/{cid}/job-posting?page=1&size=5"
                        jp = api_get(jp_url)
                        if jp and jp.get("items"):
                            postings.extend(jp["items"])

    return postings


def check_once(seen: set) -> tuple[set, int]:
    postings = fetch_recent_postings()
    if not postings:
        print("  [warn] No postings returned from API")
        return seen, 0

    new_count = 0
    for posting in postings:
        pid = posting.get("id") or posting.get("tracked_obj") or ""
        if not pid or job_key(pid) in seen:
            continue

        title = posting.get("title", "")
        seasons = posting.get("seasons", [])
        card_text = title + " " + " ".join(s.get("name","") for s in seasons)

        if not matches_keywords(card_text):
            continue
        if not matches_season(seasons):
            continue

        seen.add(job_key(pid))
        msg = format_message(posting)
        company = (posting.get("job") or {}).get("company", {}).get("name", "?")
        print(f"  [ALERT] {company} — {title}")
        send_telegram(msg)
        new_count += 1

    return seen, new_count


def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID before running.")
        return

    print("=" * 60)
    print("  Simplify.jobs → Telegram Bot (API mode, no browser)")
    print(f"  Target: Summer/Fall 2026 SWE / AI / ML Internships")
    print(f"  Polling every {POLL_INTERVAL}s")
    print("=" * 60)

    send_telegram(
        "✅ <b>Job Alert Bot is running!</b>\n"
        "Watching Simplify.jobs for <b>Summer &amp; Fall 2026 SWE / AI / ML internships</b>.\n"
        "Each alert includes a <b>match score</b> based on your resume 🎯"
    )

    seen = load_seen()

    if not seen:
        print("\nFirst run — seeding current listings (no alerts yet)...")
        postings = fetch_recent_postings()
        for p in postings:
            pid = p.get("id") or p.get("tracked_obj") or ""
            if pid:
                seen.add(job_key(pid))
        save_seen(seen)
        print(f"Seeded {len(seen)} jobs. Future new postings will trigger alerts.\n")

    while True:
        ts = datetime.now().strftime("%H:%M:%S")
        seen, n = check_once(seen)
        save_seen(seen)
        print(f"[{ts}] Checked Simplify — {n} new alert(s). Total tracked: {len(seen)}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
