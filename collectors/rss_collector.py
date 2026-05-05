"""
rss_collector.py
----------------
Collects articles from RSS feeds of tech news sites and VC newsletters.

Two feed categories:
- "passthrough" feeds: every article is relevant (TechCrunch, Crunchbase News, VC blogs)
- "filtered" feeds: general tech, must match funding/startup keywords

For passthrough sources where articles aren't paywalled, we fetch the full
article body so the LLM has more context for extraction.

All feeds are free and require no API keys.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone

from collectors.utils import http_get, parse_rss, parse_date, strip_html, now_utc_iso

PASSTHROUGH_FEEDS = {
    # TechCrunch — all verticals are startup/funding relevant
    "TechCrunch Startups":  "https://techcrunch.com/category/startups/feed/",
    "TechCrunch Venture":   "https://techcrunch.com/category/venture/feed/",
    "TechCrunch Funding":   "https://techcrunch.com/tag/funding/feed/",
    "TechCrunch AI":        "https://techcrunch.com/category/artificial-intelligence/feed/",
    "TechCrunch Fintech":   "https://techcrunch.com/category/fintech/feed/",
    "TechCrunch Climate":   "https://techcrunch.com/category/climate/feed/",
    "TechCrunch Biotech":   "https://techcrunch.com/category/biotech-health/feed/",
    "TechCrunch Robotics":  "https://techcrunch.com/category/robotics/feed/",
    "TechCrunch Space":     "https://techcrunch.com/category/space/feed/",
    "Crunchbase News":      "https://news.crunchbase.com/feed/",
    "StrictlyVC":           "https://strictlyvc.com/feed/",
    "Newcomer":             "https://www.newcomer.co/feed",
    "The Generalist":       "https://www.generalist.com/feed",
    "Tomasz Tunguz":        "https://tomtunguz.com/index.xml",
    "Y Combinator Blog":    "https://www.ycombinator.com/blog/rss/",
    "AVC (Fred Wilson)":    "https://avc.com/feed",
    "Hunter Walk":          "https://hunterwalk.com/feed",
    "First Round Review":   "http://firstround.com/review/feed.xml",
}

FILTERED_FEEDS = {
    "VentureBeat":          "https://venturebeat.com/feed/",
    "Lenny's Newsletter":   "https://www.lennysnewsletter.com/feed",
    "Hacker News Best":     "https://hnrss.org/best",
    "Product Hunt":         "https://www.producthunt.com/feed",
}

FETCH_FULL_TEXT_DOMAINS = ["techcrunch.com", "news.crunchbase.com", "venturebeat.com"]

KEYWORDS = [
    "pre-seed", "preseed", "seed round", "seed funding", "seed stage",
    "angel round", "angel funding", "angel investor",
    "raises", "raised", "funding round", "million in funding",
    "just raised", "announces funding", "closes round", "secures funding",
    "funding", "venture", "startup", "founded", "co-founded", "launch",
    "stealth", "launches out of stealth", "emerges from stealth",
    "incubator", "accelerator", "y combinator", "yc w2", "yc s2",
    "techstars", "500 global",
    "$500k", "$750k", "$1m", "$1.5m", "$2m", "$2.5m", "$3m",
    "$4m", "$5m", "$6m", "$7m", "$8m", "$9m", "$10m",
    "$500,000", "$1 million", "$2 million", "$3 million", "$5 million",
    "$10 million", "$15 million",
    "vc trend", "venture capital", "startup trend",
    "emerging", "the next", "what's next",
    "thesis", "investment thesis",
    "early-stage", "seed stage", "series a",
]

DAYS_BACK = 14


def has_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def should_fetch_full(url: str) -> bool:
    return any(domain in url for domain in FETCH_FULL_TEXT_DOMAINS)


def fetch_full_article(url: str) -> str:
    """Fetch full article body. Returns first 2000 chars of extracted text."""
    resp = http_get(url, timeout=10)
    if resp is None or resp.status_code != 200:
        return ""
    html = resp.text

    article_match = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL | re.IGNORECASE)
    if article_match:
        text = strip_html(article_match.group(1))
    else:
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
        text = " ".join(strip_html(p) for p in paragraphs)

    return text[:2000]


def fetch_feed(name: str, url: str, cutoff: datetime, require_keywords: bool) -> list[dict]:
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
        description = item["description"][:1500]
        pub_date = parse_date(item["pub_date_str"])

        if pub_date and pub_date < cutoff:
            continue

        if require_keywords and not has_keywords(title + " " + description):
            continue

        if should_fetch_full(link):
            full = fetch_full_article(link)
            if len(full) > len(description):
                description = full

        articles.append({
            "source": f"rss_{name.lower().replace(' ', '_')}",
            "feed_name": name,
            "title": title,
            "url": link,
            "description": description,
            "article_type": "deal",
            "published_at": pub_date.isoformat() if pub_date else "",
            "fetched_at": now_utc_iso(),
        })
    return articles


def run() -> list[dict]:
    total_feeds = len(PASSTHROUGH_FEEDS) + len(FILTERED_FEEDS)
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    print(f"[RSS] Collecting from {total_feeds} feeds (past {DAYS_BACK} days)...")

    all_articles = []
    seen_urls = set()

    for feeds, require_kw in [(PASSTHROUGH_FEEDS, False), (FILTERED_FEEDS, True)]:
        for name, url in feeds.items():
            articles = fetch_feed(name, url, cutoff, require_kw)
            new = 0
            for a in articles:
                if a["url"] and a["url"] not in seen_urls:
                    seen_urls.add(a["url"])
                    all_articles.append(a)
                    new += 1
            tag = " (keyword filtered)" if require_kw else ""
            print(f"  [{name}] {new} articles{tag}")

    print(f"[RSS] Total: {len(all_articles)} articles")
    return all_articles


if __name__ == "__main__":
    data = run()
    out_path = os.path.join(os.path.dirname(__file__), "../output/rss_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved to {out_path}")
