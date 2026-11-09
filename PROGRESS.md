# Project Progress

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
| **🧠 Score Jobs with Laya** | `.venv/bin/python scripts/score_jobs.py` | Batch scores eligible jobs using Laya neural decision engine |
| **📋 Interactive CLI Review** | `.venv/bin/python scripts/review_jobs.py` | Review jobs (`y/n/s/q`), saves to `data/reviewed_jobs.json` |
| **📥 Export Labeling Batch** | `.venv/bin/python scripts/export_for_labeling.py --no-rescore --batch-size 30` | Legacy 3-stratum exporter |
| **📤 Ingest Human Labels** | `.venv/bin/python scripts/ingest_labels.py data/labeling_batch_YYYYMMDD.csv` | Ingests CSV into `laya_labels` in Postgres |
| **📦 Export Labeled Datasets** | `.venv/bin/python scripts/export_labeled_descriptions.py` | Exports bookkeeping and clean training JSONL |
| **📊 5-Fold GroupKFold Splits** | `.venv/bin/python scripts/make_splits.py` | Generates 5 company-stratified cross-val folds in `data/splits/` |
| **🧹 Backfill Clean Descriptions** | `.venv/bin/python scripts/backfill_clean_descriptions.py` | Cleans HTML/mojibake in `jobs.description_text` (payloads untouched) |
| **🌍 Backfill Detected Languages** | `.venv/bin/python scripts/backfill_detected_language.py` | Re-evaluates language via title+first 500 chars & updates DB |
| **🔍 Audit Language Transitions** | `.venv/bin/python scripts/audit_language_changes.py` | Audits French/German/English transitions and false positives |
| **🎯 Calibrate Laya** | `.venv/bin/python scripts/calibrate_laya.py --version v4` | Fits temperature scaling on human labels (ECE enabled at 150 labels) |
| **🧠 Train Laya Head** | `.venv/bin/python scripts/train_laya.py --version v3` | Fine-tunes decision head with frozen ModernBERT encoder |
| **📈 Pipeline Funnel Report** | `.venv/bin/python scripts/funnel_report.py --days 7` | Source-level funnel stats (fetched → new → passed HF → scored ≥60) |
| **🇳🇵 Manual Nepal Import** | `.venv/bin/python scripts/import_manual_jobs.py -f jobs.json` | Ingests user-supplied JSON/CSV (NO web scraping) |
| **🧪 ATS Yield Dry-Run** | `.venv/bin/python scripts/dry_run_yield_test.py` | In-memory yield test across 10 company ATS boards (no DB writes) |

---

## Current State (Linux rebuild — 2026-11-06)

### Infrastructure & Sources
- **Fresh Linux database (2026-11-06)**: PostgreSQL 18.6 on `localhost:5432`, schema through migration `014_add_job_matches_reason_code.sql`. The old Windows DB was **not migrated** — the live DB currently has **30 labels** (24 `bad_fit`, 5 `maybe`, 1 `good_fit`) and **0 Laya scores**.
- **2,364 unique jobs** from **26 pipeline sources** (8 aggregators: Arbeitnow, Remotive, Himalayas, We Work Remotely, Remote OK, Jobicy, Hacker News, Working Nomads; 18 ATS boards, including Supabase, ElevenLabs, GitLab, Canonical, Mozilla, Elastic, Grafana Labs, Wikimedia, Railway, PostHog, Clerk, Buffer, Zapier, Help Scout, Bitwarden, Mattermost, Ghost, Remote.com). `raw_job_listings` holds 2,716 rows.
- **Allowlist HardFilter & Eligibility Active**: Disqualifies non-remote foreign jobs (`NOT_REMOTE`), region locks outside Nepal (`NOT_ELIGIBLE_REGION` / `REGION_LOCKED`), senior roles (`TOO_SENIOR`), hard degree / 3+ year requirements (`DEGREE_OR_EXP`), non-English (`NON_ENGLISH`), unpaid (`UNPAID`) and explicitly non-technical titles (`NON_TECHNICAL`). Unified through `src/matching/eligibility.py`. Note: the "five gates" are distributed across `hard_filter.py` and `enricher.py`; Gate 3/4/5 are not separate HardFilter code paths.
- **Docker & PostgreSQL installed**: Docker 29.1.3 + Compose v2 and PostgreSQL 18.6 are enabled systemd services. `src/db/docker_control.py` fast-paths when Postgres is healthy, so the native DB is used and Docker is not touched on a normal run. `docker` commands need a re-login in this session for the `docker` group.
- **OpenAI leak (historical)**: the pre-migration DB had 571 stored OpenAI jobs, all disqualified, and the board is disabled. The rebuilt DB starts only from the 18 enabled ATS boards, so no OpenAI rows exist.
- **Zero-Scraping Nepal Ingestion**: `scripts/import_manual_jobs.py` accepts user-supplied JSON/CSV only; no Nepali site is scraped.
- **In-Browser Feedback Dashboard (`app.py`)**: root app with Feed/Rejected tabs and live labeling, stamped `v2_role_fit_only`. Known gap: the production app does **not** populate the 5 gate audit columns; only the older `tools/app.py` did (and that duplicate now stamps v2 as well).
- **Automation & Scheduling**: `scripts/run_scheduled.py` with `data/pipeline.lock`, rotating log, and `source_runs` telemetry. Windows Task Scheduler and Docker/Linux cron remain supported; the Docker doc's env vars were corrected to `POSTGRES_*`.
- **Smart Active-Learning Triage**:
  - `scripts/smart_label_triage.py`: MatchScorer + stored Laya scores → 4 buckets → Ollama `qwen2.5:3b` labels non-obvious jobs → `data/triage_suggestions_*.json`.
  - Fixed fresh-DB bugs: `needs_human_review` → `needs_review`, latest-score LATERAL join, eligibility applied before the limit, and missing Laya scores no longer collapse everything to `OBVIOUS_BAD`.
  - Ollama triage is **ON by default**; `--triage-ollama` is now a compatibility no-op, `--no-llm` disables it.
