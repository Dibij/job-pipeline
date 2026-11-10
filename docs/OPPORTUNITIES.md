# Opportunity Intelligence — Multi-Source Extension

This document covers the opportunity-intelligence extension to the existing job
pipeline. It reuses the same ELT architecture, database, scoring stack, and
dashboard — there is no separate application.

## What it adds

| Capability | Where |
| :--- | :--- |
| Opportunity types (job / freelance / bounty / open_source) | `src/models/job.py` |
| Compensation + budget extraction | `src/opportunities/compensation.py` |
| Opportunity-specific scoring | `src/opportunities/scoring.py` |
| Deterministic scam-risk assessment | `src/opportunities/risk.py` |
| Human-reviewable outreach drafts | `src/opportunities/outreach.py` |
| Source freshness windows | `src/opportunities/freshness.py` |
| Python.org Jobs extractor | `src/extractors/python_org.py` |
| Reddit extractor (OAuth) | `src/extractors/reddit.py` |
| GitHub bounty/issues extractor | `src/extractors/github.py` |
| Dashboard filters + risk pills | `app.py` |
| Schema migrations | `src/db/migrations/015_*`, `016_*` |

## Data model

`NormalizedJob` gained backward-compatible fields. Existing job rows are
unaffected because every new column is nullable or defaulted:

```
opportunity_type           job | freelance | bounty | open_source   (default 'job')
compensation_type          salary | hourly | fixed_price | bounty | equity | unpaid | unknown
budget_min / budget_max    project budget for non-job types (NOT salary)
budget_currency            ISO code
deadline                   application/claim deadline
payment_verification_status  verified | unverified | none | unknown
scam_risk_score            0.0 – 1.0
risk_flags                 list of machine-readable flag names
risk_explanation           human-readable reasons
status                     open | closed | unknown
source_url                 canonical listing URL
last_seen_at               freshness tracking
outreach_draft             generated proposal text (human review only)
technical_angle            one-line technical approach
clarification_questions    questions to resolve before replying
```

**Fingerprint rule:** for `opportunity_type != 'job'` the type is folded into
the SHA-256 key so a GitHub bounty and a job posting with the same title/company
cannot collide. Job fingerprints are byte-identical to before, preserving all
existing rows and labels.

**Salary vs budget:** jobs keep `salary_min/salary_max`; freelance/bounty work
uses `budget_min/budget_max`. The two are never mixed.

## Scam-risk assessment

`assess_risk()` is deterministic and explainable. It never invents data; it
only inspects text that is actually present.

| Component | Trigger |
| :--- | :--- |
| `vague_description` | fewer than 15 words, or known vague phrases ("easy money", "no experience needed") |
| `unrealistic_rate` | an hourly rate above \$150/hr |
| `upfront_payment` | "pay first", "advance payment", "verification fee", … unless negated |
| `unpaid_test` | explicitly unpaid work with no portfolio context |

Negation is handled: "no upfront payment" and "pay first is not required" do
**not** raise the flag. Scores are capped at 1.0 and stored per-row.

## Scoring

`score_opportunity()` dispatches by type:

- `score_freelance` — skill coverage against the 12-skill profile plus budget
  plausibility; returns `good_fit` / `possible_fit` / `bad_fit` /
  `too_complex` / `insufficient_information`.
- `score_bounty` — returns `doable` / `stretch` / `too_complex` /
  `unpaid_portfolio_value` / `skip`. `doable` requires ≥ 2 matched skills
  and ≥ 15% coverage.

## Extractors

### Python.org Jobs (works out of the box)

Public RSS feed at `https://www.python.org/jobs/feed/rss/`. No credentials.

```bash
.venv/bin/python -c "from src.extractors.python_org import PythonOrgExtractor; \
  print(PythonOrgExtractor().stage_raw())"
```

### Reddit (requires OAuth)

Reddit returns **HTTP 403** for unauthenticated JSON requests. A script app is
required:

1. Visit <https://www.reddit.com/prefs/apps> → "create another app" → type
   **script**.
2. Set `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` in `.env`.
3. Optionally set `USER_AGENT` to a descriptive string.

Without credentials the extractor logs a warning and returns
`{"total": 0, "inserted": 0, "skipped": 0}` — the pipeline continues normally.

Monitored subreddits: `r/forhire`, `r/hiring`, `r/slavelabour`,
`r/beermoney`, `r/paidforwriting`.

### GitHub bounties / open source

Uses the GitHub Search API for `help-wanted`, `good-first-issue` and bounty
labels. Set `GITHUB_TOKEN` to raise the rate limit from 60 to 5,000 requests/hr.
Reward amounts are always `unverified` because GitHub does not escrow payment.

## Pipeline integration

`JobPipeline.run_extractors()` now registers `python_org` and `reddit`
alongside the existing sources. `process_staged()` performs, in order:

1. transform (`transform_raw_listing`)
2. enrichment (language, seniority, unpaid, reachability)
3. `assess_risk` → `scam_risk_score`, `risk_flags`, `risk_explanation`
4. for non-job types, `generate_outreach_draft` → stored draft,
   technical angle, clarification questions

## Dashboard

The Feed tab gained two filter rows:

- **Type**: ALL / Jobs / Freelance / Bounties / Open Source
- **Risk**: ALL / Low (<0.3) / Medium (0.3–0.8) / High (≥0.8), plus a
  **Fresh only** toggle (24 h for jobs, 15 min for gigs)

Each card shows opportunity-type, compensation, budget, payment-verification,
and risk pills, plus any risk flags. Sorting by **Scam Risk** is available.

New API fields on `/api/feed`: `opportunity_type`, `compensation_type`,
`budget_min`, `budget_max`, `budget_currency`,
`payment_verification_status`, `scam_risk_score`, `risk_flags`,
`risk_explanation`, `deadline`, `last_seen_at`.

## Database

```bash
psql "$DATABASE_URL" -f src/db/migrations/015_add_opportunity_fields.sql
psql "$DATABASE_URL" -f src/db/migrations/016_add_opportunity_fields.sql
```

Migration 015 adds the opportunity/compensation/risk/lifecycle columns plus a
CHECK constraint `opportunity_type IN ('job','freelance','bounty','open_source')`.
Migration 016 adds the outreach columns and compound indexes
(`idx_jobs_opportunity_type_status`, `idx_jobs_scam_risk_type`,
`idx_jobs_freshness`).

## Limitations

| Source | Status |
| :--- | :--- |
| Upwork, Freelancer.com | Automated scraping violates ToS. Use email-alert import instead. |
| Contra, PeoplePerHour | Gated/login-walled; not scraped. |
| Reddit | Needs OAuth; full read requires approved app credentials. |
| Polar | Public bounty API discontinued; covered indirectly via GitHub issues. |
| GitHub rewards | Amounts are self-reported and cannot be verified by the platform. |

Risk scoring is a heuristic triage signal, **not** a guarantee. Every outreach
draft requires human review; nothing is sent automatically.
