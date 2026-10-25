# Project Progress

## ⚡ Quick Commands Cheatsheet

| Task | PowerShell Command | Note |
| :--- | :--- | :--- |
| **🌐 Web Dashboard** | `& .\.venv\Scripts\python.exe tools/app.py` | Open **http://localhost:5000** in browser |
| **🚀 Generate FEED.md** | `& .\.venv\Scripts\python.exe scripts/export_feed.py` | Exports top matched jobs to `FEED.md` |
| **🔄 Run Daily Pipeline** | `& .\.venv\Scripts\python.exe scripts/run_daily.py` | Fetch → Normalize → MatchScorer → Update FEED.md |
| **🧠 Score Jobs with Laya** | `& .\.venv\Scripts\python.exe scripts/score_jobs.py` | Batch scores eligible jobs using Laya neural decision engine |
| **📋 Interactive CLI Review** | `& .\.venv\Scripts\python.exe scripts/review_jobs.py` | Review jobs (`y/n/s/q`), saves to `data/reviewed_jobs.json` |
| **📥 Export Labeling Batch** | `& .\.venv\Scripts\python.exe scripts/export_for_labeling.py --no-rescore --batch-size 30` | Creates `data/labeling_batch_YYYYMMDD.csv` |
| **📤 Ingest Human Labels** | `& .\.venv\Scripts\python.exe scripts/ingest_labels.py data/labeling_batch_YYYYMMDD.csv` | Ingests CSV into `laya_labels` in Postgres |
| **📦 Export Labeled Datasets** | `& .\.venv\Scripts\python.exe scripts/export_labeled_descriptions.py` | Exports bookkeeping and clean training JSONL |
| **📊 5-Fold GroupKFold Splits** | `& .\.venv\Scripts\python.exe scripts/make_splits.py` | Generates 5 company-stratified cross-val folds in `data/splits/` |
| **🧹 Backfill Clean Descriptions** | `& .\.venv\Scripts\python.exe scripts/backfill_clean_descriptions.py` | Cleans HTML/mojibake in `jobs.description_text` (payloads untouched) |
| **🌍 Backfill Detected Languages** | `& .\.venv\Scripts\python.exe scripts/backfill_detected_language.py` | Re-evaluates language via title+first 500 chars & updates DB |
| **🔍 Audit Language Transitions** | `& .\.venv\Scripts\python.exe scripts/audit_language_changes.py` | Audits French/German/English transitions and false positives |
| **🎯 Calibrate Laya** | `& .\.venv\Scripts\python.exe scripts/calibrate_laya.py --version v3` | Fits temperature scaling on human labels (ECE enabled at 150 labels) |
| **🧠 Train Laya Head** | `& .\.venv\Scripts\python.exe scripts/train_laya.py --version v2` | Fine-tunes decision head with frozen ModernBERT encoder |
| **📈 Pipeline Funnel Report** | `& .\.venv\Scripts\python.exe scripts/funnel_report.py --days 7` | Source-level funnel stats (fetched → new → passed HF → scored ≥60) |
| **🇳🇵 Manual Nepal Import** | `& .\.venv\Scripts\python.exe scripts/import_manual_jobs.py -f jobs.json` | Ingests user-supplied JSON/CSV (NO web scraping) |
| **🧪 ATS Yield Dry-Run** | `& .\.venv\Scripts\python.exe scripts/dry_run_yield_test.py` | In-memory yield test across 10 company ATS boards (no DB writes) |

---

## Current State (Oct 19 2026)

