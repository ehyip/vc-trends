"""
run_trends.py
-------------
Main orchestrator for the VC Trend Intelligence pipeline v2.

Usage:
    python run_trends.py                      # Run everything
    python run_trends.py --source rss         # Only RSS feeds
    python run_trends.py --source crunchbase  # Only Crunchbase
    python run_trends.py --source twitter     # Only Twitter/X
    python run_trends.py --source edgar       # Only SEC EDGAR Form D
    python run_trends.py --no-analyze         # Skip LLM analysis
    python run_trends.py --dry-run            # No email sent

Designed to run weekly on Monday via GitHub Actions.
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "collectors"))

from collectors import rss_collector, crunchbase_collector, twitter_collector
from collectors import edgar_collector, trend_analyzer, email_digest
from collectors import producthunt_collector, github_collector
from collectors import dashboard_builder


def load_previous_urls(path: str) -> set:
    if not os.path.exists(path):
        return set()
    try:
        with open(path) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen_urls(path: str, signals: list[dict]):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    urls = list({s.get("url", "") for s in signals if s.get("url")})
    with open(path, "w") as f:
        json.dump(urls, f)


def main():
    parser = argparse.ArgumentParser(description="VC Trend Intelligence Pipeline v2")
    parser.add_argument(
        "--source",
        choices=["rss", "crunchbase", "twitter", "edgar", "producthunt", "github", "all"],
        default="all",
    )
    parser.add_argument("--no-analyze", action="store_true", help="Skip LLM analysis")
    parser.add_argument("--dry-run", action="store_true", help="Print results only, no email")
    args = parser.parse_args()

    run_time = datetime.now(timezone.utc).isoformat()
    print(f"\n{'='*60}")
    print(f"  VC Trend Intelligence Pipeline v2")
    print(f"  Run started: {run_time}")
    print(f"{'='*60}\n")

    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    seen_path = str(output_dir / "seen_urls.json")
    seen_urls = load_previous_urls(seen_path)

    # ── Step 1: Collect signals ──────────────────────────────────────────────
    all_signals = []

    if args.source in ("rss", "all"):
        try:
            signals = rss_collector.run()
            all_signals.extend(signals)
            print()
        except Exception as e:
            print(f"  [!] RSS collector failed: {e}")
            traceback.print_exc()
            print()

    if args.source in ("crunchbase", "all"):
        try:
            signals = crunchbase_collector.run()
            all_signals.extend(signals)
            print()
        except Exception as e:
            print(f"  [!] Crunchbase collector failed: {e}")
            traceback.print_exc()
            print()

    if args.source in ("twitter", "all"):
        try:
            signals = twitter_collector.run()
            all_signals.extend(signals)
            print()
        except Exception as e:
            print(f"  [!] Twitter collector failed: {e}")
            traceback.print_exc()
            print()

    if args.source in ("edgar", "all"):
        try:
            signals = edgar_collector.run()
            all_signals.extend(signals)
            print()
        except Exception as e:
            print(f"  [!] EDGAR collector failed: {e}")
            traceback.print_exc()
            print()

    if args.source in ("producthunt", "all"):
        try:
            signals = producthunt_collector.run()
            all_signals.extend(signals)
            print()
        except Exception as e:
            print(f"  [!] Product Hunt collector failed: {e}")
            traceback.print_exc()
            print()

    if args.source in ("github", "all"):
        try:
            signals = github_collector.run()
            all_signals.extend(signals)
            print()
        except Exception as e:
            print(f"  [!] GitHub collector failed: {e}")
            traceback.print_exc()
            print()

    print(f"Total signals collected: {len(all_signals)}")

    # ── Step 2: Dedup ────────────────────────────────────────────────────────
    new_signals = [s for s in all_signals if s.get("url", "") not in seen_urls]
    print(f"New signals (not seen before): {len(new_signals)}")

    if not new_signals:
        print("Nothing new this week. Exiting.")
        return

    # ── Step 3: LLM Analysis + Theme Clustering ─────────────────────────────
    theme_analysis = {
        "themes": [], "prediction": "N/A", "biggest_surprise": "N/A",
        "sectors_cooling": "N/A", "weak_signals": "N/A"
    }

    if not args.no_analyze:
        try:
            new_signals, theme_analysis = trend_analyzer.run(new_signals)
        except Exception as e:
            print(f"  [!] Analyzer failed: {e}")
            traceback.print_exc()
    else:
        print("[Analyzer] Skipped (--no-analyze flag).")

    # ── Step 3b: Dedup by normalized company name ────────────────────────────
    # Same deal often appears across TechCrunch verticals + Crunchbase + Twitter.
    # Keep the entry with the most extracted info (longest thesis).
    from collectors.utils import normalize_company_name
    by_company: dict[str, dict] = {}
    no_company = []
    for s in new_signals:
        name = normalize_company_name(s.get("company_name", ""))
        if not name or name == "unknown":
            no_company.append(s)
            continue
        existing = by_company.get(name)
        if existing is None or len(s.get("thesis", "")) > len(existing.get("thesis", "")):
            by_company[name] = s
    pre = len(new_signals)
    new_signals = list(by_company.values()) + no_company
    if pre != len(new_signals):
        print(f"[Dedup] Collapsed {pre - len(new_signals)} duplicate-company signals.")

    # ── Step 4: Print summary ────────────────────────────────────────────────
    themes = theme_analysis.get("themes", [])
    print(f"\n{'─'*60}")
    print(f"  EMERGING THEMES ({len(themes)} detected)")
    print(f"{'─'*60}")
    for i, t in enumerate(themes):
        strength = t.get("signal_strength", "?")
        name = t.get("theme_name", "?")
        count = t.get("deal_count", 0)
        momentum = t.get("momentum", "")
        print(f"  {i+1}. [{strength.upper()}] {name} ({count} deals) {momentum}")
        examples = t.get("example_companies", [])
        if examples:
            print(f"     Companies: {', '.join(examples[:4])}")
        if t.get("why_now"):
            print(f"     Why now: {t['why_now'][:120]}")
        if t.get("contrarian_angle"):
            print(f"     Contrarian: {t['contrarian_angle'][:120]}")
        print()

    if theme_analysis.get("prediction") and theme_analysis["prediction"] != "N/A":
        print(f"  PREDICTION: {theme_analysis['prediction']}")
    if theme_analysis.get("biggest_surprise") and theme_analysis["biggest_surprise"] != "N/A":
        print(f"  SURPRISE: {theme_analysis['biggest_surprise']}")
    if theme_analysis.get("weak_signals") and theme_analysis["weak_signals"] != "N/A":
        print(f"  WEAK SIGNALS: {theme_analysis['weak_signals']}")
    print()

    # ── Step 5: Save results ─────────────────────────────────────────────────
    results_path = str(output_dir / "latest_run.json")
    with open(results_path, "w") as f:
        json.dump({
            "run_time": run_time,
            "signal_count": len(new_signals),
            "themes": theme_analysis,
            "signals": new_signals,
        }, f, indent=2)
    print(f"Results saved to {results_path}")

    # ── Step 6: Send email ───────────────────────────────────────────────────
    if not args.dry_run:
        try:
            email_digest.send(new_signals, theme_analysis)
        except Exception as e:
            print(f"  [!] Email failed: {e}")
            traceback.print_exc()
        save_seen_urls(seen_path, all_signals)
    else:
        print("[Dry run] Skipping email.")

    # ── Step 7: Update dashboard archive ─────────────────────────────────────
    try:
        dashboard_builder.update(new_signals, theme_analysis, run_time)
    except Exception as e:
        print(f"  [!] Dashboard update failed: {e}")
        traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"  Pipeline complete. {len(new_signals)} signals, {len(themes)} themes.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
