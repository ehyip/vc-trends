"""
trend_analyzer.py
-----------------
Uses Groq + Llama 4 to:
1. Extract structured deal info from batches of articles
2. Cluster all deals into emerging themes
3. Write a trend analysis identifying what's coming NEXT — before it's consensus

Two-pass approach:
  Pass 1: BATCH extract deal details (15 signals per API call)
  Pass 2: Look across ALL deals, cluster into themes, compare with last week

Designed to stay well within Groq free tier limits (~10 API calls total).
Cost: $0 (Groq free tier)
"""

import os
import re
import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
FALLBACK_MODEL = "llama-3.3-70b-versatile"

BATCH_SIZE = 20           # Signals per LLM call (keeps total calls low)
MAX_SIGNALS_TO_ANALYZE = 400  # Hard cap
DAILY_LIMIT_HIT = False


# ─── Pass 1: Batch extract deal details ───────────────────────────────────────

BATCH_EXTRACT_SYSTEM = """You are a venture capital analyst focused on the EARLIEST stage deals.
Extract structured information from EACH article below.

CRITICAL RULES:
- If an article describes a Series B or later (>$50M), set round_type to "series B+" — 
  these will be filtered out downstream.
- Focus on pre-seed, seed, angel, Form D, and stealth launches.
- For the sector field, be SPECIFIC: "AI agents for insurance claims" not just "AI".
- For the thesis field, explain what makes this company interesting as an early signal.
- If information is not available, use "unknown".
- Return a JSON object with key "deals" containing an array — one entry per article.
  Match the order of the input articles."""

BATCH_EXTRACT_USER = """Extract deal information from each of these {n} articles.

{articles}

Return JSON:
{{
  "deals": [
    {{
      "index": 1,
      "company_name": "<name>",
      "sector": "<specific 3-5 word sector, e.g. 'AI agents for legal discovery'>",
      "round_type": "<pre-seed|seed|angel|form-d|stealth|series A|series B+|unknown>",
      "amount": "<funding amount or 'unknown'>",
      "thesis": "<one sentence: what does this company do and why is it an early signal?>",
      "founder_background": "<notable background if mentioned, or 'unknown'>",
      "investors": "<lead investors if mentioned, or 'unknown'>"
    }}
  ]
}}

Return one entry per article, in order. Do NOT skip any article."""


# ─── Pass 2: Theme clustering ─────────────────────────────────────────────────

CLUSTER_SYSTEM = """You are a senior VC analyst writing a weekly intelligence brief about
the EARLIEST stage of startup funding — pre-seed, seed, angel, and stealth.

Your job is to spot what will become a trend BEFORE it's obvious. You're not tracking
what VCs are already excited about — you're tracking what they're ABOUT to be excited about.

CRITICAL — DO NOT INCLUDE:
- Public companies, mega-cap private companies, or household-name AI labs
  (Stripe, OpenAI, Anthropic, Google, Meta, Microsoft, Amazon, Nvidia, Tesla,
  Apple, Salesforce, Databricks, Snowflake, Palantir, Scale AI, Perplexity,
  Mistral, Cohere, xAI, DoorDash, Uber, Revolut, Klarna, Coinbase, Robinhood,
  Cash App, Shopify, Airbnb, Spotify, Netflix, etc.).
  News ABOUT these companies is NOT an early-stage signal.
- Acquisitions, IPOs, mega-rounds (>$50M), or "valued at $X billion" stories.
- Themes supported by only 1 deal — minimum 2 distinct companies per theme.

RULES:
- Focus on deals under $10M — these are the signals that predict where capital flows next.
- Be HYPER-SPECIFIC with theme names: "AI agents for insurance claims processing" not "AI" or "AI agents".
- Each theme MUST be supported by ≥2 actual companies from the input data.
- example_companies must contain ONLY companies that appear in the input list.
- Order themes by how "ahead of consensus" they are, not by deal count.
- The contrarian_angle should explain what most investors are MISSING about this theme.
- For the prediction, think about: if these seeds sprout, what does the Series A landscape look like in 6 months?"""

