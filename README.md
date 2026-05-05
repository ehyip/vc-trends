# VC Trend Intelligence Pipeline v2.2

Spots emerging startup themes **before they become VC consensus** by analyzing the earliest-stage deals across news, newsletters, Crunchbase, SEC EDGAR, Twitter/X, Product Hunt, and GitHub Trending every week.

Clusters pre-seed and seed deals into emerging thesis areas using Groq + Llama 4, emails you a weekly intelligence brief, and publishes a browsable archive at GitHub Pages.

**Total cost: $0/month.**

---

## What's New in v2.2

- **Hard-walled early-stage filter** — Anthropic, Stripe, DoorDash, etc. can no longer leak into the digest as "deals." Drops public/mega-cap companies, acquisitions, IPOs, valuations >$50M, and any explicit Series B+
- **EDGAR Form D filings preserved** — skip the LLM extraction step (which used to nuke their company names with "unknown") and prioritize them in the deal table sort
- **Stronger clustering prompt** — explicit blocklist of household names, requires ≥2 distinct companies per theme (kills 1-deal hallucinations)
- **Structured week-over-week diff** — prior themes feed in with deal counts + example companies so the model can classify accelerating / steady / fading / dead instead of guessing from a name
- **Cross-source dedup** — same deal appearing in TechCrunch + Crunchbase + Twitter now collapses to one entry, keeping the version with the richest extraction
- **New sources**: Product Hunt RSS, GitHub Trending (weekly, multi-language)
- **Robustness**: shared `utils.py` (single `strip_html` / `parse_date` / `http_get` with retry+backoff), Nitter instance auto-failover, EDGAR 403 short-circuit
- **Dashboard archive** — every weekly run is committed to `docs/` and published to GitHub Pages: per-week HTML page + index of all weeks + machine-readable `data.json`
- **Persisted dedup state** — GitHub Actions now commits `output/seen_urls.json` and `output/previous_themes.json` back to the repo so dedup actually persists across runs

## What's New in v2

- **SEC EDGAR Form D Monitor** — catches funding BEFORE press coverage (companies must file within 15 days of raising)
- **Expanded RSS feeds** — 24 feeds including TechCrunch verticals (AI, Biotech, Climate, Fintech, Robotics, Space), more VC newsletters
- **Crunchbase tag feeds** — separate seed, pre-seed, and AI-specific feeds
- **Week-over-week comparison** — detects which themes are accelerating vs. new
- **Early-stage filter** — post-LLM filter removes Series B+ and >$15M deals
- **Weak signals section** — flags 1-2 deal patterns that could be significant
- **Better rate limit handling** — graceful stop on Groq daily limits, sends partial results
- **Fixed fallback model** — uses `llama-3.3-70b-versatile` instead of discontinued `llama3-8b-8192`

---

## How It Works

```
RSS Feeds (24)  ──┐
Crunchbase (5)  ──┤
Twitter/X (16)  ──┼──→ Collect ──→ Dedup ──→ LLM Extract ──→ Filter ──→ Cluster ──→ Email
SEC EDGAR (16)  ──┘     signals     by URL    deal details   early-     themes     weekly
                                                             stage                  digest
```

1. **Collect** — pulls from 24 RSS feeds, 5 Crunchbase feeds, 16 VC Twitter accounts, and 16 EDGAR search queries
2. **Dedup** — removes URLs seen in previous runs
3. **Extract** — LLM extracts company name, sector, thesis, round type, investors from each signal
4. **Filter** — removes Series B+ and >$15M deals (keeps only earliest-stage)
5. **Cluster** — LLM analyzes all deals to identify 5-8 emerging themes, compares with last week
6. **Email** — sends formatted weekly digest with themes, predictions, weak signals, and deal table

---

## Sources