### Infrastructure & Sources
- Phase 1 through Phase 6, Phase 9, and Phase 10 complete.
- **Candidate Sources Built & Ingested**: 4,596 unique jobs in PostgreSQL across 8 sources (Arbeitnow, Remote OK, We Work Remotely, Jobicy, Hacker News, Himalayas, Remotive, ATS Boards).
- **Five-Gate Allowlist HardFilter Active**: Disqualifies non-remote foreign jobs (`NOT_REMOTE`), region locks outside Nepal (`NOT_ELIGIBLE_REGION` / `REGION_LOCKED`), senior roles (`TOO_SENIOR`), and hard degree / 3+ year experience requirements (`DEGREE_OR_EXP`).
- **OpenAI Leak Purged**: 0 OpenAI jobs in `job_matches`. All 571 stored OpenAI jobs disqualified due to SF/NYC hybrid presence.
- **Zero-Scraping Nepal Ingestion**: Built `scripts/import_manual_jobs.py` for candidate JSON/CSV imports. Zero web scraping of Nepali sites.
- **In-Browser Labeling Dashboard (`tools/app.py`)**: Persists 5-gate audit schema (`gate_failed`, `workplace_type`, `country_restriction`, `seniority`, `degree_required`, `years_required`, `pay_type`, `tz_overlap_required`) via migration 010.
- CUDA enabled: `torch 2.5.1+cu121`, RTX 2050 confirmed. Test suite: **150 passing tests**.

### Labeling & Model Training (as of Oct 25 2026)
150 distinct human-labeled jobs (203 total label events) in `laya_labels`:

| Label | Count (Total Rows) | Unique Jobs |
|-------|-------|---|
| `bad_fit` | 150 | 115 |
| `maybe` | 22 | 16 |
| `good_fit` | 31 | 19 |
| **Total** | **203** | **150** |

- **Milestone Unlocked & Completed**:
  - **Task 7.8a Temperature Calibration (`v3`)**: Completed on 150 unique jobs (1,650 question records) on CUDA with full ECE evaluation enabled (`config/laya_temperatures_v3.json`).
  - **Task 7.8b Decision Head Fine-Tuning (`v2`)**: Implemented full PyTorch neural decision head atop frozen ModernBERT-large (1024-dim representations) with class-weighted CrossEntropy and 120/30 train-val split. Checkpoint saved to `models/laya_head_v2/head_weights.pt` with metadata in `models/laya_head_v2/checkpoint_meta.json`.
  - **Regression Test Suite**: 150 passed in 15.6s.

### Evaluation & Inference Latency Note (`evaluate_scorers.py`)
- Running `scripts/evaluate_scorers.py` evaluates labeled jobs through rule-based `MatchScorer` and neural `LayaScorer`.
- On CPU, Laya inference requires ~15–20 seconds per job description.
- Running on CUDA (`device="cuda"`) reduces this to ~40ms per job.

The ~11% `good_fit` rate reflects the source bias (Arbeitnow, Remotive skew senior/US/EU). This is not a labeling error.

### Key Decisions Recorded (Oct 10-19 2026)
See `TRAINING.md` for full rationale. Summary:

1. **Default-Deny Allowlist**: Jobs are blocked by default unless explicitly tagged Worldwide, Global, Anywhere, APAC, South Asia, or Nepal.
2. **Two datasets**: MEASURE/CALIBRATE set preserves natural distribution (never rebalanced). TRAIN set (7.8b only, train split only) may be rebalanced.
3. **Training gated on both** total labels >= 150 AND `good_fit` >= 30 (`min_positive_labels`, configurable, default 30).
4. **Binary primary view**: `good_fit` vs not. `maybe` = not good_fit. 3-class view reported as secondary.
5. **Evaluation**: repeated stratified grouped k-fold; metrics are precision@k, recall@k, PR-AUC with bootstrap CIs. Primary metric is `recall@20`. Never report raw accuracy.
6. **Labeling queue strata**: 40% random, 30% high MatchScorer, 30% Laya-uncertainty (last stratum deferred until 7.8a calibration is done).
6. **No uncalibrated Laya gating**: raw probabilities (~0.10-0.26) are stored only; never used to discard jobs or decide labeling priority.
7. **Label hygiene**: Laya columns must be hidden from the export CSV; accepting Laya's suggestion is not allowed. `label_guideline_version` must be recorded per row.
8. **`noul` correction**: it is Laya's boolean primitive (P(yes)), not a nuance/variance signal. Checkpoint is uncalibrated until 7.8a; never call outputs "calibrated confidence" before that.