- **Environment**: `.venv` on Python 3.14.4 with `requirements.txt` + numpy/scikit-learn/joblib/PyYAML; `laya`/torch install was still running at the time of this note. Ollama `qwen2.5:3b` (1.9 GB) is installed and runs **22% CPU / 78% GPU** on the RTX 2050.
- **Tests**: 194 passed, 5 skipped (Laya tokenizer tests; the optional 842 MB checkpoint is not cached yet). Laya package + torch 2.15.0+cu132 installed; `torch.cuda.is_available()=True`. The old training JSONL files were moved to `data/pre_rebuild_20261106/` so stale labels cannot silently feed training; regenerate with `export_labeled_descriptions.py` after labeling.
- **Migrations**: 14 files through `014_add_job_matches_reason_code.sql`.

### Labeling & Model Training Status
**Live DB as of 2026-11-09: 30 labels (24 `bad_fit`, 5 `maybe`, 1 `good_fit`), 0 Laya scores.** The table below is the pre-migration snapshot (2026-10-29, from `scripts/report_labels.py`) kept for history — those rows no longer exist.

| Guideline Version (historical) | Label | Rows | Distinct Jobs |
|---|---|---|---|
| `v2_role_fit_only` | `bad_fit` | 201 | 110 |
| `v2_role_fit_only` | `maybe` | 55 | 32 |
| `v2_role_fit_only` | `good_fit` | 10 | 5 |
| **v2 Subtotal** | | **266** | **147** |
| `v1` (legacy definition) | `bad_fit` / `maybe` / `good_fit` | 108 | 73 (8 good_fit) |
| `v2` (pre-overhaul) | `bad_fit` / `good_fit` | 9 | 9 (6 good_fit) |
| `None` (legacy draft) | `bad_fit` / `maybe` / `good_fit` | 86 | 69 (6 good_fit) |

- **Training Gates**:
  - `scripts/train_ranker.py` and `scripts/train_laya.py` enforce strict safety gates: $\ge 150$ total v2 labels AND $\ge 30$ role-fit `good_fit` positives.
  - Current status: **30 / 150 v2 labels**, **1 / 30 role-fit `good_fit` labels** as of 2026-11-09 (check the app header for the live count; the old 147/5 state was lost with the Windows DB).
  - The 20 historical legacy `good_fit` jobs are also gone; there is nothing to "re-evaluate" until the new DB is labeled.
  - The old `data/triage_suggestions_20261029_1242.json` references deleted UUIDs and cannot be ingested. A fresh full run produced **`data/triage_suggestions_20261106_2017.json`** with 22 suggestions (15 `maybe`, 5 `bad_fit`, 2 `good_fit`) for human review.
- **Learned Title Role-Type Classifier (`src/matching/title_classifier.py`)**:
  - Char n-gram (3-5) TF-IDF + LogisticRegression trained on weak + human labels.
  - Claimed 5-fold Grouped CV result: **0.872 recall** vs Blocklist **0.745** (+12.7%) with **0.000 FPR on `good_fit`**. No committed report/artifact reproduces these numbers, and the current checkpoint predates the DB rebuild — treat as unverified.
  - Integrated as soft score penalty (`get_title_role_penalty()`) in `src/matching/scorer.py`.

