# Remote Job Tools (`/home/dibij/projects/Job/tools/`)

Standalone, runnable tools for collecting, filtering, and visually reviewing remote software engineering job listings.

---

## 🛠️ Tool Overview

### 1. `fetch_jobs.py` — Multi-Source Remote Job Fetcher
Pulls fresh remote job listings from multiple public job boards and REST APIs that explicitly permit programmatic access.

* **Command:**
  ```powershell
  .venv/bin/python tools/fetch_jobs.py
  ```
* **Included Public Sources:**
  - **Remotive API** (`https://remotive.com/api/remote-jobs`)
  - **Jobicy API** (`https://jobicy.com/api/v2/remote-jobs`)
  - **Arbeitnow API** (`https://www.arbeitnow.com/api/job-board-api`)
  - **RemoteOK API** (`https://remoteok.com/api`)
  - **WeWorkRemotely RSS** (`https://weworkremotely.com/remote-jobs.rss`)

* **Compliance & ToS Exclusion Note:**
  - Major sites like **LinkedIn**, **Indeed**, and **Glassdoor** are **DELIBERATELY EXCLUDED**.
  - Scraping those sites violates their Terms of Service (ToS) and puts your IP/account at risk of permanent bans. This tool uses official, public REST APIs and RSS feeds.

* **Output:**
  - Saves deduplicated, structured job listings to `/home/dibij/projects/Job/tools/jobs.json`.

---

### 2. `filter_jobs.py` — Command-Line Filter
Filters `jobs.json` by region, salary, tech tags, or keywords, and outputs a formatted terminal table + `filtered_jobs.json`.

* **Command Examples:**
  ```powershell
  # Filter for Nepal / Global Remote friendly roles with React or Python
  .venv/bin/python tools/filter_jobs.py --remote-ok-nepal --tags python,react

  # Filter with minimum salary requirement
  .venv/bin/python tools/filter_jobs.py --remote-ok-nepal --min-salary 40000
  ```
* **Flags:**
  - `--remote-ok-nepal`: Matches roles open to Worldwide, Anywhere, APAC, Asia, Nepal, or Global, and excludes strict region locks (e.g. USA Only, EU Only, UK Only).
  - `--min-salary NUM`: Filters by minimum annual salary listed.
  - `--tags TAG1,TAG2`: Comma-separated tech stack tags.
  - `--keywords KW1,KW2`: Comma-separated search terms.

* **Output:**
  - Terminal table output + `/home/dibij/projects/Job/tools/filtered_jobs.json`.

---

### 3. `tools/app.py` — Offline Standalone Viewer (Prototype)
A lightweight offline web server providing a visual dashboard to browse and filter offline jobs from `tools/jobs.json`.

> [!NOTE]
> For the **production database feedback dashboard** with the Feed and Rejected tabs, 5-gate HardFilter inspector, and live `v2_role_fit_only` PostgreSQL labeling, run the root application:
> ```powershell
> .venv/bin/.venv/bin/python app.py
> ```

* **Command for offline viewer:**
  ```powershell
  .venv/bin/python tools/app.py
  ```
* **Access URL:**
  - Open **`http://localhost:5000`** in any web browser.

* **Features:**
  - Visual job cards with company, title, location badge, salary, tags, description snippet, and direct application links.
  - Interactive **Nepal / Global Remote Toggle** to filter out regional restrictions in real time.
  - Live search bar and tech stack dropdown.
  - Requires **zero external dependencies** (uses Python's standard library `http.server`).

---

## 🚀 Quick Start Workflow

### Offline Standalone Utilities:
```powershell
# Step 1: Refresh offline job listings from public APIs
.venv/bin/python tools/fetch_jobs.py

# Step 2: Launch offline visual viewer
.venv/bin/python tools/app.py

# Step 3: Open http://localhost:5000 in your browser to inspect listings!
```

### Production Database Pipeline & Feedback Loop:
```powershell
# Run the daily ingestion, scoring & feed update
.venv/bin/python scripts/run_daily.py

# Launch the production interactive feedback app (PostgreSQL backed)
.venv/bin/python app.py
```
