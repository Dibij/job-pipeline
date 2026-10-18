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
| **🎯 Calibrate Laya** | `& .\.venv\Scripts\python.exe scripts/calibrate_laya.py --version v1` | Fits temperature scaling on human labels |

---

## Current State (Oct 15 2026)

### Infrastructure & Sources
- Phase 1, Phase 2, Phase 3, Phase 5, and Phase 6 complete.
- **Candidate Sources Built & Ingested**: 2,609 unique jobs in PostgreSQL across 7 sources (Arbeitnow: 2,307, Remote OK: 97, We Work Remotely: 86, Jobicy: 50, Hacker News: 30, Himalayas: 20, Remotive: 19).
- **Tri-State Reachability**: Migration 008 applied (`reachable_from_nepal` & `reachable_reason`). Distribution: 90 `accessible`, 218 `unknown`, 2,301 `blocked`. FEED.md filters out all blocked roles.
- **In-Browser Labeling Dashboard (`tools/app.py`)**: Built interactive labeling, 1-5 star rating, and notes directly on cards via `POST /api/label`, eliminating the Excel/CSV manual loop. Supports filtering by `⚡ Unlabeled Only`.
- CUDA enabled: `torch 2.5.1+cu121`, RTX 2050 confirmed. Test suite: 144 passing tests.

### Labeling (as of Oct 15 2026)
103 unique human-labeled jobs (127 total label events) in `laya_labels`:

| Label | Count | % |
|-------|-------|---|
| `bad_fit` | 95 | 74.8% |
| `good_fit` | 18 | 14.2% |
| `maybe` | 14 | 11.0% |

- **Strata Breakdown**: 86 legacy batch labels, 12 `random`, 9 `high_match_scorer`, 9 `laya_uncertainty`, 11 `web_ui` (labeled directly in-browser).
- **Milestone Progress**: Crossed 100 labeled jobs. `good_fit` count is 18 (approaching the M1 target of 30 positive labels required for fine-tuning).

### Evaluation & Inference Latency Note (`evaluate_scorers.py`)
- Running `scripts/evaluate_scorers.py` evaluates 127 labeled jobs through rule-based `MatchScorer` and neural `LayaScorer`.
- On CPU, Laya inference requires ~15–20 seconds per job description.
- For 127 jobs: $127 \times 15\text{s} \approx 1,900\text{s} \approx 32\text{ minutes}$. Because the evaluation loop had no per-iteration logging, the terminal appears silent/stuck between model load and final summary table output. Running on CUDA (`device="cuda"`) reduces this to ~1–2 minutes.

The ~10% `good_fit` rate reflects the source bias (Arbeitnow, Remotive skew senior/US/EU). This is not a labeling error.

### Key Decisions Recorded (Oct 10 2026)
See `TRAINING.md` for full rationale. Summary:

1. **Two datasets**: MEASURE/CALIBRATE set preserves natural distribution (never rebalanced). TRAIN set (7.8b only, train split only) may be rebalanced.
2. **Training gated on both** total labels >= 150 AND `good_fit` >= 30 (`min_positive_labels`, configurable, default 30).
3. **Binary primary view**: `good_fit` vs not. `maybe` = not good_fit. 3-class view reported as secondary.
4. **Evaluation**: repeated stratified grouped k-fold; metrics are precision@k, recall@k, PR-AUC with bootstrap CIs. Primary metric is `recall@20`. Never report raw accuracy.
5. **Labeling queue strata**: 40% random, 30% high MatchScorer, 30% Laya-uncertainty (last stratum deferred until 7.8a calibration is done).
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

## Next Step
Proceed with **Task 7.9** — build report script (`scripts/report_labels.py`) for per-source counts/rates, per-stratum breakdown, and small-sample caveat warnings.