---

## Resolved Architectural Items (Phase 8 & 11)
- **DB Connection Timeout**: Fixed `connect_timeout=5` in connection pool to prevent socket hanging when DB is stopped.
- **Hacker News Field-Length & Non-Pipe Parser**: Fixed in `src/models/transformers.py` via `is_unparseable_hn_title()`; records with location/timezone titles or missing pipes are stamped `exclude_reason="unparseable_title"`.
- **Shared Eligibility Module (Task 8.5)**: Implemented in `src/matching/eligibility.py` wrapping `HardFilter.apply()` and `exclude_reason` checks.
- **Labeling Report Script (Task 7.9)**: Implemented in `scripts/report_labels.py` providing source yield, stratum yield, gate checks, and bootstrap 95% CI ranking metrics.
- **Mojibake Cleaning**: Resolved mojibake artifacts (`Â `, smart quotes, non-breaking spaces) in `src/models/transformers.py` and `scripts/export_labeled_descriptions.py`.
- **Batch Pool Generator**: Implemented in `scripts/make_labeling_batch.py` with title-rule scoring, 70/30 rule-random split, company caps, and `v2_role_fit_only` stamping.
- **Title Seniority Filter**: Upgraded from rigid keyword blocklists to learned char n-gram TF-IDF title classifier with soft penalties, preventing false positive kills on technical support/reviewer roles.

---

## 5c.1 Audit Results (Oct 10 2026)

### 1. Duplicates
- **jobs table**: 1,464 rows, all with unique `external_id`, `apply_url`, and `fingerprint_hash`. No duplicate job rows.
- **job_matches**: 1,464 rows, one per job (no fan-out). `laya_job_scores`: 91 rows covering 43 distinct jobs (up to ~2 score rows per job from the 91/43 ratio — Laya multi-question storage).
- **Root cause of FEED.md repeats**: `export_feed.py` does a plain `LEFT JOIN job_matches m ON j.id = m.job_id` and `LEFT JOIN laya_job_scores l ON j.id = l.job_id` **without DISTINCT**, producing a cross-product when a job has multiple `laya_job_scores` rows. iMerit (2 laya rows × 1 match row = 2 feed rows), Coalition Office Assistant (3 laya rows = 3 feed rows), LILT Mongolian (2 laya rows across 2 job rows from .ch vs .fr = 2 rows), PRECIA MOLEN (4 distinct job rows with different fingerprints from .fr non-remote vs .ch remote URLs).
- **Label duplicates**: 17 company+title pairs labeled twice (same job exported from two sources with slightly different fingerprints, or same batch exported twice). E.g. iMerit, Coalition, LILT Mongolian, PRECIA MOLEN, TELUS Digital all duplicated.

### 2. Filter Holes (83 jobs currently passing HardFilter)
22 of 83 passing jobs have at least one issue:

| Issue type | Count | Examples |
|-----------|-------|---------|
| **NON_TECH_TITLE** | 18 | Linguist (6×), Account Executive (6×), Freelance Writer/Copywriter, Voice Actor, Office Assistant, Content Reviewer, Technicien maintenance |
| **COUNTRY_LOCK** (location without Nepal) | 6 | "Europe, USA, Canada, APAC" (Lemon.io), "USA" (TELUS), "Switzerland" (Voice Actor), "USA, Canada, USA timezones" (Mitre Media) |
| Both flags | 2 | Voice Actor Swiss German, TELUS Content Reviewer |

Key gaps in HardFilter: (a) no non-technical title check at all, (b) only `detected_language='german'` blocked — French (`arbeitnow.fr`) passes, (c) `nepal_accessible` flag is set by enrichment but the location string check misses "Switzerland" and compound lists like "Europe, USA, Canada, APAC".

### 3. Scorer Breakdown
The top-scoring job in today's snapshot is "Technical Customer Support Specialist" (Happyrobot.ai, score 65.0) with 7 matched skills — that's correct. The FEED.md showed "AI Response Evaluator" at 67.6 because the feed query was joining without DISTINCT, and one laya_job_scores row for it had a higher `final_score` (Laya score) than the MatchScorer score for another job. After deduplication, the top-10 MatchScorer results all have matched skills.

MatchScorer formula: `skill_points + remote_bonus (15) + adjustments`. Skill points = sum of per-skill weights. A zero-skill job gets 0 + 15 = 15 from remote bonus alone; the current FEED.md shows two zero-skill jobs at 0.0 and 15.0, which is reasonable. The 67.6 in old FEED.md came from Laya's `final_score` (Laya scoring scale, not MatchScorer scale) bleeding into the feed sort due to the join fan-out.

