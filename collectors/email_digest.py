"""
email_digest.py
---------------
Builds and sends a weekly HTML email digest with:
1. Emerging theme clusters (the main insight)
2. Weak signals to watch
3. Top deals of the week
4. Trend prediction / contrarian takes
5. Source breakdown

Sent via Gmail SMTP — no third-party email service needed.
"""

import os
import smtplib
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone

EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", EMAIL_FROM)
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")

SIGNAL_STRENGTH_COLORS = {
    "strong": "#1a7f37",
    "moderate": "#bf8700",
    "emerging": "#0969da",
}

MOMENTUM_LABELS = {
    "accelerating": "🔥 Accelerating",
    "steady": "→ Steady",
    "new_this_week": "🆕 New this week",
}


def build_theme_card(theme: dict) -> str:
    """Build HTML for a single theme card."""
    name = theme.get("theme_name", "Unknown Theme")
    strength = theme.get("signal_strength", "emerging")
    color = SIGNAL_STRENGTH_COLORS.get(strength, "#666")
    count = theme.get("deal_count", 0)
    examples = theme.get("example_companies", [])
    why_now = theme.get("why_now", "")
    contrarian = theme.get("contrarian_angle", "")
    momentum = theme.get("momentum", "")

    examples_html = ", ".join(examples[:5]) if examples else "—"
    momentum_html = MOMENTUM_LABELS.get(momentum, "")

    return f"""
    <div style="background:#fff;border:1px solid #e1e4e8;border-radius:8px;
                padding:20px;margin-bottom:14px;border-left:4px solid {color};">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap;">
        <span style="background:{color};color:#fff;font-weight:600;font-size:11px;
                     padding:3px 10px;border-radius:12px;text-transform:uppercase;
                     letter-spacing:0.5px;">{strength}</span>
        <span style="font-size:16px;font-weight:700;color:#24292f;">{name}</span>
        <span style="font-size:12px;color:#57606a;margin-left:auto;">{count} deal{"s" if count != 1 else ""}</span>
      </div>
      {"<div style='font-size:11px;color:#57606a;margin-bottom:8px;'>"+momentum_html+"</div>" if momentum_html else ""}
      <div style="font-size:13px;color:#57606a;margin-bottom:6px;">
        <strong>Companies:</strong> {examples_html}
      </div>
      <div style="font-size:14px;color:#24292f;margin-bottom:8px;">
        <strong>Why now:</strong> {why_now}
      </div>
      {"<div style='font-size:13px;color:#0969da;font-style:italic;padding:8px 12px;background:#f0f7ff;border-radius:4px;'>Contrarian: "+contrarian+"</div>" if contrarian else ""}
    </div>
    """


def build_deal_row(signal: dict) -> str:
    """Build HTML for a single deal in the table."""
    company = signal.get("company_name") or signal.get("title", "Unknown")[:40]
    sector = signal.get("sector", "—")
    amount = signal.get("amount", "—")
    round_type = signal.get("round_type", "—")
    url = signal.get("url", "#")
    thesis = signal.get("thesis", "")[:120]
    source = signal.get("source", "")

    # Source badge — keep it short but don't cut mid-word
    source_clean = source.replace("rss_", "").replace("_", " ").title()
    if source == "edgar_form_d":
        source_clean = "SEC Form D"
    elif source == "twitter":
        author = signal.get("author", "")
        source_clean = f"Twitter {author}" if author else "Twitter"
    source_short = source_clean

    return f"""
    <tr style="border-bottom:1px solid #e1e4e8;">
      <td style="padding:10px 8px;font-size:13px;">
        <a href="{url}" style="color:#0969da;text-decoration:none;font-weight:600;">{company}</a>
        {"<br><span style='color:#57606a;font-size:12px;'>"+thesis+"</span>" if thesis else ""}
      </td>
      <td style="padding:10px 8px;font-size:13px;color:#57606a;">{sector}</td>
      <td style="padding:10px 8px;font-size:13px;color:#57606a;">{round_type}</td>
      <td style="padding:10px 8px;font-size:13px;color:#24292f;font-weight:600;">{amount}</td>
      <td style="padding:10px 8px;font-size:11px;color:#8b949e;">{source_short}</td>
    </tr>
    """


