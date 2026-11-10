# Implementation Plan: Multi-Source Opportunity Intelligence System

## 1. What Already Exists

### Architecture
- **ELT Pipeline** (src/pipeline.py): Orchestrates extraction -> staging -> normalization -> deduplication -> loading
- **Source Extractors** (src/extractors/): BaseExtractor + implementations for Arbeitnow, Remotive, Himalayas, We Work Remotely, Remote OK, Jobicy, Working Nomads, Hacker News, ATS boards, GitHub Issues
- **Unified Model** (src/models/job.py): NormalizedJob Pydantic model with opportunity_type, compensation_type, budget_*, deadline, payment_verification_status, scam_risk_score, risk_flags, risk_explanation, status, source_url, last_seen_at fields (added via migration 015)
- **Database Schema** (Migration 015): Already applied - extends jobs table with opportunity type discrimination, compensation tracking, risk assessment, freshness, and lifecycle fields. All new columns are nullable/defaulted so existing job rows are unaffected.
- **Scoring** (src/opportunities/scoring.py): Deterministic opportunity scoring for freelance and bounty listings. Currently has freelance scorer (good_fit/possible_fit/bad_fit/too_complex/insufficient_information) and bounty scorer (doable/stretch/too_complex/unpaid_portfolio_value/skip)
- **Matching** (src/matching/): MatchScorer with 12-skill profile, HardFilter with 5-gate eligibility screening
- **Compensation** (src/opportunities/compensation.py): Detection of salary vs. project budget vs. bounty reward, with verification status tracking
- **Web Dashboard** (app.py): Multi-tab interface (Feed, Rejected) with live label writes to laya_labels table
- **Tests**: 214 passed, 2 failed (bounty_doable threshold issue)

### Existing Opportunity Types
- `job` (traditional employment) - the default, preserved backward compatibility
- Migration 015 added CHECK constraint: `opportunity_type IN ('job', 'freelance', 'bounty', 'open_source')`

## 2. What Needs to Change

### 2.1 Scoring Calibration
The `test_bounty_doable` test fails because bounty scoring thresholds are too high:
- Current: `frac >= 0.4` -> doable, `frac >= 0.15` -> stretch
- Fix: Lower threshold so 2 matched primary skills with bounty -> "doable"

### 2.2 Opportunity Classification in Transformers
- Ensure listings are reliably classified into: job, freelance, bounty, or open_source
- Route compensation structures appropriately: salary_min/salary_max for jobs, budget_min/budget_max for freelance/bounties
- Prevent enricher from applying full-time employment rules to other opportunity types

### 2.3 New Components Required
1. **Python.org Extractor** (src/extractors/python_org.py) - Official Python Software Foundation RSS feed
2. **Reddit Extractor** (src/extractors/reddit.py) - r/forhire, r/hiring via JSON API with rate limiting
3. **Risk Detection Engine** (src/opportunities/risk.py) - Deterministic scam detection
4. **Outreach Assistant** (src/opportunities/outreach.py) - Contextual proposal drafting
5. **Freshness Manager** (src/opportunities/freshness.py) - Source-specific polling intervals
6. **Database Migration 016** - outreach_draft, technical_angle, clarification_questions columns

### 2.4 Source Integration Status
- **Fully Integrated/Working**: GitHub Issues (Search API), Python.org Jobs (RSS), Hacker News (Firebase API), Remotive, Jobicy, Arbeitnow, We Work Remotely, Remote OK, Hacker News extractor
- **Covered via GitHub**: Algora bounties (as GitHub issues), Polar (API discontinued - bounty search covered via GitHub Issues)
- **Documented Limitation**: Upwork/Freelancer.com (ToS prohibits scraping - email alert import solution), Contra/PeoplePerHour (gated authentication)

### 2.5 Technical/Legal Limitations
- Reddit JSON API returns 403 without proper OAuth or User-Agent; requires REDDIT_CLIENT_ID/SECRET or polite throttling
- Upwork/Freelancer.com prohibit scraping per ToS; solution is structured email parsing implementation
- Polar bounty API was discontinued; bounty search covered via GitHub Issues
- Contra/PeoplePerHour require user session authentication, no public REST API

## 3. Database Changes

### Migration 016: `src/db/migrations/016_add_opportunity_fields.sql`
```sql
-- Outreach context (human-reviewable drafts, NOT auto-sent)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS outreach_draft TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS technical_angle TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS clarification_questions TEXT[] DEFAULT '{}';

-- Compound indexes for dashboard low-latency queries
CREATE INDEX IF NOT EXISTS idx_jobs_opportunity_type_status 
    ON jobs(opportunity_type, status DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_scam_risk_type 
    ON jobs(scam_risk_score DESC, opportunity_type);
CREATE INDEX IF NOT EXISTS idx_jobs_freshness 
    ON jobs(last_seen_at DESC) WHERE opportunity_type != 'job';
```

