# GitHub Pipeline Rebuild Plan

## Root problem
The old GitHub extractor searched for the word "bounty" and treated every hit as
a paid job. The word proves nothing. Rebuild around positive evidence with two
separate lanes: PAID (funded bounty) and PROOF (unfunded but real issue for
profile building). Everything else is rejected with reasons.

## New/changed files

| File | Purpose |
|------|---------|
| config/github_issues.yml | Single config file: platforms, labels, repo-name patterns, stack, avoid-domains, thresholds, search queries, watchlist seeds |
| src/db/migrations/018_github_lanes.sql | repo_health, watchlist, rejected_issues tables + new columns on jobs (lane, score, score_breakdown, why, notes) |
| src/opportunities/bounty_config.py | Extended: LaneConfig, SearchQuery, load_github_config() reading config/github_issues.yml |
| src/opportunities/bounty_verdict.py | Rewritten: LaneVerdictEngine with PAID/PROOF lanes, score, score_breakdown, why, lane, notes |
| src/opportunities/repo_health.py | Repo health check + 7-day cache in repo_health table; expiring blocklist |
| src/extractors/github.py | Rewritten: two discovery sources (SEARCH + WATCHLIST), ETag/conditional requests, backoff, rate-limit respect |
| src/models/job.py | Add lane, score, score_breakdown, why, notes fields |
| src/models/transformers.py | Map new fields from payload in transform_github_issue() |
| tests/test_github_lanes.py | One pytest per fixture (13 fixtures) + 6 synthetic ACCEPT cases + edge cases |

## Key design decisions (ASSUMPTIONS unless noted)

- lane is stored on jobs (new nullable columns) so PAID and PROOF issues share one table.
- rejected_issues mirrors rejected rows with reject_reasons + evidence so nothing is ever deleted.
- Repo health cached per repo for 7 days; failing repos go on an expiring blocklist (TTL hours configurable).
- Dedupe key = repo + issue number. Re-surface only on material change (linked PR closed without merge, assignee removed, funding label appeared).
- Rate limit: ~30 requests/min authenticated. requests Session with If-None-Match/If-Modified-Since, Retry-After/X-RateLimit-Reset backoff, ETag cache in memory.
- Nothing is auto-accepted or auto-contacted.

## What I must verify (marked TODO in config)
- Exact platform label names (e.g. drips-wave) and platform bot names.
- Exact search qualifiers GitHub supports for "no linked PR", "no assignee".
- Repo size threshold for "very large codebase".
- Watchlist seed repos.
- Whether jobs table already has a lane column (migration uses ADD COLUMN IF NOT EXISTS).

## Order of work
1. Config file (config/github_issues.yml)
2. Migration (018_github_lanes.sql)
3. Config loader (bounty_config.py extended)
4. Verdict/scoring engine (bounty_verdict.py rewritten)
5. Repo health check (repo_health.py)
6. GitHub extractor rewrite (extractors/github.py)
7. Job model + transformer updates
8. Test suite
9. Run tests
