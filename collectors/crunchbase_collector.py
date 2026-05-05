"""
crunchbase_collector.py
-----------------------
Collects early-stage funding announcements from Crunchbase News RSS feeds.

Pre-extracts amount, round type, and lead investor with regex so the LLM
has hints to work with even before the extraction pass.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone

from collectors.utils import http_get, parse_rss, parse_date, now_utc_iso

CRUNCHBASE_FEEDS = {
    "Crunchbase Main":      "https://news.crunchbase.com/feed/",
    "Crunchbase Seed":      "https://news.crunchbase.com/tag/seed/feed/",
    "Crunchbase Pre-Seed":  "https://news.crunchbase.com/tag/pre-seed/feed/",
    "Crunchbase AI":        "https://news.crunchbase.com/sections/ai/feed/",
}

DAYS_BACK = 14

FUNDING_WORDS = [
    "raises", "raised", "funding", "seed", "pre-seed",
    "million", "series", "round", "backed", "invest",
    "startup", "stealth", "launch",
]


def extract_funding_details(text: str) -> dict:
    details = {"amount": "", "round_type": "", "investors": ""}

    amount_match = re.search(r'\$[\d,.]+\s*(?:million|billion|M|B|m|b)\b', text, re.IGNORECASE)
    if amount_match:
        details["amount"] = amount_match.group(0).strip()

    for pattern in [r'pre-seed', r'preseed', r'seed\s+round', r'seed\s+funding',
                    r'angel\s+round', r'series\s+a', r'series\s+b']:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            details["round_type"] = m.group(0).strip().title()
            break

    investor_match = re.search(
        r'(?:led by|from|backed by|investors? include)\s+([^.;,]{3,60})',
        text, re.IGNORECASE
    )
    if investor_match:
        details["investors"] = investor_match.group(1).strip()

    return details


def fetch_rss_feed(name: str, url: str, cutoff: datetime) -> list[dict]:
    resp = http_get(url, timeout=15)
    if resp is None or resp.status_code != 200:
        code = resp.status_code if resp else "no response"
        print(f"  [{name}] HTTP {code}")
        return []

    items = parse_rss(resp.content)
    articles = []
    for item in items:
        title = item["title"]
        link = item["link"]
        description = item["description"][:600]
        pub_date = parse_date(item["pub_date_str"])

        if pub_date and pub_date < cutoff:
            continue

        combined = title + " " + description
        if not any(w in combined.lower() for w in FUNDING_WORDS):
            continue

        funding = extract_funding_details(combined)

        articles.append({
            "source": "crunchbase_news",
            "feed_name": name,
            "title": title,
            "url": link,
            "description": description,
            "amount": funding["amount"],
            "round_type": funding["round_type"],
            "investors": funding["investors"],
            "article_type": "deal",
            "published_at": pub_date.isoformat() if pub_date else "",
            "fetched_at": now_utc_iso(),
        })
    return articles


def run() -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    print(f"[Crunchbase] Collecting from {len(CRUNCHBASE_FEEDS)} feeds (past {DAYS_BACK} days)...")

    all_articles = []
    seen_urls = set()
    for name, url in CRUNCHBASE_FEEDS.items():
        articles = fetch_rss_feed(name, url, cutoff)
        new = 0
        for a in articles:
            if a["url"] and a["url"] not in seen_urls:
                seen_urls.add(a["url"])
                all_articles.append(a)
                new += 1
        print(f"  [{name}] {new} new articles")

    print(f"[Crunchbase] Found {len(all_articles)} funding articles total.")
    return all_articles


if __name__ == "__main__":
    data = run()
    out_path = os.path.join(os.path.dirname(__file__), "../output/crunchbase_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(data)} results to {out_path}")