### 4. Supply
| Source | Total jobs | Passing HardFilter | Unlabeled+Passing |
|--------|-----------|-------------------|-------------------|
| arbeitnow | 1,445 | 72 | 25 |
| remotive | 19 | 11 | 0 |
| **Total** | **1,464** | **83** | **25** |

- Only 1 scoring run captured (Oct 9, all 1,464 jobs scored in one batch). Cannot estimate per-daily-run yield yet.
- 25 unlabeled passing jobs available right now. At ~20 labels/session, M1 (150 labels) needs 64 more → ~3–4 labeling sessions assuming daily fetches add ~10–15 new passing jobs each.
- `raw_job_listings` has 1,599 rows (135 more than `jobs` — those were fetched but failed normalization or deduplication). FEED.md "1512 scanned" figure came from a previous run when `raw_job_listings` had 1,512 rows; the export_feed total reflects `len(rows)` from the join query, not the raw table count.

### 5. Label Hygiene
- **86 labels total**; 17 company+title pairs are duplicated (one job cross-posted on .ch and .fr Arbeitnow, labeled twice from different batches).
- **58 of 86** labeled jobs are current HardFilter survivors (reason_code = NULL).
- **43 of 86** have a Laya score in `laya_job_scores`.
- **Why calibration saw only 17**: Laya batch scoring (7.6-FULL) ran on the 43 jobs meeting the strict eligibility filter at scoring time (`is_remote AND detected_language='en' AND nepal_accessible=true`). At that time only 17 of those 43 had human labels → those 17 fed calibration. The remaining 69 labeled jobs had no Laya score (either not eligible or labeled after batch scoring ran).

---

- **6e EVALUATION DONE** (Oct 11 2026) — evaluate_scoring.py rewritten per TRAINING.md §7. Survivors (n=11, pos=3): recall@20=1.000, precision@10=0.300, PR-AUC=0.232. All labeled (n=69, pos=6): recall@20=0.667. Committed 3b51817.

---

## 6f Sources Research (Oct 11 2026)

### Himalayas
Source read: `https://himalayas.app/api` (fetched 2026-10-10, page says "Current as of Oct 10, 2026")

**Rate limit** (quoted from FAQ): *"The API is rate limited. Exceeding the limit returns a 429 Too Many Requests response. Data is cached every 24 hours, so polling more than once per day provides no benefit. Contact hi@himalayas.app for higher limits."* No numeric requests-per-minute published.

**Page size**: *"As of 24th March 2025, we have reduced the maximum limit to 20 jobs per request to improve performance and reliability."* Max `limit=20` per request; use cursor pagination.

**Location fields** on each job:
- `locationRestrictions` (optional array): *"Country where candidates must be located, there can be more than one"*
- `timezoneRestrictions` (optional array): *"Time zone (UTC) where candidates must be located, there can be more than one"*

**Attribution**: *"If you display Himalayas job data on your own website or application, include a visible link back to himalayas.app and mention that the data is sourced from Himalayas."* Also: *"Please do not submit Himalayas jobs to third-party websites, including but not limited to Jooble, Neuvoo, Google Jobs, or LinkedIn Jobs."*

**Proposed accessibility mapping for `locationRestrictions` / `timezoneRestrictions`:**

| API value | Mapping | Rationale |
|---|---|---|
| `locationRestrictions` absent / null | `UNKNOWN` | No geo restriction stated |
| Contains "Worldwide", "Global", "Anywhere" | `ACCESSIBLE` | Explicit no-restriction signal |
| Contains "Nepal" | `ACCESSIBLE` | Explicit mention |
| Contains only APAC / Asia (no Nepal) | `UNKNOWN` | Region might include Nepal; cannot confirm |
| Contains only specific countries excluding Nepal (e.g. "USA", "Germany") | `BLOCKED` | Confirmed exclusion |
| `timezoneRestrictions` absent / null | no change | Defer to `locationRestrictions` |
| `timezoneRestrictions` includes UTC+5:30 or UTC+5:45 | `ACCESSIBLE` (upgrade) | Nepal time zone explicitly OK |
| `timezoneRestrictions` includes only UTC-5 to UTC+2 ranges | `BLOCKED` | Nepal (UTC+5:45) outside window |

---

### Jobicy
Source read: `https://jobicy.com/api/v2/remote-jobs` (live JSON response, fetched 2026-10-11). Docs page `https://jobi.cy/apidocs` returned 403.

**Friendly notice** in API response (verbatim): *"Thanks for using Jobicy API! Please ensure Jobicy is clearly credited with a direct link to the source, and all application buttons redirect to the original job URL provided in this feed. That's all! You might be building something amazing, we wish you the best of luck!"*

