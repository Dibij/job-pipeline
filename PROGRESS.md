# Project Progress

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

## Current State (Oct 10 2026)

### Infrastructure
- Phase 1, Phase 2, Phase 3, Phase 5, and Phase 6 complete.
- 1,194 unique jobs in PostgreSQL (576 added Oct 9). MatchScorer re-run on all.
- CUDA enabled: `torch 2.5.1+cu121`, RTX 2050 confirmed.
- Task 5b.2 seniority fix and Task 5b.3 HardFilter complete.
- Task 7.1-7.7 Laya spike, JD extraction, truncation, typed questions, confidence gating, batch scoring, and labeling scaffolding all complete.
- Task 7.8a `calibrate_laya.py` rewritten (removed train/val split that caused n_eval=0).

### Labeling (as of Oct 10 2026)
86 human labels in `laya_labels`:

| Label | Count | % |
|-------|-------|---|
| `bad_fit` | 65 | 75.6% |
| `maybe` | 12 | 14.0% |
| `good_fit` | 9 | 10.5% |

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

## What's Broken / Incomplete
- **7.8a PROVISIONAL**: calibration ran on 43 unique labeled+scored jobs. Temperatures in `config/laya_temperatures_v1.json` are provisional. Re-run at M1.
- **`use_confidence_flag: false`** on disk — correct.
- **5c.1 Audit & 5c.2 Fixes DONE** (Oct 10 2026) — FEED.md deduplicated, NON_ENGLISH & NON_TECHNICAL & country-locks filtered, MatchScorer updated with section-targeted skill matching and seniority fallback, evaluate_scoring.py deduplicated.
- **5c.3 Supply Audit DONE** (Oct 10 2026) — Remotive category limit analyzed; 5 new candidate sources identified. `TRAINING.md` milestones updated.
- **6a ACCESSIBILITY ARCHITECTURE DONE** (Oct 11 2026) — Migration 006 applied, 3-state enum (`ACCESSIBLE`, `BLOCKED`, `UNKNOWN`), fixed transformers (never default to 'Worldwide'), 18 regression tests added (suite 99 green). Re-normalized 1,846 jobs: ACCESSIBLE 10, BLOCKED 1765, UNKNOWN 71. FEED.md split into Verified Accessible (1 job) and Location Not Stated (23 jobs).
- **6b FEED THRESHOLD & PLACEHOLDER FILTERING DONE** (Oct 11 2026) — Technical title signals in `cv_profile.json`, placeholder detection ('template', 'test'). Dropped 20 roles (1 PLACEHOLDER, 19 NO_TECH_SIGNAL without matched skills); kept 10 unknown + 1 accessible in FEED.md (including zero-skill tech roles like "Full-stack Engineer - Creative Agents"). 6 regression tests added (suite 105 green).
- **6c UNPAID FALSE POSITIVE FIX DONE** (Oct 11 2026) — Replaced bare keyword matching with contextual patterns (`unpaid internship/role/position`, `this role is unpaid`, `equity only`, etc.). Disqualified UNPAID count dropped from 53 to 1 true positive (`IndieKidz GmbH | (Unpaid) Mandatory Internship`); 52 false positives eliminated (Credit Wellness sales commission, Robinhood & Contabo volunteer day benefits). 5 regression tests added (suite 110 green).
- **6d ENRICHMENT PIPELINE INTEGRATION & BACKFILL DONE** (Oct 11 2026) — Verified that 42.1% of jobs (777/1846) had stored experience_level differences and 95.8% had tag changes. Wired `JobEnricher.enrich_job()` directly into `JobPipeline.process_staged()` and `JobRepository.upsert_job()`. Backfilled all 1,846 DB jobs via `scripts/backfill_enrichment.py`. Unspecified experience level dropped from 1,440 (78%) to 710 (38%); senior 346 -> 897, intern 36 -> 118, junior 15 -> 67, mid 9 -> 54. Suite: 110 green.
- Task 7.7b READY TO START — add `sampling_stratum` and `label_guideline_version` to schema, hide Laya columns in export CSV.
- Task 7.8b BLOCKED: needs M3 (500+ labels, 30+ `good_fit`).
- Task 7.9 NOT STARTED: report script.
- Task 6.4 (dashboard wired to hard-filter output) — not started.
- Task 6.4 (dashboard wired to hard-filter output) — not started.

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

## Next Step
Proceed with **Task 7.7b** — add `sampling_stratum` and `label_guideline_version` to the `laya_labels` schema and export script, and hide Laya columns from the labeling CSV to prevent anchoring bias.