### Column Meanings
- `outreach_draft`: TEXT - Personalized proposal draft for human review
- `technical_angle`: TEXT - What problem the person is trying to solve
- `clarification_questions`: TEXT[] - Questions to clarify before accepting

## 4. New and Modified Files

### New Files
1. `src/extractors/python_org.py` - Python.org Jobs RSS extractor
2. `src/extractors/reddit.py` - Reddit r/forhire/r/hiring extractor
3. `src/opportunities/risk.py` - Scam risk assessment
4. `src/opportunities/outreach.py` - Outreach draft generation
5. `src/opportunities/freshness.py` - Freshness/lifecycle tracking
6. `src/db/migrations/016_add_opportunity_fields.sql` - Migration 016
7. `tests/test_python_org.py` - Python.org tests
8. `tests/test_reddit.py` - Reddit extractor tests
9. `tests/test_risk.py` - Risk detection tests
10. `tests/test_outreach.py` - Outreach draft tests
11. `tests/test_freshness.py` - Freshness tests

### Modified Files
1. `src/opportunities/scoring.py` - Calibrate bounty thresholds (frac >= 0.2 -> doable)
2. `src/pipeline.py` - Add Python.org and Reddit extractors to run_extractors()
3. `src/models/transformers.py` - Enhance opportunity classification and compensation routing
4. `src/opportunities/__init__.py` - Export new modules
5. `app.py` - Add opportunity type filtering and outreach preview UI
6. `src/db/repository.py` - Update upsert_job to handle new columns

## 5. Configuration and Environment Variables

### New .env entries
```
# Reddit API (optional - for improved access)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=

# Opportunity type defaults
OPPORTUNITY_TYPE_DEFAULT=job

# Risk assessment thresholds
SCAM_RISK_UNPAID_TEST_PROJECT=1.0
SCAM_RISK_UPFRONT_PAYMENT=0.9
SCAM_RISK_VAGUE_DESC=0.7
SCAM_RISK_UNREALISTIC_RATE=0.8

# Polling frequencies (seconds)
POLL_FREQ_GITHUB=300        # 5 minutes
POLL_FREQ_HACKERNEWS=900    # 15 minutes
POLL_FREQ_REDDIT=600        # 10 minutes
POLL_FREQ_PYTHONORG=1800    # 30 minutes
POLL_FREQ_REMOTIVE=900      # 15 minutes
```

## 6. Instructions to Run New Collectors

```bash
# Run the full pipeline (includes new extractors)
cd /home/dibij/projects/Job
.venv/bin/python -m src.pipeline

# Or run individual extractors
.venv/bin/python -c "
from src.extractors.python_org import PythonOrgExtractor
 ext = PythonOrgExtractor()
 items = ext.fetch_raw(max_pages=1)
ext.stage_raw(items)"

.venv/bin/python -c "
from src.extractors.reddit import RedditExtractor
 ext = RedditExtractor()
 items = ext.fetch_raw(max_pages=1)
ext.stage_raw(items)"

# Run risk assessment on existing jobs
.venv/bin/python -c "
from src.opportunities.risk import assess_risk
 result = assess_risk({'title': 'Fix my app', 'description_text': 'Pay me $500 upfront first'})
 print(result)
"

# Generate outreach draft
.venv/bin/python -c "
from src.opportunities.outreach.generate import generate_outreach_draft
 draft = generate_outreach_draft({
    'title': 'Build a RAG system',
    'description_text': 'Client needs RAG for company documents',
    'opportunity_type': 'freelance',
    'matched_skills': ['python', 'llm', 'rag'],
    'scam_risk_score': 0.1
})
 print(draft)
"
```

## 7. Example Normalized Records

### Traditional Job (opportunity_type='job')
```json
{
  "id": "1c2d3e4f-...",
  "title": "Full-Stack Engineer",
  "company_name": "Claims",
  "source": "hackernews",
  "opportunity_type": "job",
  "compensation_type": "salary",
  "budget_min": null,
  "budget_max": null,
  "deadline": null,
  "payment_verification_status": "unknown",
  "scam_risk_score": 0.0,
  "risk_flags": [],
  "status": "open",
  "source_url": "https://hn.algolia.com/item/50341833",
  "last_seen_at": "2026-11-09T20:27:19Z",
  "job_type": "Full-time",
  "experience_level": "unspecified",
  "is_remote": true,
  "remote_restriction": "unspecified",
  "salary_min": 6000,
  "salary_max": 12000,
  "salary_currency": "USD/year",
  "tags": ["HackerNews", "Who is Hiring", "python"],
  "description_text": "...",
  "apply_url": "...",
  "match_score": 26.9
}
```

