"""
dashboard_builder.py
--------------------
Builds a static HTML archive site under `docs/` so every weekly run is
browsable forever via GitHub Pages.

Layout:
  docs/
    index.html              ← chronological list of all weeks
    data.json               ← machine-readable archive (all runs)
    weeks/
      2026-05-04.html       ← per-week digest (same content as the email)
      2026-04-27.html
      ...

Designed to be re-run idempotently from `run_trends.py`.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from collectors.email_digest import build_html


REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / "docs"
WEEKS_DIR = DOCS_DIR / "weeks"
DATA_FILE = DOCS_DIR / "data.json"
INDEX_FILE = DOCS_DIR / "index.html"


def _load_archive() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_archive(archive: list[dict]):
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(archive, f, indent=2)


def _week_filename(run_time_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(run_time_iso.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d") + ".html"


def _build_index(archive: list[dict]) -> str:
    """Build the index page listing every archived week."""
    rows = []
    for entry in sorted(archive, key=lambda e: e.get("run_time", ""), reverse=True):
        run_time = entry.get("run_time", "")
        try:
            dt = datetime.fromisoformat(run_time.replace("Z", "+00:00"))
            date_str = dt.strftime("%B %d, %Y")
        except ValueError:
            date_str = run_time

        themes = entry.get("themes", [])
        signal_count = entry.get("signal_count", 0)
        theme_pills = " ".join(
            f"<span style='display:inline-block;background:#eef;color:#225;padding:2px 8px;"
            f"border-radius:10px;font-size:11px;margin:2px 2px 2px 0;'>{t.get('theme_name', '?')[:40]}</span>"
            for t in themes[:6]
        )
        prediction = entry.get("prediction", "")[:200]

        rows.append(f"""
        <li style="border-bottom:1px solid #e1e4e8;padding:18px 0;">
          <a href="weeks/{entry.get('filename', '')}"
             style="font-size:18px;font-weight:600;color:#0969da;text-decoration:none;">
            Week of {date_str}
          </a>
          <div style="color:#57606a;font-size:12px;margin:4px 0 8px;">
            {signal_count} signals · {len(themes)} themes
          </div>
          <div>{theme_pills}</div>
          {f"<div style='font-size:13px;color:#24292f;margin-top:8px;font-style:italic;'>{prediction}</div>" if prediction else ""}
        </li>
        """)

    rows_html = "\n".join(rows) if rows else "<li style='padding:30px;text-align:center;color:#57606a;'>No archived runs yet.</li>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VC Trend Intelligence — Archive</title>
  <style>
    body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
           background:#f6f8fa;margin:0;padding:30px 20px;color:#24292f; }}
    .container {{ max-width:780px;margin:0 auto; }}
    h1 {{ font-size:28px;margin:0 0 6px; }}
    .sub {{ color:#57606a;font-size:14px;margin-bottom:24px; }}
    ul {{ list-style:none;padding:0;background:#fff;border:1px solid #e1e4e8;border-radius:8px;padding:0 24px; }}
    a:hover {{ text-decoration:underline !important; }}
    footer {{ text-align:center;color:#8b949e;font-size:12px;margin-top:30px; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>VC Trend Intelligence</h1>
    <div class="sub">Catching what's next — before it's consensus. Weekly archive.</div>
    <ul>{rows_html}</ul>
    <footer>
      Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · Powered by Groq + Llama 4
    </footer>
  </div>
</body>
</html>
"""


def write_week(signals: list[dict], theme_analysis: dict, run_time_iso: str) -> str:
    """Render a single week's HTML page (same content as the email).

    Returns the relative filename written under docs/weeks/.
    """
    WEEKS_DIR.mkdir(parents=True, exist_ok=True)
    filename = _week_filename(run_time_iso)
    try:
        dt = datetime.fromisoformat(run_time_iso.replace("Z", "+00:00"))
        date_label = dt.strftime("%B %d, %Y")
    except ValueError:
        date_label = run_time_iso

    body = build_html(signals, theme_analysis, date_label)
    page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VC Trends — Week of {date_label}</title>
</head><body>
<div style="max-width:780px;margin:0 auto;padding:12px 20px;">
  <a href="../index.html" style="font-size:13px;color:#0969da;text-decoration:none;">← All weeks</a>
</div>
{body}
</body></html>
"""
    (WEEKS_DIR / filename).write_text(page)
    return filename


def update(signals: list[dict], theme_analysis: dict, run_time_iso: str):
    """Render this week's page, append to data.json, and rebuild the index."""
    filename = write_week(signals, theme_analysis, run_time_iso)

    archive = _load_archive()
    # Remove any prior entry for the same date (idempotent re-runs)
    archive = [e for e in archive if e.get("filename") != filename]

    archive.append({
        "run_time": run_time_iso,
        "filename": filename,
        "signal_count": len(signals),
        "themes": [
            {
                "theme_name": t.get("theme_name", ""),
                "signal_strength": t.get("signal_strength", ""),
                "deal_count": t.get("deal_count", 0),
                "example_companies": t.get("example_companies", []),
                "momentum": t.get("momentum", ""),
            }
            for t in theme_analysis.get("themes", [])
        ],
        "prediction": theme_analysis.get("prediction", ""),
        "biggest_surprise": theme_analysis.get("biggest_surprise", ""),
    })
    _save_archive(archive)

    INDEX_FILE.write_text(_build_index(archive))
    print(f"[Dashboard] Updated docs/weeks/{filename} + index ({len(archive)} weeks archived).")
