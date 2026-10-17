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

## Phase 5: CV Matching & Ranking (Rule-based baseline -- DO NOT REMOVE)
- [x] 5.1 Define `cv_profile.json` structure for candidate skills and preferences.
- [x] 5.2 Build rule-based MatchScorer with word-boundary regex matching and Nepal geo-filter.
- [x] 5.3 Batch score stored jobs and write results to `job_matches`.

## Phase 5b: Fix What's Wrong (Audit & Refactor)
- [x] 5b.1 Seniority audit: sample 30 jobs labeled `senior`, report triggers and false positives. No code changes yet.
- [x] 5b.2 Fix seniority detection: prefer title over body, use word boundaries, treat body-only hits as weak evidence. Regression tests. Re-run enrichment, show before/after counts.
- [x] 5b.3 Split hard filters from scoring. Extract German/unpaid/region-locked disqualifiers from `MatchScorer` into a `HardFilter` module with reason codes. Scoring runs only on passing jobs. Update tests, keep all passing, show before/after top-20 ranking.

## Phase 5c: Pipeline Hygiene (do before 7.7b)
- [x] 5c.1 **AUDIT (read-only)** — completed. Recorded duplicate root causes, filter holes, score breakdown, supply counts, label hygiene.
- [x] 5c.2 **FIXES** (completed):
  - **5c.2a** Feed join & single score: LATERAL joins for 1 row per job, ranked by MatchScorer only, Laya score in separate column, scanned count is unique jobs.
  - **5c.2b** Cross-posted duplicates: migration 005 `canonical_job_id` + `canonicalize_jobs.py` using URL listing-ID extractor & slug fallback. 17 label pairs confirmed to agree.
  - **5c.2c** Language filter: NON_ENGLISH (replaces GERMAN_ONLY) detects French and all non-English via `detected_language` + title/desc pattern fallback.
  - **5c.2d** Location locks: single-country location strings (USA, Switzerland, etc.) blocked; ambiguous regions (APAC, Asia) marked NEEDS_REVIEW.
  - **5c.2e** Non-technical title filter: configurable blocklist in `cv_profile.json` (`non_technical_title_blocklist`). FEED.md lists 3 example titles per filter reason.
  - **5c.2f** Scorer fix: fallback to `JobEnricher.detect_seniority` when `experience_level` is unspecified (`senior` penalty -80 applied); skill matching focused on requirements & responsibilities sections via `jd_extractor.py`.
  - **5c.2g** Re-run evaluation: `evaluate_scoring.py` updated to query deduplicated canonical postings (69 unique labeled postings).
- [x] 5c.3 **SUPPLY AUDIT** (completed):
  - Remotive vs Arbeitnow gap analyzed: Remotive extractor filtered exclusively by `category=software-dev` (returning active tier list ~19 jobs), whereas Arbeitnow queries paginated all-category endpoints (~1,445 jobs).
  - Evaluated 5 candidate new sources: Jobicy API, WWR RSS, HN Algolia API, RemoteOK JSON, NoFluffJobs API.
  - Updated `TRAINING.md` milestones for M1/M2/M3.

## Phase 6: Output & Automation
- [x] 6.1 Implement `FEED.md` exporter: ranked table of jobs that passed hard filters, with score, title, company, location/remote, matched skills, and apply link. Include a section showing filter reason-code counts.
- [x] 6.2 Build interactive CLI query tool for reviewing top matches.
- [x] 6.3 Package pipeline runner into a scheduled daily script.
- [x] 6.4 Wire the web dashboard (`tools/app.py`) to use the new hard-filter output, reachability status, and in-browser human labeling & rating.

## Phase 6 Refinements: Accessibility, Thresholds & Evaluation
- [x] 6a **Accessibility Architecture** (highest priority):
  - Add migration 006: `accessibility` column (`ACCESSIBLE`, `BLOCKED`, `UNKNOWN`). Retain `nepal_accessible` until verified.
  - Normalization fix: never default `remote_restriction` to "Worldwide" or "Remote". Store source value or "unspecified".
  - 3-state `accessibility` logic: `accessible` (explicit worldwide/global/Nepal), `blocked` (exclusive lists, title region codes EMEA/NA/EU/US/LATAM, city-level locations), `unknown` (all others, including APAC/Asia).
  - Re-normalize all jobs from `raw_job_listings`.
  - `HardFilter` disqualifies only `blocked`. `FEED.md` groups `accessible` first and `unknown` in separate section ("location not stated").
- [x] 6b **Feed Threshold**:
  - Require matched skills OR technical title signal (`cv_profile.json` -> `technical_title_signals`). Remote bonus alone does not qualify. Drop placeholder titles ("template", "test"). (Dropped 20 non-technical/placeholder roles; kept roles like "Full-stack Engineer - Creative Agents").
- [x] 6c **UNPAID False Positives**:
  - Contextual matching for "unpaid" (unpaid internship/role/position/volunteer, "this is an unpaid ..."). Regression tests. (UNPAID reduced from 53 to 1 true positive; 52 false positives eliminated).
