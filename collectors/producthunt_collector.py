"""
producthunt_collector.py
------------------------
Pulls Product Hunt's daily launches via their public RSS feed. Earliest
public sign that a product exists — many later raise seed rounds.

Free, no auth. Filters by funding/launch-related keywords in description.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from collectors.utils import http_get, parse_rss, parse_date, now_utc_iso

PRODUCT_HUNT_FEED = "https://www.producthunt.com/feed?category=undefined"

DAYS_BACK = 14


def run() -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    print(f"[ProductHunt] Pulling launches (past {DAYS_BACK} days)...")

    resp = http_get(PRODUCT_HUNT_FEED, timeout=15)
    if resp is None or resp.status_code != 200:
        code = resp.status_code if resp else "no response"
        print(f"  [ProductHunt] HTTP {code}")
        return []

    items = parse_rss(resp.content)
    launches = []
    for item in items:
        pub_date = parse_date(item["pub_date_str"])
        if pub_date and pub_date < cutoff:
            continue
        launches.append({
            "source": "product_hunt",
            "feed_name": "Product Hunt",
            "title": item["title"],
            "url": item["link"],
            "description": item["description"][:1500],
            "article_type": "launch",
            "published_at": pub_date.isoformat() if pub_date else "",
            "fetched_at": now_utc_iso(),
        })
    print(f"[ProductHunt] {len(launches)} launches.")
    return launches


if __name__ == "__main__":
    data = run()
    out_path = os.path.join(os.path.dirname(__file__), "../output/producthunt_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(data)} results to {out_path}")
