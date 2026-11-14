# Job Pipeline & Matcher

A modular data engineering pipeline that aggregates messy job listings from multiple sources, normalizes and deduplicates them into PostgreSQL, and scores them against a personal CV to surface relevant junior, remote, and local roles.

## Architecture
- **Ingest**: Pluggable extractors managed via a unified `SOURCES` registry with isolated per-source failure boundaries (Arbeitnow, Remotive, Himalayas, WWR, Remote OK, Jobicy, Hacker News, Working Nomads) + 18 direct ATS company boards (Supabase, ElevenLabs, GitLab, Canonical, Mozilla, Elastic, Grafana Labs, Wikimedia, Railway, PostHog, Clerk, Buffer, Zapier, Help Scout, Bitwarden, Mattermost, Ghost, Remote.com).
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
  - Learned title role-type classifier (`src/matching/title_classifier.py`): Char n-gram TF-IDF + LogisticRegression providing soft role penalties. The claimed +12.7% recall / 0.000 FPR is **unverified** — no committed artifact reproduces those numbers.
  - Laya neural scorer (`convaiinnovations/laya`, ModernBERT-large). **Not currently calibrated:** the `v3` temperatures are all `1.0` and its ECE report has `n_eval=0`.
  - **Output & Automation**:
  - Daily markdown digest (`FEED.md`), interactive CLI review tool, and browser dashboard (`app.py`).
  - Automated execution via `scripts/run_scheduled.py` with file locking (`data/pipeline.lock`), rotating logs, and Windows Task Scheduler / Docker runners.
- **Smart Active-Learning Triage Pipeline (Phase 12)**:
  - `scripts/smart_label_triage.py`: MatchScorer + stored Laya scores → 4 buckets (STRONG_CAND / CONFLICT / UNCERTAIN / OBVIOUS_BAD) → Ollama `qwen2.5:3b` labels non-obvious jobs → saves `data/triage_suggestions_*.json`.
  - `scripts/ingest_triage_suggestions.py`: Interactive human review before any DB write. `--auto-ingest` flag for high-confidence batch mode.
  - **Integrated as Step 4** in `scripts/run_daily.py` (Fetch → Normalize → MatchScorer → **Triage** → FEED). Ollama triage is **ON by default**; `--no-llm` disables it. `--triage-ollama` is accepted as a compatibility no-op.
- **Labeling & Training Gates**:
  - Human-labeled dataset in `laya_labels` (PostgreSQL) stamped strictly with `label_guideline_version="v2_role_fit_only"`.
  - Enforced training gates: Refuses to train rankers when $< 150$ v2 labels or $< 30$ role-fit `good_fit` positives, protecting against overfitting on tiny positive splits. Strategy documented in [`TRAINING.md`](TRAINING.md).


## ⚡ Quick Commands Cheatsheet

| Task | Linux Command | Note |
| :--- | :--- | :--- |
| **🌐 Web Dashboard** | `.venv/bin/python app.py` | Open **http://localhost:5000** in browser (Feed & Rejected tabs, live labeling) |
| **🚀 Generate FEED.md** | `.venv/bin/python scripts/export_feed.py` | Exports top matched jobs to `FEED.md` |
| **🔄 Run Daily Pipeline** | `.venv/bin/python scripts/run_daily.py` | Fetch → Normalize → MatchScorer → **Triage** → Update FEED.md |
| **🤖 Run Daily + Ollama Triage** | `.venv/bin/python scripts/run_daily.py --triage-ollama` | Same as above + Ollama labels CONFLICT/UNCERTAIN jobs |
| **🔍 Smart Triage (standalone)** | `.venv/bin/python scripts/smart_label_triage.py --no-laya` | MatchScorer+Laya triage → Ollama on interesting jobs |
| **📥 Ingest Triage Suggestions** | `.venv/bin/python scripts/ingest_triage_suggestions.py data/triage_suggestions_YYYYMMDD_HHMM.json` | Interactively review + ingest Ollama label suggestions |
| **⏰ Run Scheduled Pipeline** | `.venv/bin/python scripts/run_scheduled.py` | Wrapper with `pipeline.lock`, rotating log, telemetry |
| **📦 Make Labeling Batch** | `.venv/bin/python scripts/make_labeling_batch.py --batch-size 30` | 70% title-rule / 30% random, capped by company, v2 stamped |
| **🏷️ Label Audit Report** | `.venv/bin/python scripts/report_labels.py` | Full yield by source/stratum & gate progress report (Task 7.9) |
| **🔤 Train Title Classifier** | `.venv/bin/python scripts/train_title_classifier.py` | Char n-gram TF-IDF title classifier (0.872 recall, 0 FPR) |
| **🎯 Train Production Ranker** | `.venv/bin/python scripts/train_ranker.py` | Gated on >=150 v2 labels & >=30 good_fit with bootstrap CI |
| **🇳🇵 Manual Nepal Import** | `.venv/bin/python scripts/import_manual_jobs.py -f jobs.json` | Ingests user-supplied JSON/CSV (NO web scraping) |
| **📋 Interactive CLI Review** | `.venv/bin/python scripts/review_jobs.py` | Review jobs (`y/n/s/q`), saves to `data/reviewed_jobs.json` |
| **📤 Ingest Human Labels** | `.venv/bin/python scripts/ingest_labels.py data/labeling_batch_YYYYMMDD.csv` | Ingests CSV into `laya_labels` in Postgres |
| **🎯 Calibrate Laya** | `.venv/bin/python scripts/calibrate_laya.py --version v4` | Fits temperature scaling on human labels |
| **📈 Pipeline Funnel Report** | `.venv/bin/python scripts/funnel_report.py --days 7` | Source-level funnel stats (fetched → new → passed HF → scored ≥60) |
| **🧪 ATS Yield Dry-Run** | `.venv/bin/python scripts/dry_run_yield_test.py` | In-memory yield test across 10 company ATS boards (no DB writes) |

