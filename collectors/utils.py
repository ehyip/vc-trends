"""
utils.py
--------
Shared helpers used by every collector. Centralized so changes to HTML
stripping, date parsing, or HTTP retry logic happen in one place.
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape

import requests

DEFAULT_USER_AGENT = "VCTrendsPipeline/2.2 (+https://github.com)"

DATE_FORMATS = [
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S %Z",
    "%a, %d %b %Y %H:%M:%S GMT",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
]


def strip_html(text: str) -> str:
    """Remove HTML tags, decode entities, collapse whitespace."""
    if not text:
        return ""
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_date(date_str: str) -> datetime | None:
    """Parse a date string in any of the common RSS/Atom formats."""
    if not date_str:
        return None
    s = date_str.strip()
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def http_get(
    url: str,
    *,
    timeout: int = 15,
    headers: dict | None = None,
    retries: int = 2,
    backoff: float = 1.5,
) -> requests.Response | None:
    """GET with retry/backoff. Returns the Response or None on terminal failure.

    Retries on 5xx and connection errors. Returns immediately on 4xx (no point retrying).
    """
    h = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        h.update(headers)

    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, timeout=timeout, headers=h)
            if resp.status_code < 500:
                return resp
            # 5xx — retry
            if attempt < retries:
                time.sleep(backoff ** attempt)
                continue
            return resp
        except requests.RequestException as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff ** attempt)
                continue
    if last_exc:
        print(f"  [http] {url[:80]} failed: {last_exc}")
    return None


def parse_rss(content: bytes) -> list[dict]:
    """Parse RSS or Atom feed bytes into a list of items.

    Returns dicts with: title, link, description, pub_date_str.
    Uses stdlib XML — no external deps. Handles RSS 2.0 and Atom.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items_xml = root.findall(".//item") or root.findall(".//atom:entry", ns)
    items = []

    for item in items_xml:
        title = item.findtext("title") or item.findtext("atom:title", "", ns) or ""
        link = item.findtext("link") or ""
        if not link:
            link_el = item.find("atom:link", ns)
            if link_el is not None:
                link = link_el.get("href", "") or ""

        description = (
            item.findtext("description")
            or item.findtext("atom:summary", "", ns)
            or item.findtext("atom:content", "", ns)
            or ""
        )
        pub_date_str = (
            item.findtext("pubDate")
            or item.findtext("published")
            or item.findtext("atom:published", "", ns)
            or item.findtext("atom:updated", "", ns)
            or ""
        )

        items.append({
            "title": strip_html(title),
            "link": (link or "").strip(),
            "description": strip_html(description),
            "pub_date_str": pub_date_str,
        })
    return items


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_company_name(name: str) -> str:
    """Normalize a company name for dedup matching.

    Strips common suffixes ("Inc", "LLC", ", Inc."), punctuation, and
    lowercases. So "Anthropic, PBC" and "Anthropic" match.
    """
    if not name:
        return ""
    n = name.lower().strip()
    # Strip trailing legal suffixes
    n = re.sub(
        r",?\s*(inc\.?|llc\.?|corp\.?|corporation|ltd\.?|limited|pbc|co\.?|company|gmbh|sa|ag|plc)$",
        "",
        n,
    ).strip()
    # Strip non-alphanumeric for matching
    n = re.sub(r"[^\w\s]", "", n).strip()
    n = re.sub(r"\s+", " ", n)
    return n
