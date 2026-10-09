# Job Pipeline & Matcher

A modular data engineering pipeline that aggregates messy job listings from multiple sources, normalizes and deduplicates them into PostgreSQL, and scores them against a personal CV to surface relevant junior, remote, and local roles.

## Architecture
- **Ingest**: Pluggable extractors for public APIs (Remotive, Arbeitnow, Jobicy, Greenhouse) and polite HTML scraping (Merojob).
- **Stage**: Raw JSON/HTML payloads preserved in `raw_job_listings` (ELT pattern) to guarantee zero data loss.
- **Normalize & Enrich**: Pydantic models clean text, extract seniority levels (`junior`, `intern`), and isolate tech stacks.
- **Deduplicate**: SHA-256 content hashing collapses identical postings cross-posted across platforms.
- **Match**: Weighted rule-based ranking scoring postings against CV profile keywords.
- **Output**: Daily markdown digest (`FEED.md`), interactive CLI review tool, and local web dashboard.

## ⚡ Quick Commands Cheatsheet

| Task | PowerShell Command | Note |
| :--- | :--- | :--- |
| **🌐 Web Dashboard** | `& .\.venv\Scripts\python.exe tools/app.py` | Open **http://localhost:5000** in browser |
| **🚀 Generate FEED.md** | `& .\.venv\Scripts\python.exe scripts/export_feed.py` | Exports top matched jobs to `FEED.md` |
| **🔄 Run Daily Pipeline** | `& .\.venv\Scripts\python.exe scripts/run_daily.py` | Fetch → Normalize → MatchScorer → Update FEED.md |
| **📋 Interactive CLI Review** | `& .\.venv\Scripts\python.exe scripts/review_jobs.py` | Review jobs (`y/n/s/q`), saves to `data/reviewed_jobs.json` |
| **📥 Export Labeling Batch** | `& .\.venv\Scripts\python.exe scripts/export_for_labeling.py --no-rescore --batch-size 30` | Creates `data/labeling_batch_YYYYMMDD.csv` |
| **📤 Ingest Human Labels** | `& .\.venv\Scripts\python.exe scripts/ingest_labels.py data/labeling_batch_YYYYMMDD.csv` | Ingests CSV into `laya_labels` in Postgres |
| **🎯 Calibrate Laya** | `& .\.venv\Scripts\python.exe scripts/calibrate_laya.py --version v1` | Fits temperature scaling on human labels |

---

## 🌐 Local Web Dashboard

Launch the live visual web interface backed directly by your local PostgreSQL database:

```powershell
& .\.venv\Scripts\python.exe tools/app.py
```

Then open **[http://localhost:5000](http://localhost:5000)** in your browser.

- Features live search filtering by keyword, tech stack tag (`Python`, `Django`, `React`, `AI`), and remote accessibility.
- Connects live to `raw_job_listings` in PostgreSQL and normalizes jobs dynamically.
- Interactive "Apply Now ↗" buttons link directly to original listings.

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

## Tech Stack
- Python 3.12+
- PostgreSQL 16 (via Docker Compose)
- Pydantic v2
- Psycopg 3
- Requests & BeautifulSoup4
