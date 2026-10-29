# Job Pipeline & Matcher

A modular data engineering pipeline that aggregates messy job listings from multiple sources, normalizes and deduplicates them into PostgreSQL, and scores them against a personal CV to surface relevant junior, remote, and local roles.

## Architecture
- **Ingest**: Pluggable extractors managed via a unified `SOURCES` registry with isolated per-source failure boundaries (Arbeitnow, Remotive, Himalayas, WWR, Remote OK, Jobicy, Hacker News).
- **Stage**: Raw JSON/HTML payloads preserved in `raw_job_listings` (ELT pattern) to guarantee zero data loss.
- **Normalize & Enrich**: Pydantic models clean text, truncate fields to 255 chars with warnings, extract seniority levels (`junior`, `intern`), and classify reachability.
- **Reachability & Five-Gate Eligibility Filter**: Evaluates candidate fit via strict allowlists (default-deny architecture):
  - **Gate 1 (Work Location)**: Strictly remote Worldwide/Global/APAC/Nepal or on-site/hybrid in Nepal. Automatically rejects all foreign hybrid/on-site postings (`NOT_REMOTE`) and region locks outside Nepal (`NOT_ELIGIBLE_REGION` / `REGION_LOCKED`).
  - **Gate 2 (Seniority & Degree)**: Disqualifies titles with `BLOCKED_SENIORITY` (`senior`, `lead`, `leader`, `manager`, `head`, `vp`, `director`) as `TOO_SENIOR`, and hard degree requirements or $\ge 3$ years experience as `DEGREE_OR_EXP`.
  - **Gate 3 (Clearance & Regulatory Fit)**: Blocks defense, military, ITAR, and government security clearance roles.
  - **Gate 4 (Pay & Practicality)**: Blocks unpaid/equity-only roles and US Pacific fixed-overlap requirements ($\ge 6$h).
  - **Gate 5 (Skill Fit)**: Ranks match against Python/ML, Django, React/Next.js, Flutter, and SQL stack.
- **Zero-Scraping Policy for Nepal**: Strictly respects ToS and legal prohibitions on scraping local job boards (Merojob, Kumarijob, etc.). Local listings enter exclusively through manual JSON/CSV imports via `scripts/import_manual_jobs.py` (`source = 'manual:nepal'`).
- **Deduplicate**: SHA-256 content hashing collapses identical postings cross-posted across platforms.
- **Match & Role Classification**:
  - Rule-based weighted ranking (`MatchScorer`) with skill-requirement focusing.
  - Learned title role-type classifier (`src/matching/title_classifier.py`): Char n-gram TF-IDF + LogisticRegression providing calibrated soft penalties (+12.7% recall over rigid keyword blocklists, 0.000 FPR on `good_fit`).
  - Laya neural scorer (`convaiinnovations/laya`, ModernBERT-large) with temperature calibration.
- **Output & Automation**:
  - Daily markdown digest (`FEED.md`), interactive CLI review tool, and browser dashboard (`app.py`).
  - Automated execution via `scripts/run_scheduled.py` with file locking (`data/pipeline.lock`), rotating logs, and Windows Task Scheduler / Docker runners.
- **Labeling & Training Gates**:
  - Human-labeled dataset in `laya_labels` (PostgreSQL) stamped strictly with `label_guideline_version="v2_role_fit_only"`.
  - Enforced training gates: Refuses to train rankers when $< 150$ v2 labels or $< 30$ role-fit `good_fit` positives, protecting against overfitting on tiny positive splits. Strategy documented in [`TRAINING.md`](TRAINING.md).


## ⚡ Quick Commands Cheatsheet