| Collector | Sources | Count | Cost |
|---|---|---|---|
| `rss_collector.py` | TechCrunch (9 verticals), VentureBeat, Crunchbase News, StrictlyVC, Newcomer, The Generalist, Tomasz Tunguz, Lenny's Newsletter, HN, Product Hunt RSS, YC Blog, AVC, Hunter Walk, First Round Review | 22 feeds | Free |
| `crunchbase_collector.py` | Crunchbase News main + seed/pre-seed/AI tag feeds | 4 feeds | Free |
| `twitter_collector.py` | 16 tracked VC/founder accounts via Nitter RSS (with instance failover) | 16 accounts | Free |
| `edgar_collector.py` | SEC EDGAR Form D search (AI, SaaS, biotech, climate, etc.) | 16 queries | Free |
| `producthunt_collector.py` | Product Hunt daily launches via RSS | 1 feed | Free |
| `github_collector.py` | GitHub Trending (all + Python + TypeScript + Rust, weekly) | 4 feeds | Free |
| `trend_analyzer.py` | Groq + Llama 4 Scout (deal extraction + theme clustering) | — | Free |
| `email_digest.py` | Gmail SMTP | — | Free |
| `dashboard_builder.py` | Static HTML archive in `docs/` for GitHub Pages | — | Free |

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/vc-trends.git
cd vc-trends
pip install -r requirements.txt
```

### 2. Set environment variables

```bash
export GROQ_API_KEY=gsk_...               # https://console.groq.com (free)
export EMAIL_FROM=you@gmail.com
export EMAIL_TO=you@gmail.com
export EMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"  # Gmail App Password
```

### 3. Run locally

```bash
python run_trends.py                          # Full run
python run_trends.py --source rss             # Only RSS feeds
python run_trends.py --source edgar           # Only SEC EDGAR
python run_trends.py --source producthunt     # Only Product Hunt
python run_trends.py --source github          # Only GitHub Trending
python run_trends.py --dry-run                # No email sent
python run_trends.py --no-analyze             # Skip LLM (just collect)
```

---

## GitHub Actions Setup

Uses 4 secrets:

1. Push to a new GitHub repo (private is fine)
2. Add secrets: `GROQ_API_KEY`, `EMAIL_FROM`, `EMAIL_TO`, `EMAIL_APP_PASSWORD`
3. Enable Actions — runs every Monday at 10am UTC (6am ET)
4. Enable GitHub Pages — Settings → Pages → Source: GitHub Actions
5. Grant the workflow `contents: write` (already declared in `weekly_trends.yml`) so it can commit dedup state and dashboard back to the repo

After the first successful run, the dashboard will be live at `https://<your-username>.github.io/<repo-name>/`.

---

## Email Output

The weekly digest includes:

- **3-6 Month Prediction** — where the LLM thinks seed investment is heading
- **Emerging Themes** — 5-8 clusters ranked by how far ahead of consensus, with example companies, "why now" reasoning, contrarian angles, and momentum indicators
- **Biggest Surprise** — the most unexpected pattern
- **Weak Signals** — patterns in only 1-2 deals that could become significant
- **Sectors Cooling** — areas losing early-stage momentum
- **Deal Table** — all extracted deals with company, sector, round type, amount, and source

---

## Customization

### Add/remove RSS feeds
Edit `FEEDS` dict in `collectors/rss_collector.py`.

### Add/remove Twitter accounts to track
Edit `TRACKED_ACCOUNTS` list in `collectors/twitter_collector.py`.

### Add/remove EDGAR search queries
Edit `SEARCH_QUERIES` list in `collectors/edgar_collector.py`.

### Change the lookback window
Edit `DAYS_BACK` in each collector (default: 7 days).

### Change email frequency
Edit the cron in `.github/workflows/weekly_trends.yml`. Examples:
- `0 10 * * 1` = Monday 10am UTC (weekly)
- `0 10 * * 1,4` = Monday + Thursday (twice weekly)
- `0 10 * * *` = Every day

---

## Architecture

```
vc-trends/
├── run_trends.py                   # Main orchestrator
├── requirements.txt
├── README.md
├── collectors/
│   ├── __init__.py
│   ├── utils.py                    # Shared HTTP / RSS / date helpers
│   ├── rss_collector.py            # 22 RSS feeds (passthrough + filtered)
│   ├── crunchbase_collector.py     # 4 Crunchbase News feeds
│   ├── twitter_collector.py        # 16 VC accounts via Nitter (with failover)
│   ├── edgar_collector.py          # SEC EDGAR Form D monitor (16 queries)
│   ├── producthunt_collector.py    # Product Hunt daily launches
│   ├── github_collector.py         # GitHub Trending (4 language filters)
│   ├── trend_analyzer.py           # Groq/Llama 4 extraction + clustering
│   ├── email_digest.py             # HTML email builder + sender
│   └── dashboard_builder.py        # Static archive site under docs/
├── output/                         # Persisted across runs by GitHub Actions
│   ├── latest_run.json             #   Latest results
│   ├── seen_urls.json              #   Dedup state
│   └── previous_themes.json        #   Last week's themes (for comparison)
├── docs/                           # Auto-published to GitHub Pages
│   ├── index.html                  #   Chronological archive index
│   ├── data.json                   #   Machine-readable archive of all runs
│   └── weeks/
│       └── YYYY-MM-DD.html         #   Per-week digest
└── .github/
    └── workflows/
        └── weekly_trends.yml       # GitHub Actions cron + Pages deploy
```

---

## Cost

| Component | Cost |
|---|---|
| RSS feeds (24) | Free |
| Crunchbase News RSS (5) | Free |
| Twitter via Nitter RSS (16) | Free |
| SEC EDGAR EFTS API (16 queries) | Free |
| Groq + Llama 4 | Free (14,400 req/day) |
| Gmail SMTP | Free |
| GitHub Actions | Free |
| **Total** | **$0/month** |