**Rate limit**: No numeric limit published in the JSON response or accessible docs. Fair use implied; 429 returned on excess. (Source: web search cross-check + observed API response structure.)

**Key fields**:
- `jobGeo`: single string geo restriction per job (e.g. `"USA"`, `"Worldwide"`, `"Australia"`)
- `count` param: max 50 jobs per request (default 20 per observed `jobCount` in response)
- No authentication required

**Proposed accessibility mapping for `jobGeo`:**

| `jobGeo` value | Mapping |
|---|---|
| `"Anywhere"`, `"Worldwide"`, `"Global"`, `""` (empty) | `ACCESSIBLE` |
| `"Nepal"` | `ACCESSIBLE` |
| `"APAC"`, `"Asia"` | `UNKNOWN` |
| Single country NOT Nepal (e.g. `"USA"`, `"Australia"`) | `BLOCKED` |
| Multi-country list not containing Nepal | `BLOCKED` |

---

### Merojob
Source read: `https://merojob.com/terms-and-conditions/` (fetched 2026-10-11). `robots.txt` previously confirmed: empty `Disallow`, `ai-train=no`.

**Scraping prohibition** (verbatim from Section 3.E "License to use the Site"): *"Data scraping, automated bots, or other tools for collecting or mining personal or professional data"* are explicitly listed under "this license does not allow". No public API exists.

**Governing law**: *"These terms and conditions are governed by and construed in accordance with the laws of the Federal Democratic Republic of Nepal. You agree, as we do, to submit to the exclusive jurisdiction of the courts in Kathmandu."* (Section 3.T)

**Conclusion**: Merojob cannot be scraped. No extractor should be built. `robots.txt` `ai-train=no` means job description text **must never be used for fine-tuning** even if somehow accessed. Record this as a hard rule in TRAINING.md.

---

## 7.7b Labeling Protocol & Schema Hygiene (Oct 13 2026)
- **Migration 007**: Added `sampling_stratum VARCHAR(32)` and `label_guideline_version VARCHAR(16)` to `laya_labels` table.
- **Stratified Export (`scripts/export_for_labeling.py`)**:
  - Implemented 3-stratum sampling allocation: 40% `random`, 30% `high_match_scorer`, 30% `laya_uncertainty` (falls back to random when no Laya-scored jobs are available).
  - Explicitly excluded Laya score & confidence columns from output CSV to prevent anchoring bias during human labeling.
  - Added `sampling_stratum` and `label_guideline_version` (defaulting to `"v1"`) columns to CSV.
- **Ingestion (`scripts/ingest_labels.py`)**: Updated to ingest `sampling_stratum` and `label_guideline_version` into database columns.
- **Test Suite**: Added `tests/test_export_labeling.py` with 9 regression tests covering allocation math, stratum ranking, Laya column exclusion, and fallback behavior. All 9 tests passing.

---

## Phase 8 / 9: Pipeline Observability, Leak Audit & ATS Yield Test (Oct 18 2026)

### 1. Pipeline Leak Audit (`scripts/funnel_report.py`)
- Added read-only `scripts/funnel_report.py` reporting per-source funnel metrics over configurable look-back windows (`--days N`, default 7):
  `Fetched (source_runs) -> New (jobs inserted) -> Passed HardFilter -> Scored >= 60`.
- Split rejection reasons into two explicit side-by-side columns: **HardFilter Rejections** (`NOT_REMOTE`, `NON_ENGLISH`, `REGION_LOCKED`, `NON_TECHNICAL`, `UNPAID`) and **MatchScorer Rejections** (`SENIOR`, `NO_TECH_SIGNAL`, `LOW_SCORE`, `PLACEHOLDER`).
- **Audit Findings**:
  - **Arbeitnow** was identified as the largest intake waster in the pipeline: 1,443 fetched, 1,201 new, only 51 passed HardFilter (95.7% rejection rate, 0.08% yield, only 1 job scored $\ge 60$).
  - Verified live that Arbeitnow's public API ignores `?remote=true` (still returns ~89% non-remote on-site German roles).
  - Reduced Arbeitnow intake in `src/pipeline.py` from `max_pages=2` (600 jobs) to `max_pages=1` (300 jobs), cutting raw non-remote waste by 50% without dropping fresh listings.
  - **Jobicy** (75.5%) and **Himalayas** (72.5%) have severe `REGION_LOCKED` leak rates due to US/Americas residency requirements.
  - **We Work Remotely** demonstrated the highest intake quality among aggregators (82.6% HardFilter pass rate, 2.1% final yield).

