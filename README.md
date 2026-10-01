# Job Pipeline & Matcher

A modular data engineering pipeline that aggregates messy job listings from multiple sources, normalizes and deduplicates them into PostgreSQL, and scores them against a personal CV to surface relevant junior, remote, and local roles.

## Architecture
- **Ingest**: Pluggable extractors for public APIs (Remotive, Arbeitnow, Jobicy, Greenhouse) and polite HTML scraping (Merojob).
- **Stage**: Raw JSON/HTML payloads preserved in `raw_job_listings` (ELT pattern) to guarantee zero data loss.
- **Normalize & Enrich**: Pydantic models clean text, extract seniority levels (`junior`, `intern`), and isolate tech stacks.
- **Deduplicate**: SHA-256 content hashing collapses identical postings cross-posted across platforms.
- **Match**: Weighted rule-based ranking scoring postings against CV profile keywords.
- **Output**: Daily markdown digest (`FEED.md`), interactive CLI review tool, and local web dashboard.

## 🌐 Local Web Dashboard

Launch the live visual web interface backed directly by your local PostgreSQL database:

```powershell
.\.venv\Scripts\python tools/app.py
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