CLUSTER_USER = """Here are {count} early-stage deals and signals from the past week:

{deals_summary}

{previous_context}

Based on these deals, write a trend analysis with this exact JSON structure:
{{
  "themes": [
    {{
      "theme_name": "<hyper-specific theme, 5-10 words>",
      "signal_strength": "<strong|moderate|emerging>",
      "deal_count": <number of deals in this cluster>,
      "example_companies": ["<company1>", "<company2>"],
      "why_now": "<1-2 sentences: why is this theme emerging right now?>",
      "contrarian_angle": "<1 sentence: what does the market NOT yet see about this?>",
      "momentum": "<accelerating|steady|new_this_week>"
    }}
  ],
  "biggest_surprise": "<1-2 sentences: the most unexpected pattern you see — what's getting funded that nobody is talking about yet?>",
  "prediction": "<2-3 sentences: based on these earliest-stage signals, what will become a hot Series A thesis in 3-6 months? Be specific and bold.>",
  "sectors_cooling": "<1-2 sentences: any sectors that seem to be losing early-stage momentum compared to recent weeks?>",
  "weak_signals": "<1-2 sentences: patterns that appear in only 1-2 deals but could be significant if they grow>"
}}

Return 5-8 themes, ordered by how FAR AHEAD of consensus they are (not by deal count).
Theme 1 should be the most contrarian / least obvious pattern."""