### 2. Observability & Orchestrator Telemetry (`source_runs`)
- **Migration 009 (`009_source_runs.sql`)**: Created `source_runs` table `(id, run_id, source, started_at, fetched, inserted, skipped, error)` with index on `(source, started_at)`. Reversible via `DROP TABLE IF EXISTS source_runs`.
- **Telemetry Integration**: Added `JobRepository.record_source_run` and wrapped extractor executions in `JobPipeline.run_extractors` to record execution timestamps, batch counts, duplicate skips, and errors under a unified pipeline `run_id`.
- **Historical Fallback**: `funnel_report.py` reads `Fetched` directly from `source_runs`, seamlessly falling back to `raw_job_listings` for earlier historical days prior to migration 009 and reporting fallback status.
- **Scorer Summary Bug Fix**: Fixed `score_all_jobs()` in `src/matching/service.py` to return `"total_scored": len(passed_jobs)`, resolving a bug where `run_daily.py` printed `Scored 0 jobs`.

### 3. ATS Company Board Yield Dry-Run (`scripts/dry_run_yield_test.py`)
- Evaluated 10 high-signal company boards across Greenhouse, Lever, and Ashby without writing to the database:
  - **Greenhouse**: `gitlab`, `givedirectly`
  - **Lever**: `curai`, `peerspace`
  - **Ashby**: `openai`, `elevenlabs`, `supabase`, `omnea`, `runway-ml`, `duck-duck-go`