def build_html(signals: list[dict], theme_analysis: dict, run_date: str) -> str:
    """Build the full HTML email."""
    themes = theme_analysis.get("themes", [])
    surprise = theme_analysis.get("biggest_surprise", "")
    prediction = theme_analysis.get("prediction", "")
    cooling = theme_analysis.get("sectors_cooling", "")
    weak_signals = theme_analysis.get("weak_signals", "")

    # Source breakdown
    source_counts = {}
    for s in signals:
        src = s.get("feed_name") or s.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
    source_summary = " · ".join(f"{v} {k}" for k, v in sorted(source_counts.items(), key=lambda x: -x[1])[:8])

    # Count by type
    deal_count = sum(1 for s in signals if s.get("article_type") == "deal")
    edgar_count = sum(1 for s in signals if s.get("source") == "edgar_form_d")

    # Theme cards
    themes_html = ""
    for t in themes:
        themes_html += build_theme_card(t)

    if not themes_html:
        themes_html = "<p style='color:#57606a;text-align:center;padding:20px;'>No clear themes detected this week.</p>"

    # Deal table — show ONLY early-stage deals with known company names,
    # sorted by signal quality:
    #   1. Companies named in this week's themes (the LLM thought they mattered)
    #   2. SEC Form D filings (freshest legal signal)
    #   3. Deals with a known dollar amount
    #   4. Everything else
    theme_companies = set()
    for t in themes:
        for c in t.get("example_companies", []):
            theme_companies.add(c.lower().strip())

    candidates = [
        s for s in signals
        if s.get("company_name")
        and s.get("company_name") != "unknown"
        and s.get("is_early_stage", True)
    ]

    def rank(s):
        name = (s.get("company_name") or "").lower().strip()
        in_theme = name in theme_companies
        is_edgar = s.get("source") == "edgar_form_d"
        has_amount = bool(s.get("amount") and s.get("amount") != "unknown")
        # Lower tuple sorts first
        return (
            0 if in_theme else 1,
            0 if is_edgar else 1,
            0 if has_amount else 1,
        )

    known_deals = sorted(candidates, key=rank)[:30]
    deals_html = ""
    for d in known_deals:
        deals_html += build_deal_row(d)

    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                 background:#f6f8fa;margin:0;padding:20px;">
      <div style="max-width:720px;margin:0 auto;">

        <!-- Header -->
        <div style="background:linear-gradient(135deg, #24292f 0%, #0d1117 100%);color:#fff;
                    padding:28px 30px;border-radius:8px 8px 0 0;">
          <div style="font-size:22px;font-weight:700;">VC Trend Intelligence</div>
          <div style="font-size:14px;color:#8b949e;margin-top:6px;">
            Catching what's next — before it's consensus
          </div>
          <div style="font-size:12px;color:#6e7681;margin-top:8px;">
            Week of {run_date} · {len(signals)} signals · {deal_count} deals · {edgar_count} Form D filings
          </div>
        </div>

        <!-- Summary bar -->
        <div style="background:#fff;border:1px solid #e1e4e8;border-top:none;
                    padding:14px 30px;margin-bottom:24px;border-radius:0 0 8px 8px;">
          <div style="font-size:12px;color:#57606a;">{source_summary}</div>
        </div>

        <!-- 3-Month Prediction -->
        {"<div style='background:#ddf4ff;border:1px solid #54aeff;border-radius:8px;padding:18px 24px;margin-bottom:24px;'><div style=\"font-size:12px;font-weight:700;color:#0969da;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;\">3-6 Month Prediction</div><div style=\"font-size:15px;color:#24292f;line-height:1.5;\">"+prediction+"</div></div>" if prediction and prediction != "N/A" else ""}

        <!-- Emerging Themes -->
        <div style="margin-bottom:24px;">
          <div style="font-size:18px;font-weight:700;color:#24292f;margin-bottom:14px;
                      padding-bottom:8px;border-bottom:2px solid #e1e4e8;">
            Emerging Themes <span style="font-size:13px;font-weight:400;color:#57606a;">(ordered by how far ahead of consensus)</span>
          </div>
          {themes_html}
        </div>

        <!-- Biggest Surprise -->
        {"<div style='background:#fff8c5;border:1px solid #d4a72c;border-radius:8px;padding:16px 24px;margin-bottom:24px;'><div style=\"font-size:12px;font-weight:700;color:#9a6700;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;\">Biggest Surprise</div><div style=\"font-size:14px;color:#24292f;line-height:1.5;\">"+surprise+"</div></div>" if surprise and surprise != "N/A" else ""}

        <!-- Weak Signals -->
        {"<div style='background:#f0f0ff;border:1px solid #818cf8;border-radius:8px;padding:16px 24px;margin-bottom:24px;'><div style=\"font-size:12px;font-weight:700;color:#5b21b6;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;\">Weak Signals to Watch</div><div style=\"font-size:14px;color:#24292f;line-height:1.5;\">"+weak_signals+"</div></div>" if weak_signals and weak_signals != "N/A" else ""}

        <!-- Cooling Sectors -->
        {"<div style='background:#ffebe9;border:1px solid #ff8182;border-radius:8px;padding:16px 24px;margin-bottom:24px;'><div style=\"font-size:12px;font-weight:700;color:#cf222e;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;\">Sectors Cooling</div><div style=\"font-size:14px;color:#24292f;line-height:1.5;\">"+cooling+"</div></div>" if cooling and cooling != "N/A" else ""}

        <!-- Top Deals Table -->
        <div style="margin-bottom:24px;">
          <div style="font-size:18px;font-weight:700;color:#24292f;margin-bottom:14px;
                      padding-bottom:8px;border-bottom:2px solid #e1e4e8;">
            This Week's Earliest-Stage Deals
          </div>
          <table style="width:100%;border-collapse:collapse;background:#fff;
                        border:1px solid #e1e4e8;border-radius:8px;">
            <thead>
              <tr style="background:#f6f8fa;border-bottom:2px solid #e1e4e8;">
                <th style="padding:10px 8px;text-align:left;font-size:12px;color:#57606a;font-weight:600;">Company</th>
                <th style="padding:10px 8px;text-align:left;font-size:12px;color:#57606a;font-weight:600;">Sector</th>
                <th style="padding:10px 8px;text-align:left;font-size:12px;color:#57606a;font-weight:600;">Round</th>
                <th style="padding:10px 8px;text-align:left;font-size:12px;color:#57606a;font-weight:600;">Amount</th>
                <th style="padding:10px 8px;text-align:left;font-size:12px;color:#57606a;font-weight:600;">Source</th>
              </tr>
            </thead>
            <tbody>
              {deals_html if deals_html else "<tr><td colspan='5' style='padding:20px;text-align:center;color:#57606a;'>No deals with identified companies this week.</td></tr>"}
            </tbody>
          </table>
        </div>

        <!-- Footer -->
        <div style="text-align:center;font-size:12px;color:#57606a;margin-top:24px;
                    padding:16px;border-top:1px solid #e1e4e8;">
          VC Trend Intelligence v2 · Powered by Groq + Llama 4 · $0/month<br>
          <span style="font-size:11px;color:#8b949e;">Sources: TechCrunch, Crunchbase News, SEC EDGAR, Nitter, StrictlyVC, Newcomer + more</span>
        </div>
      </div>
    </body>
    </html>
    """
    return html


def build_plaintext(signals: list[dict], theme_analysis: dict) -> str:
    """Plain text fallback."""
    themes = theme_analysis.get("themes", [])
    lines = [f"VC Trend Intelligence — {len(themes)} themes detected\n"]

    if theme_analysis.get("prediction") and theme_analysis["prediction"] != "N/A":
        lines.append(f"PREDICTION: {theme_analysis['prediction']}\n")

    for t in themes:
        lines.append(f"[{t.get('signal_strength','?').upper()}] {t.get('theme_name','')}")
        lines.append(f"  {t.get('deal_count',0)} deals — {', '.join(t.get('example_companies',[]))}")
        lines.append(f"  Why now: {t.get('why_now','')}")
        if t.get("contrarian_angle"):
            lines.append(f"  Contrarian: {t.get('contrarian_angle','')}")
        lines.append("")

    if theme_analysis.get("weak_signals") and theme_analysis["weak_signals"] != "N/A":
        lines.append(f"WEAK SIGNALS: {theme_analysis['weak_signals']}\n")

    return "\n".join(lines)


def send(signals: list[dict], theme_analysis: dict):
    """Send the weekly digest email."""
    if not EMAIL_FROM or not EMAIL_APP_PASSWORD:
        print("[Email] EMAIL_FROM or EMAIL_APP_PASSWORD not set — skipping.")
        return

    run_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
    themes = theme_analysis.get("themes", [])
    subject = f"VC Trends: {len(themes)} emerging themes — Week of {run_date}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    msg.attach(MIMEText(build_plaintext(signals, theme_analysis), "plain"))
    msg.attach(MIMEText(build_html(signals, theme_analysis, run_date), "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        print(f"[Email] Sent to {EMAIL_TO} — {len(themes)} themes, {len(signals)} signals")
    except Exception as e:
        print(f"[Email] Error sending: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    # Test with dummy data
    test_signals = [{"company_name": "TestCo", "sector": "AI", "amount": "$5M", "round_type": "seed", "url": "#", "thesis": "test", "source": "test"}]
    test_themes = {
        "themes": [{"theme_name": "Test Theme", "signal_strength": "strong", "deal_count": 3,
                     "example_companies": ["A", "B"], "why_now": "Testing", "contrarian_angle": "Test angle",
                     "momentum": "new_this_week"}],
        "prediction": "Test prediction",
        "biggest_surprise": "Test surprise",
        "sectors_cooling": "Test cooling",
        "weak_signals": "One interesting pattern",
    }
    send(test_signals, test_themes)