| Task | PowerShell Command | Note |
| :--- | :--- | :--- |
| **🌐 Web Dashboard** | `& .\.venv\Scripts\python.exe app.py` | Open **http://localhost:5000** in browser (Feed & Rejected tabs, live labeling) |
| **🚀 Generate FEED.md** | `& .\.venv\Scripts\python.exe scripts/export_feed.py` | Exports top matched jobs to `FEED.md` |
| **🔄 Run Daily Pipeline** | `& .\.venv\Scripts\python.exe scripts/run_daily.py` | Fetch → Normalize → MatchScorer → Update FEED.md |
| **⏰ Run Scheduled Pipeline** | `& .\.venv\Scripts\python.exe scripts/run_scheduled.py` | Wrapper with `pipeline.lock`, rotating log, telemetry |
| **📦 Make Labeling Batch** | `& .\.venv\Scripts\python.exe scripts/make_labeling_batch.py --batch-size 30` | 70% title-rule / 30% random, capped by company, v2 stamped |
| **🏷️ Label Audit Report** | `& .\.venv\Scripts\python.exe scripts/report_labels.py` | Full yield by source/stratum & gate progress report (Task 7.9) |
| **🔤 Train Title Classifier** | `& .\.venv\Scripts\python.exe scripts/train_title_classifier.py` | Char n-gram TF-IDF title classifier (0.872 recall, 0 FPR) |
| **🎯 Train Production Ranker** | `& .\.venv\Scripts\python.exe scripts/train_ranker.py` | Gated on >=150 v2 labels & >=30 good_fit with bootstrap CI |
| **🇳🇵 Manual Nepal Import** | `& .\.venv\Scripts\python.exe scripts/import_manual_jobs.py -f jobs.json` | Ingests user-supplied JSON/CSV (NO web scraping) |
| **📋 Interactive CLI Review** | `& .\.venv\Scripts\python.exe scripts/review_jobs.py` | Review jobs (`y/n/s/q`), saves to `data/reviewed_jobs.json` |
| **📤 Ingest Human Labels** | `& .\.venv\Scripts\python.exe scripts/ingest_labels.py data/labeling_batch_YYYYMMDD.csv` | Ingests CSV into `laya_labels` in Postgres |
| **🎯 Calibrate Laya** | `& .\.venv\Scripts\python.exe scripts/calibrate_laya.py --version v3` | Fits temperature scaling on human labels |
| **📈 Pipeline Funnel Report** | `& .\.venv\Scripts\python.exe scripts/funnel_report.py --days 7` | Source-level funnel stats (fetched → new → passed HF → scored ≥60) |
| **🧪 ATS Yield Dry-Run** | `& .\.venv\Scripts\python.exe scripts/dry_run_yield_test.py` | In-memory yield test across 10 company ATS boards (no DB writes) |

---

## 🌐 Local Web Dashboard & In-Browser Labeling

Launch the live visual web interface backed directly by your local PostgreSQL database (4,596 jobs across 8 active sources):

```powershell
& .\.venv\Scripts\python.exe app.py
```

