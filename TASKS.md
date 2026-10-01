# Tasks Backlog

## Phase 1: Foundations & Local Database
- [x] 1.1 Clean legacy root clutter into `archive/`, init Git repository, create `.gitignore`, `requirements.txt`, and package layout.
- [x] 1.2 Create `docker-compose.yml` for local PostgreSQL and verify container connectivity.
- [x] 1.3 Write and execute SQL migration script for `raw_job_listings`, `jobs`, and `job_matches` tables.

## Phase 2: Clean API Ingestion & Normalization
- [x] 2.1 Implement base extractor class and Arbeitnow API extractor with raw DB staging.
- [x] 2.2 Implement Remotive API extractor with polite rate limiting.
- [x] 2.3 Implement Pydantic normalization models for Arbeitnow and Remotive data.

## Phase 3: Deduplication & Enrichment
- [x] 3.1 Implement SHA-256 fingerprinting and PostgreSQL upsert pipeline.
- [x] 3.2 Implement regex enrichment for seniority, language, unpaid flag, and tech tags.
- [x] 3.3 Run end-to-end integration check: fetch, normalize, deduplicate, and store.

## Phase 4: Messy & Unstructured Sources (Skipped per request)
- [ ] 4.1 Build Hacker News Algolia extractor for "Who is hiring" comments.
- [ ] 4.2 Build text parser for unformatted HN comment posts.
- [ ] 4.3 Build polite BeautifulSoup scraper for Merojob tech listings.

## Phase 5: CV Matching & Ranking (Rule-based baseline — DO NOT REMOVE)
- [x] 5.1 Define `cv_profile.json` structure for candidate skills and preferences.
- [x] 5.2 Build rule-based MatchScorer with word-boundary regex matching and Nepal geo-filter.
- [x] 5.3 Batch score stored jobs and write results to `job_matches`.

## Phase 5b: Fix What's Wrong (Audit & Refactor)
- [ ] 5b.1 Seniority audit. Sample 30 jobs labeled `senior` and print the title + exact triggering text. Report false positive count. Do not change the regex yet.
- [ ] 5b.2 Fix seniority detection based on 5b.1 audit: prefer title over body, use word boundaries, treat body-only hits as weak evidence. Regression tests from the real false positives. Re-run enrichment and show before/after counts.
- [ ] 5b.3 Split hard filters from scoring. Extract German/unpaid/region-locked disqualifiers from `MatchScorer` into a separate `HardFilter` module that records a reason code. Scoring runs only on passing jobs. Update tests, keep all 28 passing, show before/after top-20 ranking.

## Phase 6: Output & Automation
- [ ] 6.1 Implement `FEED.md` exporter: ranked table of jobs that passed hard filters, with score, title, company, location/remote, matched skills, and apply link. Include a section showing filter reason-code counts.
- [ ] 6.2 Build interactive CLI query tool for reviewing top matches.
- [ ] 6.3 Package pipeline runner into a scheduled daily script.
- [ ] 6.4 Wire the web dashboard (`tools/app.py`) to use the new hard-filter output.

## Phase 7: Laya Scoring
- [x] 7.1 Spike: run Laya locally on one hard-coded example and print raw output. Record hardware, speed, and token limit in PROGRESS.md. STOP and show result before 7.2.
- [x] 7.2 JD section extraction: module that splits a JD into sections (title, responsibilities, requirements, nice-to-haves, benefits, company blurb, legal/EEO). Heading + keyword rules, graceful fallback when no headings. Tests with messy inputs.
- [ ] 7.3 Truncation to token budget: fit scoring input inside Laya's limit using configurable `LAYA_INPUT_TOKEN_BUDGET`. Priority order to keep: title, company, location/remote, requirements, responsibilities, nice-to-haves, company blurb. Drop benefits and legal boilerplate first. Add `[...]` marker when cutting. Include compact CV summary in budget.
- [ ] 7.4 Typed questions and scoring: 4-6 typed questions (score: skills fit, seniority fit, domain fit; boolean: fully remote, requires unreachable hours, looks like a real job). Combine answers into one score with weights from a config file.
- [ ] 7.5 Confidence gating: if Laya's confidence on a question is below a configurable threshold, mark job "needs review" instead of trusting the score.
- [ ] 7.6 Storage: new table `laya_job_scores` (never overwrites `job_matches`). Stores final score, per-question scores and probabilities, confidence flag, Laya checkpoint/version, scoring-config version, and timestamp.
- [ ] 7.7 Evaluation: build a labeled CSV (~30-50 jobs: good fit / maybe / bad fit), then a script comparing MatchScorer vs Laya rankings against the labels and printing a simple report.
- [ ] 7.8 Fine-tune Laya decision head: adapt Laya on the labeled JD dataset using RLCD to specialize the model on candidate CV matching and calibrate prediction probabilities.
