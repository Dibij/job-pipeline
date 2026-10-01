# Remote Job Tools (`D:\Code\Job\tools\`)

Standalone, runnable tools for collecting, filtering, and visually reviewing remote software engineering job listings.

---

## 🛠️ Tool Overview

### 1. `fetch_jobs.py` — Multi-Source Remote Job Fetcher
Pulls fresh remote job listings from multiple public job boards and REST APIs that explicitly permit programmatic access.

* **Command:**
  ```powershell
  python D:\Code\Job\tools\fetch_jobs.py
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
  - Saves deduplicated, structured job listings to `D:\Code\Job\tools\jobs.json`.

---

### 2. `filter_jobs.py` — Command-Line Filter
Filters `jobs.json` by region, salary, tech tags, or keywords, and outputs a formatted terminal table + `filtered_jobs.json`.

* **Command Examples:**
  ```powershell
  # Filter for Nepal / Global Remote friendly roles with React or Python
  python D:\Code\Job\tools\filter_jobs.py --remote-ok-nepal --tags python,react

  # Filter with minimum salary requirement
  python D:\Code\Job\tools\filter_jobs.py --remote-ok-nepal --min-salary 40000
  ```
* **Flags:**
  - `--remote-ok-nepal`: Matches roles open to Worldwide, Anywhere, APAC, Asia, Nepal, or Global, and excludes strict region locks (e.g. USA Only, EU Only, UK Only).
  - `--min-salary NUM`: Filters by minimum annual salary listed.
  - `--tags TAG1,TAG2`: Comma-separated tech stack tags.
  - `--keywords KW1,KW2`: Comma-separated search terms.

* **Output:**
  - Terminal table output + `D:\Code\Job\tools\filtered_jobs.json`.

---

### 3. `app.py` — Local Web Dashboard
A single-command, interactive local web server providing a visual dashboard to browse and filter jobs from your browser.

* **Command:**
  ```powershell
  python D:\Code\Job\tools\app.py
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

```powershell
# Step 1: Refresh job listings from public APIs
python D:\Code\Job\tools\fetch_jobs.py

# Step 2: Launch your local visual dashboard
python D:\Code\Job\tools\app.py

# Step 3: Open http://localhost:5000 in your browser to inspect listings!
```
