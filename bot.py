#!/usr/bin/env python3
"""
Simplify.jobs → Telegram Job Alert Bot
No browser — uses Simplify's public API directly.
Runs a tiny health-check HTTP server so Railway keeps it alive.
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
PORT             = int(os.environ.get("PORT", 8080))

TARGET_SEASONS   = ["fall 2026", "summer 2026"]
POLL_INTERVAL    = 60
SEEN_FILE        = Path(__file__).parent / "seen_jobs.json"
SALARY_PERIOD_MAP = {1: "hr", 2: "wk", 3: "mo", 4: "yr"}

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


# ── TINY HEALTH CHECK SERVER (keeps Railway alive) ────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Job bot is running")
    def log_message(self, *_):
        pass  # suppress access logs

def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Health server listening on port {PORT}")
# ─────────────────────────────────────────────────────────────────────────────


def api_get(url: str):
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


def parse_seasons(seasons_raw) -> list[str]:
    """Safely extract season strings regardless of API shape."""
    if not seasons_raw:
        return []
    result = []
    for s in seasons_raw:
        if isinstance(s, str):
            result.append(s.lower())
        elif isinstance(s, dict):
            val = s.get("name") or s.get("value") or s.get("label") or ""
            result.append(str(val).lower())
        elif isinstance(s, list):
            result.extend(parse_seasons(s))
    return result


def matches_season(seasons_raw) -> bool:
    seasons = parse_seasons(seasons_raw)
    if not seasons:
        return True  # no season = always include
    return any(t in s for t in TARGET_SEASONS for s in seasons)


def is_internship(posting: dict) -> bool:
    """Return True only for actual internship/co-op postings."""
    title = (posting.get("title") or "").lower()
    intern_words = ["intern", "co-op", "coop", "student", "new grad", "university grad"]
    return any(w in title for w in intern_words)


def matches_keywords(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in KEYWORD_FILTER)


def score_match(details: dict) -> tuple[str, str, list[str]]:
    def to_str(val):
        if isinstance(val, list):
            return " ".join(str(v) for v in val)
        return str(val) if val else ""

    job_text = " ".join([
        to_str(details.get("title")),
        to_str(details.get("description")),
        to_str(details.get("requirements")),
        to_str(details.get("responsibilities")),
        " ".join(
            (s.get("name") if isinstance(s, dict) else str(s))
            for s in details.get("skills", [])
        ),
    ]).lower()

    matched = [skill for skill in RESUME_SKILLS if skill in job_text]
    matched_display = [s.title() for s in sorted(set(matched))]

    total = max(len(re.findall(
        r'\b(?:python|javascript|typescript|react|node\.?js|java|c\+\+|sql|aws|docker|'
        r'pytorch|tensorflow|machine.?learning|nlp|api|git|ci/?cd|kubernetes|'
        r'langchain|langgraph|rag|next\.?js|gcp|postgresql|supabase)\b',
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
    job_info = details.get("job") or {}
    company  = ""
    if isinstance(job_info, dict) and job_info:
        company = (job_info.get("company") or {}).get("name", "")
    if not company:
        company = details.get("company_name", "Unknown Company")

    seasons_raw = details.get("seasons", [])
    seasons     = parse_seasons(seasons_raw)
    season_str  = ", ".join(s.title() for s in seasons) if seasons else "Internship"

    locs     = details.get("locations", [])
    location = ""
    if locs and isinstance(locs[0], dict):
        location = locs[0].get("value") or locs[0].get("name", "")

    try:
        min_sal = float(details.get("min_salary") or 0) or None
        max_sal = float(details.get("max_salary") or 0) or None
    except (TypeError, ValueError):
        min_sal = max_sal = None
    currency = details.get("currency_type", "USD")
    period   = SALARY_PERIOD_MAP.get(details.get("salary_period"), "yr")
    salary   = ""
    if min_sal and max_sal:
        salary = f"{currency} ${min_sal:,.0f}–${max_sal:,.0f}/{period}"
    elif min_sal:
        salary = f"{currency} ${min_sal:,.0f}/{period}"

    job_id  = details.get("id", "")
    slug    = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    job_url = f"https://simplify.jobs/p/{job_id}/{slug}" if job_id else \
              f"https://simplify.jobs/jobs?search={urllib.parse.quote_plus(f'{company} {title}')}&jobType=Internship"

    match_label, match_emoji, matched_skills = score_match(details)
    api_skills = details.get("skills", [])
    skill_names = [
        (s.get("name") if isinstance(s, dict) else str(s))
        for s in api_skills[:6]
    ]
    skills_str = ", ".join(filter(None, skill_names)) or "Not listed"

    lines = []
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🔔  <b>NEW INTERNSHIP ALERT</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"\n<b>{title}</b>")
    lines.append(f"<i>{company}</i>\n")
    if season_str: lines.append(f"🗓  <b>Season</b>    <i>{season_str}</i>")
    if location:   lines.append(f"📍  <b>Location</b>  <i>{location}</i>")
    if salary:     lines.append(f"💰  <b>Pay</b>       <i>{salary}</i>")
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


def fetch_postings() -> list[dict]:
    """Fetch internship postings by scanning top tech/finance companies."""
    companies = [
        "Google", "Microsoft", "Amazon", "Meta", "Apple", "Shopify",
        "Stripe", "Cloudflare", "Databricks", "OpenAI", "Anthropic",
        "TD-Bank", "Royal-Bank-of-Canada", "Nvidia", "TikTok", "Ramp", "Figma",
        "Palantir", "Waymo", "Scale-AI", "Cohere", "Wealthsimple",
    ]
    extra = os.environ.get("EXTRA_COMPANIES", "")
    extra_companies = [c.strip() for c in extra.split(",") if c.strip()]
    companies = companies + extra_companies

    all_postings = []
    seen_ids = set()

    for slug in companies:
        url = f"https://api.simplify.jobs/v2/company/:slug/{slug}"
        company_data = api_get(url)
        if not company_data or "id" not in company_data:
            continue

        cid = company_data["id"]
        url2 = f"https://api.simplify.jobs/v2/company/:id/{cid}/job-posting?page=1&size=50&active=true"
        result = api_get(url2)
        # Some companies (Amazon, Meta, Apple) return 500 with active=true — fall back
        if not result or not result.get("items"):
            url2 = f"https://api.simplify.jobs/v2/company/:id/{cid}/job-posting?page=1&size=20"
            result = api_get(url2)
        if not result or not result.get("items"):
            continue

        for posting in result["items"]:
            pid = posting.get("id") or posting.get("tracked_obj", "")
            if pid and pid not in seen_ids and posting.get("active"):
                seen_ids.add(pid)
                # Always inject so format_message can use it as fallback
                posting["company_name"] = company_data.get("name", slug)
                all_postings.append(posting)

    if len(all_postings) == 0:
        print("  WARNING: All company fetches returned 0 active postings — check API or network.")
    print(f"  Fetched {len(all_postings)} active postings from {len(companies)} companies")
    return all_postings


def check_once(seen: set) -> tuple[set, int]:
    postings = fetch_postings()
    new_count = 0

    for posting in postings:
        pid = posting.get("id") or posting.get("tracked_obj", "")
        if not pid or pid in seen:
            continue

        title       = posting.get("title", "")
        seasons_raw = posting.get("seasons", [])
        desc        = posting.get("description", "") or ""
        card_text   = f"{title} {desc[:200]}"

        # Add season info from description if seasons field is empty
        if not seasons_raw:
            for season in ["Summer 2026", "Fall 2026", "Spring 2026", "Winter 2026"]:
                if season.lower() in desc.lower():
                    seasons_raw = [season]
                    break

        seen.add(pid)

        if not is_internship(posting):
            continue
        if not matches_keywords(card_text):
            continue
        if not matches_season(seasons_raw):
            continue

        posting["seasons"] = seasons_raw  # inject parsed seasons back
        msg = format_message(posting)
        company = (posting.get("job") or {}).get("company", {}).get("name") \
                  or posting.get("company_name", "?")
        print(f"  [ALERT] {company} — {title}")
        send_telegram(msg)
        new_count += 1

    return seen, new_count


def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID before running.")
        return

    start_health_server()

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

    seen = load_seen()

    if not seen:
        print("\nFirst run — seeding current listings (no alerts yet)...")
        postings = fetch_postings()
        for p in postings:
            pid = p.get("id") or p.get("tracked_obj", "")
            if pid:
                seen.add(pid)
        save_seen(seen)
        print(f"Seeded {len(seen)} jobs. Future new postings will trigger alerts.\n")

    while True:
        ts = datetime.now().strftime("%H:%M:%S")
        seen, n = check_once(seen)
        save_seen(seen)
        print(f"[{ts}] Checked — {n} new alert(s). Total tracked: {len(seen)}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
