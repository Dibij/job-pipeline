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
- [x] 5b.1 Seniority audit: sample 30 jobs labeled `senior`, report triggers and false positives. No code changes yet.
- [ ] 5b.2 Fix seniority detection: prefer title over body, use word boundaries, treat body-only hits as weak evidence. Regression tests. Re-run enrichment, show before/after counts.
- [ ] 5b.3 Split hard filters from scoring. Extract German/unpaid/region-locked disqualifiers from `MatchScorer` into a `HardFilter` module with reason codes. Scoring runs only on passing jobs. Update tests, keep all passing, show before/after top-20 ranking.

## Phase 6: Output & Automation
- [ ] 6.1 Implement `FEED.md` exporter: ranked table of jobs that passed hard filters, with score, title, company, location/remote, matched skills, and apply link. Include a section showing filter reason-code counts.
- [ ] 6.2 Build interactive CLI query tool for reviewing top matches.
- [ ] 6.3 Package pipeline runner into a scheduled daily script.
- [ ] 6.4 Wire the web dashboard (`tools/app.py`) to use the new hard-filter output.

## Phase 7: Laya Scoring
- [x] 7.1 Spike: run Laya locally on one hard-coded example and print raw output. Record hardware, speed, and token limit in PROGRESS.md.
- [x] 7.2 JD section extraction: `src/matching/jd_extractor.py`. Heading + keyword rules, graceful fallback. 24 tests.
- [x] 7.3 Truncation to token budget: `src/matching/jd_truncator.py`. Budget computed from real token counts (not assumed). Count with real tokenizer. Priority: title, company, location, requirements, responsibilities, nice-to-haves, company blurb. Drop benefits/legal first. Add `[...]` markers. Include compact CV summary. Tests: very long, very short, empty, and real DB JDs.
- [x] 7.4 Typed questions and scoring: `config/laya_questions.yaml` + `src/matching/laya_scorer.py`. Load from config (never hard-code). Gate questions remove disqualified jobs with reason codes. Penalty questions subtract points. Score questions weighted average → 0-100. Show per-question breakdown for 10 real jobs.
- [x] 7.5 Confidence gating: if any score/gate question confidence < threshold, mark "needs_review". Config-driven threshold. `use_confidence_flag: false` until 7.8a calibration — flag computed but never used to filter.
- [x] 7.6 Storage: `laya_job_scores` table (migration 004). Stores final score, per-question data (JSONB), gate_warnings (JSONB), needs_review flag, laya_checkpoint, config_version, tokens_used, scored_at. Unique constraint on (job_id, checkpoint, config_version) for resumable batch scoring. `scripts/score_jobs.py` with `--limit`, `--dry-run`, ETA output.
- [ ] 7.7 Evaluation: labeled CSV (~30-50 jobs: good_fit / maybe / bad_fit), comparison script for MatchScorer vs Laya vs labels.

## Phase 7 — Training Workstream (src/training/, scripts/, TRAINING.md)
- [ ] 7.8a Temperature calibration: fit a temperature on labeled data to fix Laya's uncalibrated confidence. Evaluate before/after on held-out split. Save temperature as versioned config. (Can run with fewer than 150 labels.)
- [ ] 7.8b Fine-tune Laya decision head: supervised head training with proper scoring rules (Brier/RPS). Only runs when labeled rows ≥ 150 (configurable). Never trains on Laya's own predictions as labels. Saves versioned checkpoints (out of git). Prints comparison report vs baseline and original Laya before recommending new checkpoint.

## Phase 7 — Training Scaffolding Scripts (no real training yet)
- [x] scripts/export_for_labeling.py: run unlabeled jobs through extractor → truncator → Laya, write `labeling_batch_YYYYMMDD.csv` (id, title, company, link, Laya answers, confidence, empty `my_label`). Sort least-confident first; mix in random jobs to avoid bias.
- [x] scripts/ingest_labels.py: read labeled CSV, validate, insert into `laya_labels` table (never overwrite).
- [x] scripts/calibrate_laya.py (7.8a): temperature fitting on train split, evaluation on held-out, save versioned config.
- [x] scripts/train_laya.py (7.8b): reads labeled rows, supports `--dry-run` on tiny fake dataset. Refuses to train when labels < 150 with clear explanation.
