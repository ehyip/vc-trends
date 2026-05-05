"""
edgar_collector.py
------------------
Monitors SEC EDGAR for Form D filings — the EARLIEST legal signal of a
funding round. Every US company raising private capital must file a Form D
within 15 days. This often appears before any press coverage.

Uses the free EDGAR EFTS (full-text search) API. No API key needed.
Form D filings here are pre-marked as already-extracted so the LLM batch
extractor leaves their fields alone.

SEC blocks some cloud-host IPs; we retry once and, if blocked, back off
silently rather than spamming the API.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone

from collectors.utils import http_get, now_utc_iso

EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# SEC requires a contact email in the User-Agent header.
# Set EDGAR_CONTACT_EMAIL in your environment (or GitHub secrets) — falls back
# to a generic value if unset, but SEC may rate-limit anonymous-looking traffic.
EDGAR_CONTACT_EMAIL = os.getenv("EDGAR_CONTACT_EMAIL", "anonymous@example.com")

SEARCH_QUERIES = [
    "artificial intelligence", "machine learning", "software platform",
    "SaaS", "developer tools", "robotics", "biotech", "climate tech",
    "fintech", "cybersecurity", "autonomous", "blockchain",
    "quantum computing", "defense technology", "healthtech", "edtech",
]

DAYS_BACK = 14
MAX_AMOUNT = 15_000_000

# Set on first 403 to stop hammering EDGAR for the rest of the run
_EDGAR_BLOCKED = False


def search_edgar(query: str, start_date: str) -> list[dict]:
    global _EDGAR_BLOCKED
    if _EDGAR_BLOCKED:
        return []

    params = f"?q=%22{query.replace(' ', '+')}%22&forms=D&dateRange=custom&startdt={start_date}"
    url = f"{EDGAR_SEARCH_URL}{params}"
    headers = {
        "User-Agent": f"VCTrendsPipeline/2.2 {EDGAR_CONTACT_EMAIL}",
        "Accept": "application/json",
    }

    resp = http_get(url, timeout=20, headers=headers, retries=1)
    if resp is None:
        return []
    if resp.status_code == 403:
        if not _EDGAR_BLOCKED:
            print("  [EDGAR] 403 blocked (likely cloud-host IP) — skipping remaining queries.")
        _EDGAR_BLOCKED = True
        return []
    if resp.status_code != 200:
        return []

    try:
        data = resp.json()
    except ValueError:
        return []
    return data.get("hits", {}).get("hits", [])


def parse_filing(hit: dict) -> dict | None:
    source = hit.get("_source", {})

    company_name = ""
    if source.get("display_names"):
        company_name = source["display_names"][0]
    if not company_name:
        company_name = source.get("entity_name", "")
    if not company_name:
        return None
    # display_names sometimes returns "Company Inc. (CIK 0001234567)" — strip trailing CIK
    company_name = re.sub(r"\s*\(CIK[^)]+\)\s*$", "", company_name).strip()

    filing_date = source.get("file_date", "")
    snippet = source.get("text", "")

    amount = ""
    amount_match = re.search(r'\$[\d,]+(?:\.\d+)?', snippet)
    if amount_match:
        try:
            raw = amount_match.group(0).replace("$", "").replace(",", "")
            val = float(raw)
            if val > MAX_AMOUNT:
                return None
            if val >= 1_000_000:
                amount = f"${val/1_000_000:.1f}M"
            elif val >= 1_000:
                amount = f"${val/1_000:.0f}K"
            else:
                amount = f"${val:,.0f}"
        except ValueError:
            pass

    cik = source.get("entity_id", "") or (source.get("ciks", [""])[0] if source.get("ciks") else "")
    filing_url = ""
    if cik:
        filing_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=D&dateb=&owner=include&count=10"

    return {
        "source": "edgar_form_d",
        "title": f"Form D: {company_name}",
        "company_name": company_name,
        "sector": "unknown",  # EDGAR doesn't tell us sector directly
        "url": filing_url or f"https://efts.sec.gov/LATEST/search-index?q=%22{company_name.replace(' ', '+')}%22&forms=D",
        "description": f"SEC Form D filing by {company_name}. {snippet[:300]}",
        "amount": amount,
        "round_type": "Form D (likely seed/pre-seed)",
        "thesis": f"Form D filing — {company_name} raised private capital and disclosed it to the SEC.",
        "investors": "unknown",
        "founder_background": "unknown",
        "article_type": "deal",
        "filing_date": filing_date,
        "published_at": filing_date,
        "fetched_at": now_utc_iso(),
        # Tell the analyzer not to re-extract this — fields are already set
        "skip_llm_extraction": True,
    }


def run() -> list[dict]:
    start_date = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
    print(f"[EDGAR] Searching Form D filings since {start_date} across {len(SEARCH_QUERIES)} queries...")

    all_filings = []
    seen_companies = set()

    for query in SEARCH_QUERIES:
        hits = search_edgar(query, start_date)
        new_count = 0
        for hit in hits:
            filing = parse_filing(hit)
            if filing is None:
                continue
            key = filing["company_name"].lower().strip()
            if key in seen_companies or key in ("unknown", ""):
                continue
            seen_companies.add(key)
            filing["edgar_query"] = query
            all_filings.append(filing)
            new_count += 1
        if new_count > 0:
            print(f"  [EDGAR] '{query}': {new_count} new filings")

    print(f"[EDGAR] Found {len(all_filings)} Form D filings total (< ${MAX_AMOUNT/1_000_000:.0f}M).")
    return all_filings


if __name__ == "__main__":
    data = run()
    out_path = os.path.join(os.path.dirname(__file__), "../output/edgar_results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved {len(data)} results to {out_path}")
