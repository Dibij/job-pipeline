# Job Pipeline & Matcher

A modular data engineering pipeline that aggregates messy job listings from multiple sources, normalizes and deduplicates them into PostgreSQL, and scores them against a personal CV to surface relevant junior, remote, and local roles.

## Architecture
- **Ingest**: Pluggable extractors for public APIs (Remotive, Arbeitnow, Jobicy, Greenhouse) and polite HTML scraping (Merojob).
- **Stage**: Raw JSON/HTML payloads preserved in `raw_job_listings` (ELT pattern) to guarantee zero data loss.
- **Normalize & Enrich**: Pydantic models clean text, extract seniority levels (`junior`, `intern`), and isolate tech stacks.
- **Deduplicate**: SHA-256 content hashing collapses identical postings cross-posted across platforms.
- **Match**: Weighted rule-based ranking scoring postings against CV profile keywords.
- **Output**: Daily markdown digest (`FEED.md`), interactive CLI review tool, and local web dashboard.

## Tech Stack
- Python 3.11+
- PostgreSQL 16 (via Docker Compose)
- Pydantic v2
- Psycopg 3
- Requests & BeautifulSoup4