Then open **[http://localhost:5000](http://localhost:5000)** in your browser.

- **Feed Tab**: Top passing jobs pre-ranked by title-rule score, showing MatchScorer points, tech role probability, and direct application links.
- **Rejected Tab**: Full transparency into HardFilter decisions. Filterable by failure reason (`TOO_SENIOR`, `DEGREE_OR_EXP`, `REGION_LOCKED`, `NOT_REMOTE`, `NON_ENGLISH`, `NON_TECHNICAL`) with the exact snippet that triggered disqualification.
- **Immediate Feedback Loop**: Label any job (`Good Fit`, `Maybe`, `Bad Fit`), enter a free-text fit reason, and check "Wrongly filtered" for false positives. Every label writes instantly to PostgreSQL `laya_labels` stamped `label_guideline_version="v2_role_fit_only"`.
- **Live Header**: Displays last pipeline run time, 24h new jobs, active model version, and real-time progress toward the 150/30 ranker training gate (with stale run warning if > 36 hours).


## 📊 Database CLI Commands

Check PostgreSQL status and staged row counts:
```powershell
.\.venv\Scripts\python -m src.db.connection
```

Run schema migrations:
```powershell
.\.venv\Scripts\python -m src.db.migrate
```

Run automated test suite:
```powershell
.\.venv\Scripts\pytest
```

## 📡 Ingestion Sources & Feasibility Audit (Researched Oct 14, 2026)

| Source | Official API / Feed URL | Terms / robots.txt Verdict | Location & Timezone Restrictions | Seniority Field | Rate Limits & Policies | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Himalayas** | `https://himalayas.app/jobs/api` (browse)<br>`https://himalayas.app/jobs/api/search` (search) | **Allowed** via public JSON API per [`/api`](https://himalayas.app/api). HTML screen scraping prohibited in ToS clause 30 ([`/terms`](https://himalayas.app/terms)). Fetched 2026-10-14. | `locationRestrictions` (array of countries), `timezoneRestrictions` (array of UTC offsets). | `seniority` (e.g. `Entry-level`, `Mid-level`, `Senior`). | Max 20 jobs/request via cursor pagination. 429 status on excess. Daily cached (poll max 1×/day). Visible link attribution required. | **BUILD** |
| **Merojob** | None (no public API). HTML scraping target only. | **Forbidden**: Terms §3.E ([`/terms-and-conditions/`](https://merojob.com/terms-and-conditions/)) explicitly forbids "Data scraping, automated bots, or other tools for collecting or mining personal or professional data". [`/robots.txt`](https://merojob.com/robots.txt) has `ai-train=no`. Fetched 2026-10-14. | None structured (raw HTML body text). | None structured. | N/A (scraping forbidden; zero-tolerance legal risk under Nepalese jurisdiction). | **SKIP** |
| **We Work Remotely** | `https://weworkremotely.com/categories/remote-programming-jobs.rss`<br>`https://weworkremotely.com/remote-jobs.rss` | **Allowed**: Official public RSS feed. [`/robots.txt`](https://weworkremotely.com/robots.txt) has `Allow: /`. Terms ([`/terms-and-conditions`](https://weworkremotely.com/terms-and-conditions)) permit RSS syndication consumption. Fetched 2026-10-14. | `<region>` XML tag per item (e.g. `Anywhere in the World`, `USA Only`). | In title/description text (extractable via existing enricher). | Standard RSS `<ttl>60</ttl>` (60 min cache). Poll max 1×/day with polite client delay. | **BUILD** |
| **Remote OK** | `https://remoteok.com/api` | **Allowed**: Public JSON feed with explicit inline ToS: "Please link back... and mention Remote OK as a source". [`/robots.txt`](https://remoteok.com/robots.txt) specifies `Allow: /` and `Crawl-delay: 1`. Fetched 2026-10-14. | `location` string field (e.g. `United Kingdom`, `Kansas`, or empty string `""` for worldwide). | In `position` and `tags` list. | `Crawl-delay: 1` per robots.txt. Cached via timestamp epoch. Poll max 1×/day. | **BUILD** |
| **Jobicy** | `https://jobicy.com/api/v2/remote-jobs` | **Allowed**: Official public JSON API with friendly notice in JSON response: "Please ensure Jobicy is clearly credited with a direct link to the source". [`/robots.txt`](https://jobicy.com/robots.txt) allows `/api/v2/`. Fetched 2026-10-14. | `jobGeo` string field (e.g. `Canada, Europe, USA`, `Anywhere`, `Worldwide`). | `jobLevel` (e.g. `Senior`, `Mid-Level`, `Entry-Level`). | Fair-use policy; 429 status on excess; pagination via `nextCursor`. Poll max 1×/day. | **BUILD** |
| **Hacker News ("Who is hiring")** | `https://hacker-news.firebaseio.com/v0/` (monthly thread from user `whoishiring`, e.g. item `49922569`) | **Allowed**: Official Firebase API documented in official repository ([`HackerNews/API`](https://github.com/HackerNews/API)). Fetched 2026-10-14. | Unstructured top line in comment text (pipe-separated: `Company \| Title \| Location \| Remote`). | In title/comment body text. | Docs state: "There is currently no rate limit." We apply client-side throttle of 0.2s between items and limit to top-level comments. | **BUILD** |

## Tech Stack
- Python 3.12+
- PostgreSQL 16 (via Docker Compose)
- Pydantic v2
- Psycopg 3
- Requests & BeautifulSoup4