def call_groq(messages: list[dict], model: str = MODEL, max_tokens: int = 2000) -> str | None:
    """Make a Groq API call. Returns content or None."""
    global DAILY_LIMIT_HIT
    if not GROQ_API_KEY or DAILY_LIMIT_HIT:
        return None

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=90)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        elif resp.status_code == 429:
            body = resp.text.lower()
            if "per day" in body or "daily" in body:
                print("  [Groq] Daily rate limit hit — stopping LLM calls.")
                DAILY_LIMIT_HIT = True
                return None
            # Per-minute limit — wait and retry once
            print("  [Groq] Rate limited, waiting 20s...")
            time.sleep(20)
            resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=90)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            elif resp.status_code == 429:
                DAILY_LIMIT_HIT = True
                print("  [Groq] Still rate limited — stopping.")
                return None
        elif resp.status_code == 404:
            if model == MODEL:
                print(f"  [Groq] Model {MODEL} not found, falling back to {FALLBACK_MODEL}")
                return call_groq(messages, model=FALLBACK_MODEL, max_tokens=max_tokens)
        print(f"  [Groq] Error {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"  [Groq] Request error: {e}")
        return None


def extract_batch(batch: list[dict], batch_num: int, total_batches: int) -> list[dict]:
    """Extract deal details from a batch of signals in a SINGLE API call."""
    # Build article text block
    art_lines = []
    for idx, signal in enumerate(batch, 1):
        title = (signal.get("title") or "")[:200]
        source = signal.get("source", "unknown")
        desc = (signal.get("description") or "")[:400]
        art_lines.append(f"--- Article {idx} ---\nTitle: {title}\nSource: {source}\nContent: {desc}\n")

    messages = [
        {"role": "system", "content": BATCH_EXTRACT_SYSTEM},
        {"role": "user", "content": BATCH_EXTRACT_USER.format(
            n=len(batch), articles="\n".join(art_lines)
        )},
    ]

    print(f"  [Analyzer] Batch {batch_num}/{total_batches} ({len(batch)} signals)...")
    content = call_groq(messages, max_tokens=3000)
    if not content:
        content = call_groq(messages, model=FALLBACK_MODEL, max_tokens=3000)

    # Parse response and merge back into signals
    deals = []
    try:
        parsed = json.loads(content) if content else {}
        extracted = parsed.get("deals", [])
    except (json.JSONDecodeError, TypeError):
        extracted = []

    def _better(new_val, old_val):
        """Prefer a real value over 'unknown' / empty, regardless of source."""
        new_clean = (new_val or "").strip()
        old_clean = (old_val or "").strip()
        if new_clean and new_clean.lower() != "unknown":
            return new_clean
        return old_clean or "unknown"

    for idx, signal in enumerate(batch):
        details = extracted[idx] if idx < len(extracted) else {}

        signal["company_name"] = _better(details.get("company_name"), signal.get("company_name"))
        signal["sector"] = _better(details.get("sector"), signal.get("sector"))
        signal["round_type"] = _better(details.get("round_type"), signal.get("round_type"))
        signal["thesis"] = details.get("thesis") or signal.get("thesis", "")
        signal["founder_background"] = _better(details.get("founder_background"), signal.get("founder_background"))
        signal["investors"] = _better(details.get("investors"), signal.get("investors"))
        signal["amount"] = _better(details.get("amount"), signal.get("amount"))

        deals.append(signal)

    extracted_count = sum(1 for d in deals if d.get("company_name", "unknown") != "unknown")
    print(f"       → {extracted_count}/{len(batch)} companies identified")
    return deals


def load_previous_themes() -> str:
    """Load last week's themes for structured comparison (if available).

    Format the prior themes with their deal counts AND example companies so
    the model can recognize which clusters are continuing, accelerating,
    or fading rather than guessing from a name alone.
    """
    prev_path = Path(__file__).parent.parent / "output" / "previous_themes.json"
    if not prev_path.exists():
        return ""

    try:
        with open(prev_path) as f:
            prev = json.load(f)
        themes = prev.get("themes", [])
        if not themes:
            return ""
        lines = [
            "LAST WEEK'S THEMES — for each one, classify in your output as:",
            "  · ACCELERATING (more deals this week)",
            "  · STEADY (similar deal count)",
            "  · FADING (fewer deals)",
            "  · DEAD (no longer in this week's data — omit from new themes)",
            "and add momentum='accelerating'/'steady'/'new_this_week' on each new theme.",
            "",
        ]
        for t in themes:
            companies = ", ".join(t.get("example_companies", [])[:3]) or "—"
            lines.append(
                f"- {t.get('theme_name', '?')} "
                f"[{t.get('signal_strength', '?')}, {t.get('deal_count', 0)} deals] "
                f"e.g. {companies}"
            )
        return "\n".join(lines)
    except Exception:
        return ""


def save_current_themes(theme_analysis: dict):
    """Save this week's themes for next week's comparison."""
    out_path = Path(__file__).parent.parent / "output" / "previous_themes.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(out_path, "w") as f:
            json.dump(theme_analysis, f, indent=2)
    except Exception:
        pass


def cluster_themes(signals: list[dict]) -> dict:
    """Pass 2: Analyze all deals together to find emerging themes."""
    deal_lines = []
    for s in signals:
        company = s.get("company_name", "unknown")
        sector = s.get("sector", "unknown")
        thesis = s.get("thesis", "")
        amount = s.get("amount", "")
        round_type = s.get("round_type", "")
        source = s.get("source", "")
        line = f"- {company} ({sector}, {round_type} {amount}) [{source}]: {thesis}"
        deal_lines.append(line[:250])

    deals_summary = "\n".join(deal_lines)

    # Truncate if too long for context window
    if len(deals_summary) > 12000:
        deals_summary = deals_summary[:12000] + "\n... (truncated)"

    previous_context = load_previous_themes()

    messages = [
        {"role": "system", "content": CLUSTER_SYSTEM},
        {"role": "user", "content": CLUSTER_USER.format(
            count=len(signals),
            deals_summary=deals_summary,
            previous_context=previous_context,
        )},
    ]

    if not GROQ_API_KEY:
        return {"themes": [], "biggest_surprise": "N/A", "prediction": "N/A", "sectors_cooling": "N/A", "weak_signals": "N/A"}

    # Try primary model, then fallback
    content = call_groq(messages, max_tokens=3000)
    if not content:
        time.sleep(5)
        content = call_groq(messages, model=FALLBACK_MODEL, max_tokens=3000)

    try:
        result = json.loads(content) if content else {}
        if "themes" in result:
            return result
    except Exception as e:
        print(f"  [Cluster] Parse error: {e}")

    return {"themes": [], "biggest_surprise": "Error in clustering", "prediction": "N/A", "sectors_cooling": "N/A", "weak_signals": "N/A"}


# Companies to exclude from "early-stage" — already public, mega-cap, or
# household names that keep appearing in news without being seed-stage deals.
EXCLUDED_COMPANIES = {
    "openai", "anthropic", "google", "alphabet", "meta", "facebook", "apple",
    "microsoft", "amazon", "nvidia", "tesla", "stripe", "spacex", "x", "twitter",
    "doordash", "uber", "lyft", "airbnb", "snowflake", "databricks", "palantir",
    "salesforce", "oracle", "ibm", "intel", "amd", "qualcomm", "samsung",
    "revolut", "klarna", "robinhood", "coinbase", "binance", "circle",
    "shopify", "square", "block", "paypal", "cash app", "venmo",
    "tiktok", "bytedance", "snap", "snapchat", "reddit", "pinterest",
    "spotify", "netflix", "disney", "warner", "comcast",
    "y combinator", "yc", "techstars", "a16z", "sequoia",
    "faraday future", "rivian", "lucid",
    "scale ai", "perplexity", "mistral", "cohere", "xai",
}

# Phrases in title/thesis that indicate this is NOT an early-stage deal
EXIT_INDICATORS = [
    "acquired", "acquires", "acquisition", "buys ", "bought by",
    "ipo", "going public", "valuation of $", "valued at $",
    "raises $", "lawsuit", "sued", "files for bankruptcy",
]


def _has_exit_signal(s: dict) -> bool:
    """Check if title/thesis suggests an acquisition, IPO, or mega-round."""
    text = " ".join([
        s.get("title", ""), s.get("thesis", ""), s.get("description", "")
    ]).lower()

    # Acquisitions / exits
    if any(kw in text for kw in ["acquired", "acquisition", "bought by", "ipo", "going public"]):
        return True

    # Mega-valuations or mega-rounds in the text (>$50M / >$1B)
    # Match $XXM where XX>=50, or any $XB
    if re.search(r'\$\d+\s*b\b|\$\d{2,}\s*b\b', text, re.IGNORECASE):
        return True
    big_m = re.findall(r'\$(\d+(?:\.\d+)?)\s*m\b', text, re.IGNORECASE)
    for m in big_m:
        try:
            if float(m) > 50:
                return True
        except ValueError:
            pass
    return False


def _is_excluded_company(s: dict) -> bool:
    name = (s.get("company_name") or "").lower().strip()
    if not name or name == "unknown":
        return False
    # Exact match on the company name
    if name in EXCLUDED_COMPANIES:
        return True
    # Word-boundary match (e.g. "Anthropic raises..." → name might be just "Anthropic")
    for excluded in EXCLUDED_COMPANIES:
        if name == excluded or name.startswith(excluded + " ") or name.endswith(" " + excluded):
            return True
    return False


def filter_early_stage(signals: list[dict]) -> list[dict]:
    """Post-extraction filter: keep ONLY clearly early-stage deals.

    Drops:
    - Series B+ rounds
    - Amounts > $15M (parsed from `amount` field)
    - Acquisitions, IPOs, lawsuits (parsed from title/thesis)
    - Mega-valuations / mega-rounds mentioned in text (>$50M, any $B)
    - Known public / mega-cap companies (Anthropic, Stripe, DoorDash, etc.)
    """
    early_stage = []
    for s in signals:
        rt = (s.get("round_type") or "").lower()
        if any(x in rt for x in ["series b", "series c", "series d", "series e", "series f", "ipo", "growth"]):
            continue

        amount_str = s.get("amount", "")
        if amount_str and amount_str.lower() != "unknown":
            try:
                clean = amount_str.replace("$", "").replace(",", "").strip().lower()
                if "b" in clean:
                    continue
                if "m" in clean:
                    val = float(re.sub(r'[^\d.]', '', clean.split("m")[0]))
                    if val > 15:
                        continue
            except (ValueError, IndexError):
                pass

        if _is_excluded_company(s):
            continue

        if _has_exit_signal(s):
            continue

        early_stage.append(s)
    return early_stage


def run(signals: list[dict]) -> tuple[list[dict], dict]:
    """
    Two-pass analysis:
    1. Batch extract deal details (15 signals per API call → ~13 calls for 200 signals)
    2. Filter to early-stage, then cluster into themes

    Returns (enriched_signals, theme_analysis)
    """
    global DAILY_LIMIT_HIT

    if not GROQ_API_KEY:
        print("[Analyzer] No GROQ_API_KEY — skipping analysis.")
        return signals, {"themes": [], "biggest_surprise": "N/A", "prediction": "N/A"}

    # Split: signals that need LLM extraction vs. those already-structured
    # (currently EDGAR Form D filings — they set skip_llm_extraction=True)
    needs_extraction = [s for s in signals if not s.get("skip_llm_extraction")]
    pre_structured = [s for s in signals if s.get("skip_llm_extraction")]

    to_analyze = needs_extraction[:MAX_SIGNALS_TO_ANALYZE]
    skipped = needs_extraction[MAX_SIGNALS_TO_ANALYZE:]

    total_batches = (len(to_analyze) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"[Analyzer] Pass 1: Extracting deals from {len(to_analyze)} signals in {total_batches} batches "
          f"(+ {len(pre_structured)} pre-structured EDGAR filings, {len(skipped)} over cap)")

    # Pass 1: Batch extraction
    analyzed = []
    batch_num = 0
    for i in range(0, len(to_analyze), BATCH_SIZE):
        if DAILY_LIMIT_HIT:
            print(f"  [Analyzer] Daily limit hit after {batch_num} batches — using what we have.")
            analyzed.extend(to_analyze[i:])
            break
        batch = to_analyze[i : i + BATCH_SIZE]
        batch_num += 1
        extracted = extract_batch(batch, batch_num, total_batches)
        analyzed.extend(extracted)
        time.sleep(2)

    # Pre-structured signals (EDGAR) skip extraction entirely — fold them in
    analyzed = analyzed + pre_structured
    all_signals = analyzed + skipped

    # Pass 2: Filter to early-stage
    early_signals = filter_early_stage(analyzed)
    print(f"[Analyzer] Filtered to {len(early_signals)} early-stage signals (from {len(analyzed)} analyzed)")

    # Tag each signal so the email layer can show only early-stage deals,
    # while archives still have the full set.
    early_ids = {id(s) for s in early_signals}
    for s in all_signals:
        s["is_early_stage"] = id(s) in early_ids

    # Pass 3: Cluster themes — ALWAYS attempt if we have signals
    # Reset rate limit flag so clustering gets a fresh shot.
    # Extraction may have burned through per-minute limits, but the
    # 2-second sleep between batches + time to filter usually means
    # the per-minute window has reset by now.
    theme_analysis = {"themes": [], "biggest_surprise": "N/A", "prediction": "N/A", "sectors_cooling": "N/A", "weak_signals": "N/A"}

    if early_signals:
        DAILY_LIMIT_HIT = False  # Reset — give clustering one shot
        print(f"[Analyzer] Pass 2: Clustering {len(early_signals)} deals into themes...")
        print(f"  (Rate limit flag reset — attempting clustering with {len(early_signals)} extracted signals)")
        time.sleep(5)  # Extra breathing room before the big clustering call
        theme_analysis = cluster_themes(early_signals)

        themes = theme_analysis.get("themes", [])
        if themes:
            save_current_themes(theme_analysis)
            print(f"[Analyzer] Found {len(themes)} emerging themes.")
        else:
            print("[Analyzer] Clustering returned no themes (may still be rate limited).")
    else:
        print("[Analyzer] No early-stage signals to cluster.")

    return all_signals, theme_analysis


if __name__ == "__main__":
    test_signals = [
        {"title": "AI code review startup raises $5M seed", "description": "Codebase AI raises seed for automated code review", "source": "techcrunch"},
        {"title": "Defense AI startup emerges from stealth", "description": "Former Pentagon engineers launch autonomous systems company", "source": "crunchbase"},
    ]
    enriched, themes = run(test_signals)
    print(json.dumps(themes, indent=2))