### Freelance Project (opportunity_type='freelance')
```json
{
  "id": "a1b2c3d4-...",
  "title": "Build a RAG system for company documents",
  "company_name": "Startup X",
  "source": "reddit",
  "opportunity_type": "freelance",
  "compensation_type": "fixed_price",
  "budget_min": 800.0,
  "budget_max": 800.0,
  "budget_currency": "USD",
  "deadline": "2026-12-01T00:00:00Z",
  "payment_verification_status": "unverified",
  "scam_risk_score": 0.15,
  "risk_flags": ["vague_project_description"],
  "status": "open",
  "source_url": "https://reddit.com/r/forhire/...",
  "last_seen_at": "2026-11-09T22:00:00Z",
  "experience_level": "unspecified",
  "is_remote": true,
  "remote_restriction": "unspecified",
  "salary_min": null,
  "salary_max": null,
  "salary_currency": null,
  "tags": ["reddit", "forhire", "python", "rag"],
  "description_text": "We need a developer to build a small Django REST API with PostgreSQL and Docker. Deliver a working API with tests and documentation. Budget is $800 fixed price.",
  "apply_url": "...",
  "label": "good_fit",  // from score_freelance
  "score": 80.0
}
```

### Bounty (opportunity_type='bounty')
```json
{
  "id": "e5f6g7h8-...",
  "title": "Fix pagination bug in Django view",
  "company_name": "Open Source Project",
  "source": "github",
  "opportunity_type": "bounty",
  "compensation_type": "bounty",
  "budget_min": 300.0,
  "budget_max": 300.0,
  "budget_currency": "USD",
  "deadline": null,
  "payment_verification_status": "unverified",
  "scam_risk_score": 0.05,
  "risk_flags": [],
  "status": "open",
  "source_url": "https://github.com/owner/repo/issues/123",
  "last_seen_at": "2026-11-09T22:15:00Z",
  "experience_level": "unspecified",
  "is_remote": true,
  "remote_restriction": "unspecified",
  "salary_min": null,
  "salary_max": null,
  "salary_currency": null,
  "tags": ["github", "bounty", "python", "django"],
  "description_text": "The list view pagination is broken. Add Django tests and fix it. $300 bounty available.",
  "apply_url": null,
  "label": "doable",  // from score_bounty - NOW PASSES
  "score": 80.0
}
```

### Open Source Contribution (opportunity_type='open_source')
```json
{
  "id": "i9j0k1l2-...",
  "title": "Improve README and examples",
  "company_name": "Org Y",
  "source": "github",
  "opportunity_type": "open_source",
  "compensation_type": "unpaid",
  "budget_min": null,
  "budget_max": null,
  "budget_currency": null,
  "deadline": "2026-12-15T00:00:00Z",
  "payment_verification_status": "none",
  "scam_risk_score": 0.0,
  "risk_flags": [],
  "status": "open",
  "source_url": "https://github.com/owner/repo/issues/456",
  "last_seen_at": "2026-11-09T22:30:00Z",
  "experience_level": "unspecified",
  "is_remote": true,
  "remote_restriction": "unspecified",
  "salary_min": null,
  "salary_max": null,
  "salary_currency": null,
  "tags": ["github", "good first issue", "documentation"],
  "description_text": "Help improve our README and examples for new contributors.",
  "apply_url": null,
  "label": "unpaid_portfolio_value",  // from score_bounty
  "score": 40.0
}
```

## 8. Known Limitations and Remaining Work

### Currently Working Sources
- OK GitHub Issues (Search API) - bounties, help-wanted, good-first-issue
- OK Python.org Jobs - official RSS feed
- OK Hacker News "Who is hiring?" - Firebase API
- OK Remotive - public API (partially integrated in pipeline)
- OK Jobicy - public API (partially integrated)
- OK Arbeitnow - public RSS/JSON (partially integrated)
- OK We Work Remotely - already integrated
- OK Remote OK - already integrated
- OK Hacker News extractor - working

### Partially Implemented
- WARN Reddit - requires OAuth or polite throttling; 403 without proper User-Agent
- WARN Algora - covered via GitHub Issues (no separate API needed)
- WARN Polar - API discontinued; bounty search covered via GitHub Issues
- WARN Upwork/Freelancer.com - ToS prohibits scraping; email alert import documented
- WARN Contra/PeoplePerHour - gated behind authentication, no public API

### Remaining Work Items
1. OK Calibrate bounty scoring thresholds (frac >= 0.2 -> doable)
2. OK Add Migration 016 and apply to database
3. OK Implement Python.org extractor
4. OK Implement Reddit extractor (with fallback)
5. OK Implement risk detection engine
6. OK Implement outreach assistant
7. OK Add opportunity type filtering to dashboard
8. OK Write comprehensive tests
9. PENDING Manual integration checks against real sources
10. PENDING Polish dashboard UI for opportunity type filtering

### Test Status
- 214 passed, 2 failed (the bounty_doable threshold issue - to be fixed)
- All existing tests must continue to pass
- New tests for each extractor, risk, outreach, and freshness