- [x] 6d **Enrichment Integration & Backfill**:
  - Re-run check (42.1% experience_level changed, 95.8% tags changed). Ran enrichment inside `JobPipeline.process_staged()` for new jobs and backfilled all 1,846 existing DB rows via `scripts/backfill_enrichment.py`. Unspecified experience dropped from 1,440 to 710.
- [x] 6e **Evaluation & Calibration Alignment**:
  - Population = hard-filter survivors (n=11, pos=3). Metrics per TRAINING.md §7: recall@20 (1.000), recall@10 (1.000), precision@10 (0.300), precision@20 (0.273), PR-AUC (0.232) with 95% bootstrap CIs. Feed precision of top 10: good_fit=2, maybe=2, bad_fit=4, unlabeled=2. Terminology: 'decision model' used throughout. Reconciled `laya_temperatures_v1.json` (69 labels confirmed).
- [x] 6f **Sources Research** (Oct 11 2026) — See PROGRESS.md §6f for full quoted findings.
  - **Himalayas**: Free public JSON API. Rate limit: 429 returned if exceeded; no numeric limit published. Data cached every 24 h; polling more often provides no benefit. Max 20 jobs/request. `locationRestrictions` and `timezoneRestrictions` fields on each job. Attribution required (link back + mention Himalayas). Source: `https://himalayas.app/api` (FAQ section, fetched 2026-10-10).
  - **Jobicy**: Free public API (no key). `jobGeo` field per job. No numeric rate limit published; 429 returned on excess; fair-use only. `count` param (up to 50). Source: API JSON response header + friendly notice in `https://jobicy.com/api/v2/remote-jobs`.
  - **Merojob**: Nepal-focused job board. Terms explicitly prohibit "Data scraping, automated bots, or other tools for collecting or mining personal or professional data." No public API. `robots.txt` empty Disallow but `ai-train=no`. **Never use Merojob text for fine-tuning.** Source: `https://merojob.com/terms-and-conditions/` (section 3.E, fetched 2026-10-11).
- [x] 6g **Tri-State Reachability & Candidate Sources Ingestion** (Oct 14-15 2026):
  - Migration 008 added `reachable_from_nepal` (`accessible`, `unknown`, `blocked`) and `reachable_reason`.
  - Built extractors & transformers for Himalayas, We Work Remotely (RSS), Remote OK, Jobicy, and Hacker News (Who is hiring Firebase API).
  - Staged and scored all sources. Database reached 2,609 active jobs (90 accessible, 218 unknown, 2,301 blocked).
- [x] 6h **In-Browser Labeling & Rating Dashboard** (Oct 15 2026):
  - Upgraded `tools/app.py` with `POST /api/label` endpoint.
  - Integrated 1-5 star rating, fit buttons (`good_fit`, `maybe`, `bad_fit`), and inline notes directly into job cards.
  - Added `⚡ Unlabeled Only` filtering. Total human-labeled jobs crossed 100 milestone (103 unique jobs, 127 records).


## Phase 7: Laya Scoring
- [x] 7.1 Spike: run Laya locally on one hard-coded example and print raw output. Record hardware, speed, and token limit in PROGRESS.md.
- [x] 7.2 JD section extraction: `src/matching/jd_extractor.py`. Heading + keyword rules, graceful fallback. 24 tests.
- [x] 7.3 Truncation to token budget: `src/matching/jd_truncator.py`. Budget computed from real token counts (not assumed). Count with real tokenizer. Priority: title, company, location, requirements, responsibilities, nice-to-haves, company blurb. Drop benefits/legal first. Add `[...]` markers. Include compact CV summary. Tests: very long, very short, empty, and real DB JDs.
- [x] 7.4 Typed questions and scoring: `config/laya_questions.yaml` + `src/matching/laya_scorer.py`. Load from config (never hard-code). Gate questions remove disqualified jobs with reason codes. Penalty questions subtract points. Score questions weighted average to 0-100. Show per-question breakdown for 10 real jobs.
- [x] 7.5 Confidence gating: if any score/gate question confidence < threshold, mark "needs_review". Config-driven threshold. `use_confidence_flag: false` until 7.8a calibration -- flag computed but never used to filter.
- [x] 7.6 Storage: `laya_job_scores` table (migration 004). Stores final score, per-question data (JSONB), gate_warnings (JSONB), needs_review flag, laya_checkpoint, config_version, tokens_used, scored_at. Unique constraint on (job_id, checkpoint, config_version) for resumable batch scoring. `scripts/score_jobs.py` with `--limit`, `--dry-run`, ETA output.
- [x] 7.7 Labeling protocol: export batches from the DB, label manually, ingest. Scaffolding complete (`export_for_labeling.py`, `ingest_labels.py`). 86 labels ingested. Protocol updated -- see TRAINING.md §6 for full rules (strata, hygiene, Laya answer hiding).