---

## What's Broken / Incomplete (Phase 8 Issues from tmp/4.txt)
- **DB Connection Timeout**: Pipeline lacks fast-fail on database connection (`connect_timeout=5`); when Docker Desktop is stopped, `run_daily.py` hangs for 4 minutes before failing with socket timeout.
- **Hacker News Field-Length Parser Bug**: Comments lacking a clear "Company | Role | Location" header (e.g., #49924674) overflow the 255-character `VARCHAR(255)` constraint on `title`/`company_name`. Needs fallback title and string truncation to 255 chars in normalization.
- **Eligibility Discrepancy (98 vs 161, 287 vs 546)**:
  - `score_jobs.py` queries `WHERE detected_language = 'english' AND nepal_accessible = true` (546 jobs).
  - `export_for_labeling.py` queries `WHERE accessibility IN ('ACCESSIBLE', 'UNKNOWN')` (267 jobs).
  - Neither script executes `HardFilter`, leaking ITAR defense roles (e.g. Swarmaero), US-citizen-only restrictions, and non-technical jobs (e.g. Account Executives) into Laya scoring and the labeling queue.
  - Solution: Create one shared `src/matching/eligibility.py` module backed by `HardFilter.apply`.
- **Reachability Field Fragmentation**: Codebase reads from legacy `nepal_accessible` and `accessibility` columns alongside `reachable_from_nepal` & `reachable_reason`. Must unify onto `reachable_from_nepal` as single source of truth.
- **Title & Seniority Gaps**: Out-of-range senior titles (Senior, Staff, Principal, Lead, VP, Director) and non-engineering titles (Recruiter, Sourcer, FP&A, Accounts Payable) pass through to scoring unless explicitly caught.
- **`laya_uncertainty` Export Stratum**: Picks senior, score-0 jobs because Laya is not yet calibrated. Must fall back to the random pool until calibration is verified.
- **Orchestrator Code Duplication**: `JobPipeline.run_extractors` repeats per-source try/except blocks; must be refactored into a declarative `SOURCES` registry with per-source error isolation.
- **7.8a PROVISIONAL**: Calibration ran on 103 unique labeled jobs (1,133 records). ECE evaluation skipped until M1 (150 labels).
- **Task 7.8b BLOCKED**: Needs M3 (150+ labels, 30+ `good_fit`).
- **Task 7.9 NOT STARTED**: Report script (`scripts/report_labels.py`).

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
- Initial production roster: `supabase` (ashby), `openai` (ashby), `runway-ml` (ashby), `elevenlabs` (ashby), `gitlab` (greenhouse).
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

---

## 🛠️ Potential Things We May Need to Fix (Backlog / Roadmap)

1. **Unified Eligibility Module (`src/matching/eligibility.py`)** [Task 8.5]:
   - Create single authoritative candidate eligibility function wrapping `HardFilter.apply` to eliminate divergence between `run_daily.py`, `score_jobs.py`, and `export_for_labeling.py`.
2. **Single Reachability Field** [Task 8.6]:
   - Retain `reachable_from_nepal` & `reachable_reason` as the only reachability fields; eliminate legacy reads/writes of `nepal_accessible` and `accessibility`.
3. **Title & Seniority Hard Filter** [Task 8.7]:
   - Extend `non_technical_title_blocklist` and add configurable seniority title checks (`SENIORITY_TITLE`) with zero-regression check on human labels.
4. **Fast-Fail DB Timeout & HN String Truncation** [Task 8.2 & 8.3]:
   - Add `connect_timeout=5` to connection pool to prevent 4-minute hangs when Docker is stopped.
   - Truncate long Hacker News comment titles/company names to 255 chars in normalization to prevent schema violations.

---

## Next Step
Proceed with Phase 8 architecture harmonization: building `src/matching/eligibility.py` (Task 8.5) and retiring legacy reachability columns (Task 8.6).

