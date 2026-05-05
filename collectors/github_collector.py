"""
github_collector.py
-------------------
Scrapes GitHub Trending for repos gaining traction this week. Rapid star
growth on a startup-shaped repo (auth, infra, agentic, AI tooling) is
often the earliest signal of a fundable company forming.

No API key — scrapes the public /trending HTML page.
"""

import json
import os
import re
from datetime import datetime, timezone

from collectors.utils import http_get, strip_html, now_utc_iso

TRENDING_URL = "https://github.com/trending?since=weekly"
TRENDING_LANGS = [
    "https://github.com/trending/python?since=weekly",
    "https://github.com/trending/typescript?since=weekly",
    "https://github.com/trending/rust?since=weekly",
]


def parse_trending(html: str, source_url: str) -> list[dict]:
    """Extract repo entries from a GitHub trending HTML page."""
    repos = []
    # Each repo card is wrapped in <article class="Box-row">...</article>
    for article in re.findall(r'<article class="Box-row"[^>]*>(.*?)</article>', html, flags=re.DOTALL):
        # Repo path: <a href="/owner/repo">
        href_m = re.search(r'<h2[^>]*>\s*<a\s+href="(/[^"]+)"', article)
        if not href_m:
            continue
        repo_path = href_m.group(1).strip()
        full_url = f"https://github.com{repo_path}"

        # Description in <p class="col-9 ...">
        desc_m = re.search(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', article, flags=re.DOTALL)
        description = strip_html(desc_m.group(1)) if desc_m else ""

        # Stars gained this week — last span has "stars this week" or similar
        stars_m = re.search(r'(\d[\d,]*)\s*stars?\s*(?:this\s+week|today)', article)
        stars_gained = stars_m.group(1) if stars_m else "?"

        owner_repo = repo_path.lstrip("/")
        repos.append({
            "source": "github_trending",
            "feed_name": "GitHub Trending",
            "title": f"{owner_repo} — {stars_gained} stars this week",
            "url": full_url,
            "description": f"{description} (gained {stars_gained} stars this week on GitHub Trending)",
            "company_name": owner_repo.split("/")[-1] if "/" in owner_repo else owner_repo,
            "article_type": "trending_repo",
            "published_at": "",
            "fetched_at": now_utc_iso(),
            "trending_source": source_url,
        })
    return repos


def run() -> list[dict]:
    print("[GitHub] Scraping trending repos (weekly)...")
    all_repos = []
    seen_urls = set()

    for url in [TRENDING_URL] + TRENDING_LANGS:
        resp = http_get(url, timeout=15)
        if resp is None or resp.status_code != 200:
            code = resp.status_code if resp else "no response"
            print(f"  [GitHub] {url} HTTP {code}")
            continue
        repos = parse_trending(resp.text, url)
        new = 0
        for r in repos:
            if r["url"] in seen_urls:
                continue
            seen_urls.add(r["url"])
            all_repos.append(r)
            new += 1
        lang = url.split("/")[-1].split("?")[0] or "all"
        print(f"  [GitHub/{lang}] {new} new repos")

    print(f"[GitHub] {len(all_repos)} trending repos total.")
    return all_repos


if __name__ == "__main__":
    data = run()
    out_path = os.path.join(os.path.dirname(__file__), "../output/github_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(data)} results to {out_path}")