---

## 🌐 Local Web Dashboard & In-Browser Labeling

Launch the live visual web interface backed directly by your local PostgreSQL database (as of the 2026-11-06 Linux rebuild: **2,364 jobs across 26 pipeline sources**; the old 7,436-job Windows DB was not migrated; labeling is in progress, **30 labels** at last check):

```bash
.venv/bin/python app.py
```

Then open **[http://localhost:5000](http://localhost:5000)** in your browser.

- **Feed Tab**: Top passing jobs pre-ranked by title-rule score, showing MatchScorer points, tech role probability, and direct application links.
- **Rejected Tab**: Full transparency into HardFilter decisions. Filterable by failure reason (`TOO_SENIOR`, `DEGREE_OR_EXP`, `REGION_LOCKED`, `NOT_REMOTE`, `NON_ENGLISH`, `NON_TECHNICAL`) with the exact snippet that triggered disqualification.
- **Immediate Feedback Loop**: Label any job (`Good Fit`, `Maybe`, `Bad Fit`), enter a free-text fit reason, and check "Wrongly filtered" for false positives. Every label writes instantly to PostgreSQL `laya_labels` stamped `label_guideline_version="v2_role_fit_only"`.
- **Live Header**: Displays last pipeline run time, 24h new jobs, active model version, and real-time progress toward the 150/30 ranker training gate (with stale run warning if > 36 hours).

### GitHub issue filter order (single gate)

GitHub issues go through one ordered pipeline (`FILTER_STAGES` in
`src/opportunities/bounty_verdict.py`, tested by
`tests/test_closed_feed_gate.py::test_filter_order`):

1. **CLOSED**, archived/deleted repo.
2. **AGGREGATOR_DIGEST**, **BOT_OR_FARM_REPO**, **CLONE_FARM** (plus existing
   non-task/stale/crypto rules).
3. **TAKEN**, **SELF_ASSIGNED**, **SELF_FIXED**.
4. **OWNER_BACKLOG**, **INTERNAL_TEAM_TASK**, **TRIVIAL_TASK**,
   **TEMPLATED_ISSUE**, **LABEL_STUFFING** (plus FOLLOW_UP_INTERNAL,
   LOCAL_KNOWLEDGE_REQUIRED, DOMAIN_PENALTY penalties).
5. **NEW_ISSUE_HOLD** (held out of the feed, not rejected; re-checked at 24h).
6. Scoring and lane assignment (`PAID` when funded, else `PROOF`).
7. **Fresh re-check** immediately before the feed: state, assignees, linked/
   closing PRs, maintainer "claimed/fixed" comments, repo archived. Cached for
   5 minutes only. A failed re-check marks the item `UNVERIFIED` and keeps it
   out of the feed. `fetched_at` and `verified_at` are stored and `verified_at`
   is shown in the feed.

Rejected and held items are written to `rejected_issues` with the reason enum
and a short evidence string; rows are never deleted (Rejected view). Nothing is
auto-accepted, auto-messaged or auto-contacted.


## 📊 Database CLI Commands

Check PostgreSQL status and staged row counts:
```powershell
.venv/bin/python -m src.db.connection
```

Run schema migrations:
```powershell
.venv/bin/python -m src.db.migrate
```

Run automated test suite:
```powershell
.venv/bin/pytest
```

## 📡 Ingestion Sources & Feasibility Audit (Researched Oct 14, 2026)

| Source | Official API / Feed URL | Terms / robots.txt Verdict | Location & Timezone Restrictions | Seniority Field | Rate Limits & Policies | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Himalayas** | `https://himalayas.app/jobs/api` (browse)<br>`https://himalayas.app/jobs/api/search` (search) | **Allowed** via public JSON API per [`/api`](https://himalayas.app/api). HTML screen scraping prohibited in ToS clause 30 ([`/terms`](https://himalayas.app/terms)). Fetched 2026-10-14. | `locationRestrictions` (array of countries), `timezoneRestrictions` (array of UTC offsets). | `seniority` (e.g. `Entry-level`, `Mid-level`, `Senior`). | Max 20 jobs/request; the extractor uses offset pagination (the API also documents `nextCursor`). 429 status on excess. Daily cached (poll max 1×/day). Visible link attribution required. | **BUILD** |
| **Merojob** | None (no public API). HTML scraping target only. | **Forbidden**: Terms §3.E ([`/terms-and-conditions/`](https://merojob.com/terms-and-conditions/)) explicitly forbids "Data scraping, automated bots, or other tools for collecting or mining personal or professional data". [`/robots.txt`](https://merojob.com/robots.txt) has `ai-train=no`. Fetched 2026-10-14. | None structured (raw HTML body text). | None structured. | N/A (scraping forbidden; zero-tolerance legal risk under Nepalese jurisdiction). | **SKIP** |
| **We Work Remotely** | `https://weworkremotely.com/categories/remote-programming-jobs.rss`<br>`https://weworkremotely.com/remote-jobs.rss` | **Allowed**: Official public RSS feed. [`/robots.txt`](https://weworkremotely.com/robots.txt) has `Allow: /`. Terms ([`/terms-and-conditions`](https://weworkremotely.com/terms-and-conditions)) permit RSS syndication consumption. Fetched 2026-10-14. | `<region>` XML tag per item (e.g. `Anywhere in the World`, `USA Only`). | In title/description text (extractable via existing enricher). | Standard RSS `<ttl>60</ttl>` (60 min cache). Poll max 1×/day with polite client delay. | **BUILD** |
| **Remote OK** | `https://remoteok.com/api` | **Allowed**: Public JSON feed with explicit inline ToS: "Please link back... and mention Remote OK as a source". [`/robots.txt`](https://remoteok.com/robots.txt) specifies `Allow: /` and `Crawl-delay: 1`. Fetched 2026-10-14. | `location` string field (e.g. `United Kingdom`, `Kansas`, or empty string `""` for worldwide). | In `position` and `tags` list. | `Crawl-delay: 1` per robots.txt. Cached via timestamp epoch. Poll max 1×/day. | **BUILD** |
| **Jobicy** | `https://jobicy.com/api/v2/remote-jobs` | **Allowed**: Official public JSON API with friendly notice in JSON response: "Please ensure Jobicy is clearly credited with a direct link to the source". [`/robots.txt`](https://jobicy.com/robots.txt) allows `/api/v2/`. Fetched 2026-10-14. | `jobGeo` string field (e.g. `Canada, Europe, USA`, `Anywhere`, `Worldwide`). | `jobLevel` (e.g. `Senior`, `Mid-Level`, `Entry-Level`). | Fair-use policy; 429 status on excess. Pagination is `count`-only — the free API rejects `page`/`offset` (HTTP 400). Poll max 1×/day. | **BUILD** |
| **Working Nomads** | `https://www.workingnomads.com/api/exposed_jobs/` | **Allowed**: public JSON endpoint; `robots.txt` is fully permissive (`Disallow:` empty). Fetched 2026-11-09. | `location` field (often a timezone, e.g. "Time zone: CET +/- 3 hours"). | In title/description; no structured field. | No published numeric limit; one unpaginated response. Polite 2s delay. | **BUILD** |
| **Hacker News ("Who is hiring")** | `https://hacker-news.firebaseio.com/v0/` (monthly thread from user `whoishiring`, e.g. item `49922569`) | **Allowed**: Official Firebase API documented in official repository ([`HackerNews/API`](https://github.com/HackerNews/API)). Fetched 2026-10-14. | Unstructured top line in comment text (pipe-separated: `Company \| Title \| Location \| Remote`). | In title/comment body text. | Docs state: "There is currently no rate limit." We apply a client-side 0.1s throttle between items and limit to top-level comments. | **BUILD** |

## Tech Stack
- Python 3.12+ (this Linux checkout runs 3.14.4)
- PostgreSQL 18.6 (native service; Docker Compose still supported)
- Pydantic v2
- Psycopg 3
- Requests & BeautifulSoup4
- numpy / scikit-learn / joblib (title classifier + eval harness)
- Ollama + `qwen2.5:3b` (active-learning triage)
- Optional: Laya scoring stack via `.venv/bin/pip install -r requirements-laya.txt` (torch/transformers, multi-GB)
