# Tasks Backlog

## Phase 1: Foundations & Local Database
- [x] 1.1 Clean legacy root clutter into `archive/`, init Git repository, create `.gitignore`, `requirements.txt`, and package layout (`src/extractors`, `src/models`, `src/db`).
- [x] 1.2 Create `docker-compose.yml` for local PostgreSQL and verify container connectivity with a test script.
- [x] 1.3 Write and execute SQL migration script for `raw_job_listings`, `jobs`, and `job_matches` tables.

## Phase 2: Clean API Ingestion & Normalization
- [x] 2.1 Implement base extractor class and Arbeitnow API extractor with raw DB staging.
- [ ] 2.2 Implement Remotive API extractor with polite rate limiting.
- [ ] 2.3 Implement Pydantic normalization models for Arbeitnow and Remotive data.

## Phase 3: Deduplication & Enrichment
- [ ] 3.1 Implement SHA-256 fingerprinting and PostgreSQL upsert pipeline.
- [ ] 3.2 Implement regex enrichment for seniority (`intern`, `junior`) and tech tags.
- [ ] 3.3 Run end-to-end integration check: fetch, normalize, deduplicate, and store.

## Phase 4: Messy & Unstructured Sources
- [ ] 4.1 Build Hacker News Algolia extractor for "Who is hiring" comments.
- [ ] 4.2 Build text parser for unformatted HN comment posts with defensive fallbacks.
- [ ] 4.3 Build polite BeautifulSoup scraper for Merojob tech listings.

## Phase 5: CV Matching & Ranking
- [ ] 5.1 Define `cv_profile.json` structure for candidate skills and preferences based on CVs.
- [ ] 5.2 Build scoring algorithm (skill overlap, title matching, remote weighting).
- [ ] 5.3 Batch score stored jobs and write results to `job_matches`.

## Phase 6: Output & Automation
- [ ] 6.1 Implement `FEED.md` exporter with formatted tables and direct apply links.
- [ ] 6.2 Build interactive CLI query tool for reviewing top matches.
- [ ] 6.3 Package pipeline runner into a scheduled daily script.
- [ ] 6.4 Wire the web dashboard (`tools/app.py`) to PostgreSQL and fix UI buttons.
