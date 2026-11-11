# GitHub Pipeline Rebuild Plan

## Root problem
The old GitHub extractor searched for the word "bounty" and treated every hit as
a paid job. The word proves nothing. Rebuild around **positive evidence** and a
single quality gate: surface only real, workable issues. Funded bounties are a
strong positive signal, but an unfunded issue still passes if it is well-scoped
and in a healthy repo. Everything else is rejected with reasons.

## New/changed files

| File | Purpose |
|------|---------|
| config/github_issues.yml | Single config file: platforms, labels, repo-name patterns, stack, avoid-domains, thresholds, crypto tokens, search queries, watchlist seeds |
| src/db/migrations/018_github_quality_gate.sql | repo_health, watchlist, rejected_issues tables + score/why columns on jobs |
| src/opportunities/bounty_config.py | GithubConfig, SearchQuery, load_github_config() from YAML |
| src/opportunities/bounty_verdict.py | BountyVerdictEngine: one pool, score 0-100, reject reasons, funding evidence, why/notes, resurface helpers |
| src/opportunities/repo_health.py | Repo health check + 7-day cache in repo_health; expiring blocklist |
| src/extractors/github.py | Two discovery sources (SEARCH + WATCHLIST), ETag/conditional requests, backoff, rate-limit handling |
| src/models/job.py | Add score, score_breakdown, why, notes |
| src/models/transformers.py | Map score/funding/why/notes from payload |
| tests/test_github_quality_gate.py | 13 fixtures + synthetic accepts + crypto legal gate + edge cases |

## Key design decisions (ASSUMPTIONS unless noted)

- One ranked pool. Funding adds +40 to score; it is not a separate lane.
- Crypto payments are a **legal eligibility gate**, not a quality signal: receiving
  crypto is illegal in Nepal, so any crypto-paid bounty is hard-rejected.
- rejected_issues mirrors rejected rows with reasons + evidence so nothing is deleted.
- Repo health cached per repo for 7 days; failing repos expiring-blocklisted.
- Dedupe key = repo + issue number; re-surface only on material state change.
- Rate limit: ~30 req/min authenticated; honour Retry-After / X-RateLimit-Reset,
  ETag/If-Modified-Since caching, capped backoff.

## Assumptions / to verify (marked TODO in config)
- Exact platform label names (e.g. drinks-wave) and platform bot names.
- Which search qualifiers GitHub supports for "no linked PR"/"no assignee".
- Repo size thresholds (`repo_size_warn_kb`, `min_repo_size_kb`).
- Watchlist seed repos.
- Whether `jobs` already has the new columns (migration uses IF NOT EXISTS).

## Order of work
1. Config file   2. Migration   3. Config loader   4. Verdict engine
5. Repo health   6. Extractor   7. Model/transformer   8. Tests   9. Run