- **Existence Verification**: 0 HTTP 404s (all 10 company boards exist and returned HTTP 200).
- **Yield Results (1,414 jobs total, 637 passed HardFilter, 29 scored $\ge 60$)**:
  - Combined yield across the 10 boards: **2.05%** (~25× higher than Arbeitnow's 0.08%).
  - **Boards Beating 2% Yield**:
    1. **Supabase** (`ashby`): **12.96% yield** (7 / 54 jobs) — exceptional remote engineering concentration.
    2. **OpenAI** (`ashby`): **2.09% yield** (17 / 813 jobs) — massive scale with 421 jobs clearing HardFilter.
    3. **Runway ML** (`ashby`): **2.04% yield** (1 / 49 jobs) — 41 jobs passed HardFilter.
    4. *(ElevenLabs near-miss: 1.92% yield, 3 / 156 jobs).*

---

### 4. Targeted ATS Board Extractor Implementation (Task 9.7)
- Built `src/extractors/ats_board.py` featuring `ATSBoardExtractor` supporting Greenhouse, Lever, and Ashby job boards.
- Configurable via `config/ats_boards.json` (declarative list of boards, slugs, and platforms).
- Initial production roster: `supabase` (ashby), `elevenlabs` (ashby), `gitlab` (greenhouse). OpenAI and Runway ML were verified then **disabled** (`enabled: false`) because they do not hire globally/junior-friendly.
- **Phase 12 expansion** (2026-10-29): Added 5 more boards — `canonical` (greenhouse, 314 jobs), `mozilla` (greenhouse, 118 jobs), `elastic` (greenhouse, 404 jobs), `grafanalabs` (greenhouse, 131 jobs), `wikimedia` (greenhouse, 15 jobs). **982 new jobs ingested.** Total active ATS boards: **8**.
- Added per-platform normalizers (`transform_ats_greenhouse`, `transform_ats_lever`, `transform_ats_ashby`) and dispatched via `ats:*` in `src/models/transformers.py`.
- Integrated directly into `JobPipeline.run_extractors()` with individual `source_runs` telemetry logging.
- Verified live: fetched 1,304 items across the 5 target boards with 100% successful transformation, zero errors, and direct employer application links.

### 5. Direct ATS Application Link Extraction & Backfill (Task 9.8)
- Added `extract_direct_ats_link()` to `src/models/transformers.py` to recognize direct application links (`job-boards.greenhouse.io`, `grnh.se`, `jobs.lever.co`, `jobs.ashbyhq.com`, `apply.workable.com`).
- Resolved Hacker News HTML entity decoding (`&#x2F;`), unlocking direct apply link extraction for 47 / 53 HN listings that previously fell back to generic thread comments.
- Wired automatic direct ATS promotion into `transform_raw_listing`: if an aggregator description embeds a direct ATS link, `apply_url` is automatically upgraded from the aggregator link to the direct ATS application form.
- Created and executed `scripts/backfill_direct_ats_links.py`, successfully upgrading 15 existing aggregator/thread jobs in the PostgreSQL database to direct ATS URLs.

### 6. Aggregator Geo-Filter Tightening (Task 9.9)
- Tested server-side geo filtering against Jobicy and Himalayas APIs:
  - **Jobicy**: Proved live that `?geo=worldwide` returns HTTP 400 (not supported by free API).
  - **Himalayas**: Proved live that location query parameters (`location=worldwide`, etc.) are silently ignored.
- Implemented client-side geo pre-filtering:
  - `src/extractors/jobicy.py`: skips single-country jobs (~98% drop rate), keeping only worldwide, remote, or blank listings.
  - `src/extractors/himalayas.py`: skips jobs with non-empty single-country `locationRestrictions` (~75% drop rate).
  - Eliminates upstream noise before staging into `raw_job_listings` and database.

### 7. Eligibility Filter Rebuild & Allowlist Architecture (Oct 19 2026)
- **Problem**: 814 OpenAI listings and numerous foreign hybrid/on-site postings leaked through the system because the filter relied on enumerating negative edge cases (blocklist) rather than strict allowlists.
- **Mission**: Flipped the filter to **default deny**:
  - **Gate 1 (Work Location)**: PASS only if on-site/hybrid in Nepal, or tagged exactly `worldwide`, `global`, `anywhere`, `apac`, `asia`, `south asia`, `nepal`, or remote at a verified global hiring company with international contractor payout. Fails all foreign hybrid/on-site (`NOT_REMOTE`), US/EU/UK/Americas locks, citizenship requirements, and W-2 restrictions (`NOT_ELIGIBLE_REGION` / `REGION_LOCKED`).
  - **Gate 2 (Seniority & Degree)**: Disqualifies titles containing `BLOCKED_SENIORITY` (`senior`, `staff`, `principal`, `lead`, `leader`, `manager`, `head`, `vp`, `director`) as `TOO_SENIOR` (**420 jobs blocked**). Disqualifies hard degree requirements (`DEGREE_HARD_RE`) and $\ge 3$ years experience (`YEARS_RE`) as `DEGREE_OR_EXP` (**128 jobs blocked**).
  - **Gate 3 (Clearance & Regulatory Fit)**: Disqualifies defense, military, ITAR, and government security clearance roles.
  - **Gate 4 (Pay & Practicality)**: Disqualifies unpaid/equity/commission-only roles and US Pacific core hour overlap ($\ge 6$h).
  - **Gate 5 (Skill Fit)**: Strong match on junior ML/AI, Python/Django, React/Next.js, Flutter.
- **OpenAI Leak Resolution**: Reprocessed all 1,298 raw ATS rows. **0 OpenAI jobs** in `job_matches` (571 stored in `jobs` but 100% disqualified from matches and feed). Disabled non-worldwide boards (`openai`, `runway-ml`) in `config/ats_boards.json`.
- **Zero-Scraping Compliance for Nepal**: Established strict prohibition against crawling Nepali sites (Merojob, Kumarijob, etc.). Implemented `scripts/import_manual_jobs.py` for local JSON/CSV entry with `source = 'manual:nepal'`.
- **Audit Schema Migration 010**: Added `gate_failed`, `workplace_type`, `country_restriction`, `seniority`, `degree_required`, `years_required`, `pay_type`, and `tz_overlap_required` to `laya_labels`. Updated `tools/app.py` to persist all audit fields.
- **Test Suite**: 150 passing tests.

### 8. Phase 11: Pipeline Overhaul & Operationalization (Late Oct 2026)
- **Step 1: Data Hygiene Prerequisites** (Commit `be83c9d`):
  - Cross-strata deduplication in `scripts/export_for_labeling.py` preventing duplicate `job_id` exports across random, match scorer, and uncertainty strata.
  - Mojibake cleaning in `src/models/transformers.py` and `scripts/export_labeled_descriptions.py` stripping `Â `, `\xc2\xa0`, and corrupted utf-8 characters.
  - Added `is_unparseable_hn_title()` to classify location/timezone strings ("Santa Clara, CA", "GMT-2", "Hacker News Role") as `exclude_reason="unparseable_title"`.
  - Stamped 50 Runway ML jobs as `exclude_reason="board_not_junior_friendly"`.
  - Added migrations `011_widen_label_stratum.sql` and `012_add_exclude_reason.sql`.
- **Step 2: Pool Generator & Intake Pagination** (Commit `0bdaf50`):
  - Created `scripts/make_labeling_batch.py`: Title-rule scoring (+1 for developer/junior/python, -2 for senior/manager/support), 70% rule / 30% random pool, company cap (max 3/batch, drops historical $\ge 5$), `v2_role_fit_only` stamping.
  - Fixed Himalayas pagination to 5 pages (`offset=0, 20, 40, ...`) and Jobicy to `count=100` (removed invalid `page` param).
  - Verified 10 public company ATS boards on Greenhouse and Ashby with HTTP 200 (Canonical, Mozilla, Elastic, Grafana Labs, PostHog, Linear, Cohere, Replit, GitBook, Wikimedia).
- **Step 3: Learned Title Role-Type Classifier** (Commit `0219404`):
  - Trained char n-gram (3-5) TF-IDF + LogisticRegression on human + weak labels (`src/matching/title_classifier.py` and `scripts/train_title_classifier.py`).
  - Claimed 5-fold Grouped CV result: **0.872 recall** vs Blocklist **0.745** (+12.7%) with **0.000 FPR on `good_fit`**. No committed report/artifact reproduces these numbers, and the current checkpoint predates the DB rebuild — treat as unverified.
  - Integrated into `src/matching/scorer.py` as soft score penalty.
- **Step 4: Ranker Model with Strict Safety Gates** (Commit `cfcfa25`):
  - Implemented `scripts/train_ranker.py`: Joined bookkeeping + training jsonl on `job_id`, strictly filtering `v2_role_fit_only` and unexcluded rows.
  - Safety gates: Refuses to train or evaluate when $< 150$ v2 labels or $< 30$ role-fit `good_fit` positives. Refuses folds with $< 3$ positives.
  - Added ElevenLabs ablation and promotion rule (lower CI $> 0.70$ and $\ge +0.05$ over rule baseline).
- **Step 5: Interactive Feedback Dashboard** (Commit `43ae779`):
  - Implemented `app.py`: Clean browser UI on port 5000 with Feed tab (ranked by title-rule score), Rejected tab (grouped by failure reason with trigger snippet), instant writes to `laya_labels` stamped with `label_guideline_version="v2_role_fit_only"`, and live header tracking.
- **Step 6: Scheduled Daily Runner** (Commit `e58fb64`):
  - Implemented `scripts/run_scheduled.py` protected by `data/pipeline.lock`, rotating log in `logs/scheduled_run.log`, recording to `source_runs`.
  - Created PowerShell installer (`scripts/install_schedule.ps1`) for Windows Task Scheduler daily runs at 06:00 AM, and Docker setup guide (`docs/scheduled_run_docker.md`).
- **Step 7 & Task 7.9: Audit & Label Reporting**:
  - Implemented `src/matching/eligibility.py` (Task 8.5) and `scripts/report_labels.py` (Task 7.9).

---

## 🛠️ Next Action Items

1. **Label the recovered junior roles first**: restart `.venv/bin/python app.py`. The top of the Feed is now Canonical's worldwide junior/graduate engineering roles — Graduate Software Engineer (74.8), Junior Ubuntu Software Engineer (72.4), Associate Linux Support Engineer (71.2), Junior Linux Kernel Engineer (71.2). These were previously hidden by the ATS `Home based - Worldwide` remote-classification bug.

2. **Review the pending Ollama suggestions** (optional, lower priority): 22 suggestions are in `data/triage_suggestions_20261106_2017.json` (15 still pending):
   ```bash
   .venv/bin/python scripts/ingest_triage_suggestions.py data/triage_suggestions_20261106_2017.json
   ```

3. **Continue labeling**: gate is **30/150 v2 labels** and **1/30 `good_fit`** as of 2026-11-09. After labeling, run `.venv/bin/python scripts/export_labeled_descriptions.py` to regenerate `data/labeled_jobs_*.jsonl` before `train_ranker.py` / `make_splits.py`.

4. **Calibrate, then train**: once there are ≥150 v2 labels, run `scripts/calibrate_laya.py --version v4` and verify `ece_computed=true` with non-zero `n_eval` before trusting it. `v3` is a no-op. Then, once there are ≥30 `good_fit`, run `scripts/train_ranker.py` and `scripts/train_laya.py --version v3`.

5. **Source roster (26 total)**: 8 aggregators (Arbeitnow, Remotive, Himalayas, WWR, Remote OK, Jobicy, Hacker News, Working Nomads) + 18 ATS boards (including Canonical, Supabase, ElevenLabs, Railway, PostHog, Bitwarden, Zapier). The ATS remote fix recovered 96 Canonical worldwide roles; keep prioritizing ATS boards with explicit worldwide/global locations.

6. **Known follow-ups**: (a) root `app.py` does not persist the 5 gate audit columns; (b) `can_be_executed_globally` can override explicit non-Nepal locations; (c) `ai/ml` matches bare "AI"; (d) committed `evals/gold/gold_latest.csv` still has 7 excluded rows; (e) retire duplicate `tools/app.py`; (f) after `usermod -aG docker`, log out/in before `docker` works without sudo.
