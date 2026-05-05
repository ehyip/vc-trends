"""
twitter_collector.py
--------------------
Collects early-stage startup signals from X/Twitter via free Nitter RSS feeds.
Tracks specific high-signal VC accounts for pre-seed/seed announcements.

Nitter instances frequently die; we try a list and remember which one
worked first so we don't re-probe dead instances per account.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from collectors.utils import http_get, parse_rss, parse_date, now_utc_iso

TRACKED_ACCOUNTS = [
    "garrytan", "jason", "sacca", "paulg", "sama",
    "andrewchen", "gustaf", "daltonc", "jaltma", "hnshah",
    "hunterwalk", "semil", "alexiskold", "precursorvc",
    "techcrunch", "craborange",
]

NITTER_INSTANCES = [
    "https://xcancel.com",
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
]

DAYS_BACK = 14

FUNDING_KEYWORDS = [
    "raised", "raises", "funding", "pre-seed", "seed round",
    "angel round", "just announced", "stealth", "launching",
    "building", "co-founder", "founding", "first check",
    "backed by", "investing in", "portfolio company",
    "yc batch", "demo day", "accepted into",
]

TREND_KEYWORDS = [
    "trend", "thesis", "excited about", "bullish on",
    "the future of", "next big", "underrated space",
    "seeing a lot of", "hot take", "prediction",
    "where founders should", "emerging",
]


def _find_working_instance() -> str | None:
    """Pick the first Nitter instance that responds 200 to a probe."""
    for base in NITTER_INSTANCES:
        resp = http_get(f"{base}/garrytan/rss", timeout=10, retries=0)
        if resp is not None and resp.status_code == 200:
            return base
    return None


def fetch_account_feed(username: str, cutoff: datetime, base: str) -> list[dict]:
    resp = http_get(f"{base}/{username}/rss", timeout=15, retries=1)
    if resp is None or resp.status_code != 200:
        return []

    items = parse_rss(resp.content)
    tweets = []
    for item in items:
        pub_date = parse_date(item["pub_date_str"])
        if pub_date and pub_date < cutoff:
            continue

        title = item["title"][:200]
        description = item["description"][:500]
        combined = (title + " " + description).lower()

        is_funding = any(kw in combined for kw in FUNDING_KEYWORDS)
        is_trend = any(kw in combined for kw in TREND_KEYWORDS)
        if not is_funding and not is_trend:
            continue

        tweets.append({
            "source": "twitter",
            "author": f"@{username}",
            "title": title,
            "url": item["link"],
            "description": description,
            "article_type": "deal" if is_funding else "trend",
            "published_at": pub_date.isoformat() if pub_date else "",
            "fetched_at": now_utc_iso(),
        })
    return tweets


def run() -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    print(f"[Twitter] Collecting from {len(TRACKED_ACCOUNTS)} accounts (past {DAYS_BACK} days)...")

    base = _find_working_instance()
    if base is None:
        print("[Twitter] No working Nitter instance found — skipping.")
        return []
    print(f"[Twitter] Using {base}")

    all_tweets = []
    seen_urls = set()
    success_count = 0

    for username in TRACKED_ACCOUNTS:
        tweets = fetch_account_feed(username, cutoff, base)
        for t in tweets:
            if t["url"] and t["url"] not in seen_urls:
                seen_urls.add(t["url"])
                all_tweets.append(t)
        if tweets:
            success_count += 1
            print(f"  [@{username}] {len(tweets)} relevant tweets")

    print(f"[Twitter] {success_count}/{len(TRACKED_ACCOUNTS)} accounts produced data, {len(all_tweets)} tweets.")
    return all_tweets


if __name__ == "__main__":
    data = run()
    out_path = os.path.join(os.path.dirname(__file__), "../output/twitter_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(data)} results to {out_path}")