## Phase 7 -- Training Workstream (src/training/, scripts/, TRAINING.md)
- [x] 7.7b **Schema & export hygiene changes** (Oct 13 2026):
  - Added migration `007_labeling_schema.sql` adding `sampling_stratum` and `label_guideline_version` to `laya_labels`.
  - Updated `scripts/export_for_labeling.py`: implemented 3-stratum sampling (40% random, 30% high_match_scorer, 30% laya_uncertainty with fallback), excluded Laya score & confidence columns from output CSV to eliminate anchoring bias, and included `sampling_stratum` and `label_guideline_version` in output columns.
  - Updated `scripts/ingest_labels.py`: ingests `sampling_stratum` and `label_guideline_version` into `laya_labels` columns.
  - Added unit test suite `tests/test_export_labeling.py` (9 tests passing).
- [x] 7.8a Temperature calibration: **PROVISIONAL** — ran on 69 unique labels (759 question records across 11 questions, confirmed in `config/laya_temperatures_v1.json`). Still below M1 threshold (~150 labels). `use_confidence_flag` stays `false` until M1. Saves temperature as versioned config. At M1: evaluate with held-out folds, report calibration quality and ranking metrics (precision@k, recall@k, PR-AUC with bootstrap CIs). Never rebalance the calibration set.
- [ ] 7.8b **BLOCKED (M3)** Fine-tune Laya decision head: supervised head training with proper scoring rules (Brier/RPS). Gated on:
  - >= 150 labeled rows total
  - >= 30 `good_fit` labels (`min_positive_labels`, configurable -- default 30)
  Both gates must pass. Primary metric is binary good_fit vs not; `maybe` maps to not good_fit. Rebalancing (class weights or downsampling bad_fit) allowed **in the train split only**. Held-out folds are never rebalanced. Use repeated stratified grouped k-fold. Report Laya vs MatchScorer comparison on the same folds. Save versioned checkpoints (out of git). Never trains on Laya's own predictions as labels.
- [ ] 7.9 **NOT STARTED** Report script (`scripts/report_labels.py`):
  - Per-source counts and `good_fit` rates (Arbeitnow, Remotive, etc.).
  - Per-stratum counts and `good_fit` rates.
  - Laya vs MatchScorer top-k metrics (precision@10, recall@10, recall@20, PR-AUC) on current labeled set, with bootstrap 95% CIs.
  - Print caveat when `good_fit` count < 30.

## Phase 7 -- Training Scaffolding Scripts (no real training yet)
- [x] scripts/export_for_labeling.py: run unlabeled jobs through extractor, truncator, Laya, write `labeling_batch_YYYYMMDD.csv` (id, title, company, link, Laya answers, confidence, empty `my_label`). Sort least-confident first; mix in random jobs to avoid bias.
- [x] scripts/ingest_labels.py: read labeled CSV, validate, insert into `laya_labels` table (never overwrite).
- [x] scripts/calibrate_laya.py (7.8a): temperature fitting on train split, evaluation on held-out, save versioned config.
- [x] scripts/train_laya.py (7.8b): reads labeled rows, supports `--dry-run` on tiny fake dataset. Refuses to train when labels < 150 with clear explanation.

## Phase 8: Pipeline Cleanup & Architecture Harmonization (tmp/4.txt)
- [x] 8.1 Record tmp/4.txt findings and decisions into project documentation (README.md, PROGRESS.md, TASKS.md, TRAINING.md).
- [x] 8.2 DB Identity & Fast-Fail Timeout: Verify database connection host/port/db vs docker-compose.yml; add `connect_timeout=5` to connection pool to prevent socket hanging.
- [x] 8.3 HN Parser & Field-Length Truncation: Fix Hacker News comment parser fallback for non-pipe comments; truncate strings to 255 chars in normalization with warnings.
- [x] 8.4 Count Mismatch Diagnosis: Document queries and root causes for 287 HardFilter passed vs 109 really passed vs 40/69 feed vs 546 score_jobs.
- [ ] 8.5 One Shared Eligibility Function: Create `src/matching/eligibility.py` as single source of truth for candidate eligibility across run_daily, score_jobs, and export_for_labeling; fix summary count key.
- [ ] 8.6 Single Reachability Field: Retain `reachable_from_nepal` & `reachable_reason` as only reachability fields; eliminate reads/writes of legacy `nepal_accessible` and `accessibility`.
- [ ] 8.7 Title & Seniority Hard Filter: Extend `non_technical_title_blocklist` and add configurable seniority title checks (`SENIORITY_TITLE`) with zero-regression check on human labels.
- [ ] 8.8 `laya_uncertainty` Stratum Fallback: When Laya-scored jobs are insufficient, fall back to random eligible pool until calibration is verified.
- [ ] 8.9 `SOURCES` Orchestrator Registry: Refactor `JobPipeline.run_extractors` into a declarative `SOURCES` list with per-source error isolation.
- [ ] 8.10 Documentation Finalization: Synchronize all numbers, reason codes, and architecture decisions across docs with verified session measurements.

