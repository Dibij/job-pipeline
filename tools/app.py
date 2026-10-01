#!/usr/bin/env python3
"""
app.py — Local Web Dashboard for Job Listings backed by PostgreSQL.

USAGE:
    python tools/app.py

SERVES:
    http://localhost:5000
"""

import json
import logging
import sys
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# Normalize messy job_type strings into clean buckets
# ────────────────────────────────────────────────────────────
def normalize_job_type(raw: str) -> str:
    if not raw:
        return "Unknown"
    r = raw.lower()
    if any(x in r for x in ["intern", "stageur", "student"]):
        return "Internship / Student"
    if any(x in r for x in ["freelance", "contract"]):
        return "Contract / Freelance"
    if any(x in r for x in ["part", "teilzeit"]):
        return "Part-time"
    if any(x in r for x in ["full", "permanent", "employee", "berufserfahren", "berufseinstieg", "experienced", "entry", "mid"]):
        return "Full-time"
    return "Other"

# ────────────────────────────────────────────────────────────
# Normalize tags: identify tech tags by known keyword list
# ────────────────────────────────────────────────────────────
KNOWN_TECH_TAGS = {
    "python", "django", "flask", "fastapi",
    "javascript", "typescript", "react", "next.js", "nextjs", "vue", "angular",
    "node", "node.js", "nodejs", "express",
    "postgresql", "postgres", "mysql", "mongodb", "redis",
    "docker", "kubernetes", "aws", "gcp", "azure", "devops", "ci/cd",
    "ai/ml", "ai", "ml", "machine learning", "deep learning", "llm", "rag",
    "data science", "data", "engineering",
    "java", "kotlin", "rust", "go", "golang", "c++", "c#", ".net",
    "php", "ruby", "rails", "swift", "flutter", "dart",
    "graphql", "rest", "api", "microservices",
    "shopify", "wordpress", "ui/ux", "figma",
    "saas", "product", "product management",
}

def is_tech_tag(tag: str) -> bool:
    return tag.lower().strip() in KNOWN_TECH_TAGS


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Pipeline Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f172a;--panel:#1e293b;--border:#334155;
  --accent:#38bdf8;--green:#4ade80;--red:#f87171;
  --text:#f8fafc;--muted:#94a3b8;
  --radius:10px;
}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);min-height:100vh}

/* HEADER */
header{background:var(--panel);border-bottom:1px solid var(--border);padding:16px 32px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:10}
header h1{font-size:1.25rem;color:var(--accent);letter-spacing:-0.5px}
.stats{display:flex;gap:20px;font-size:0.82rem;color:var(--muted)}
.stat-pill{background:rgba(56,189,248,.1);border:1px solid rgba(56,189,248,.2);padding:4px 10px;border-radius:20px;color:var(--accent);font-weight:600}

/* LAYOUT */
.layout{display:flex;height:calc(100vh - 57px)}
aside{width:280px;flex-shrink:0;background:var(--panel);border-right:1px solid var(--border);overflow-y:auto;padding:20px 16px;display:flex;flex-direction:column;gap:18px}
main{flex:1;overflow-y:auto;padding:20px 24px}

/* SIDEBAR FILTERS */
.filter-section h3{font-size:0.7rem;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:8px;font-weight:700}
.search-box{display:flex;flex-direction:column;gap:6px}
.search-box input{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:9px 12px;border-radius:6px;font-size:0.9rem;width:100%;outline:none}
.search-box input:focus{border-color:var(--accent)}

.filter-group{display:flex;flex-direction:column;gap:6px}
.filter-group select, .filter-group input[type=range]{width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:8px 10px;border-radius:6px;font-size:0.85rem;outline:none;cursor:pointer}
.filter-group select:focus{border-color:var(--accent)}

.toggle-row{display:flex;align-items:center;justify-content:space-between;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px 12px;cursor:pointer}
.toggle-row label{font-size:0.88rem;cursor:pointer;font-weight:500}
.toggle-row input[type=checkbox]{width:16px;height:16px;accent-color:var(--accent);cursor:pointer}

.tag-cloud{display:flex;flex-wrap:wrap;gap:5px}
.tag-btn{background:rgba(56,189,248,.08);border:1px solid rgba(56,189,248,.2);color:var(--muted);padding:3px 9px;border-radius:4px;font-size:0.75rem;cursor:pointer;transition:all .15s}
.tag-btn:hover,.tag-btn.active{background:rgba(56,189,248,.25);color:var(--accent);border-color:var(--accent)}

.apply-filters-btn{background:var(--accent);color:#0f172a;border:none;padding:10px 0;border-radius:8px;font-weight:700;font-size:0.9rem;cursor:pointer;width:100%;transition:opacity .15s}
.apply-filters-btn:hover{opacity:.85}
.clear-btn{background:transparent;border:1px solid var(--border);color:var(--muted);padding:8px 0;border-radius:8px;font-size:0.82rem;cursor:pointer;width:100%;transition:all .15s}
.clear-btn:hover{border-color:var(--red);color:var(--red)}

/* RESULTS BAR */
.results-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:8px}
.results-bar span{color:var(--muted);font-size:0.88rem}
.sort-select{background:var(--panel);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:6px;font-size:0.82rem;outline:none}

/* LOADING */
#loading{text-align:center;padding:60px;color:var(--muted);font-size:1.1rem}

/* JOB GRID */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}

/* CARD */
.card{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:18px;display:flex;flex-direction:column;gap:12px;transition:border-color .15s,transform .15s;position:relative}
.card:hover{border-color:var(--accent);transform:translateY(-2px)}

.card-top{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.company{font-size:0.82rem;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.5px}
.source-badge{font-size:0.7rem;padding:2px 7px;border-radius:4px;font-weight:700;text-transform:uppercase;flex-shrink:0}
.src-arbeitnow{background:rgba(251,191,36,.12);color:#fbbf24;border:1px solid rgba(251,191,36,.2)}
.src-remotive{background:rgba(74,222,128,.12);color:var(--green);border:1px solid rgba(74,222,128,.2)}

.job-title{font-size:1.05rem;font-weight:700;line-height:1.35;color:var(--text)}

.meta-row{display:flex;flex-wrap:wrap;gap:5px}
.badge{padding:3px 8px;border-radius:4px;font-size:0.72rem;font-weight:600}
.badge-remote{background:rgba(74,222,128,.12);color:var(--green);border:1px solid rgba(74,222,128,.2)}
.badge-onsite{background:rgba(148,163,184,.1);color:var(--muted);border:1px solid var(--border)}
.badge-loc{background:rgba(56,189,248,.1);color:var(--accent);border:1px solid rgba(56,189,248,.2)}
.badge-type{background:rgba(167,139,250,.1);color:#a78bfa;border:1px solid rgba(167,139,250,.2)}
.badge-tag{background:rgba(56,189,248,.06);color:var(--muted);border:1px solid var(--border)}
.badge-tag.tech{background:rgba(56,189,248,.12);color:var(--accent);border:1px solid rgba(56,189,248,.25)}

.desc{font-size:0.84rem;color:#94a3b8;line-height:1.55;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}

.card-footer{display:flex;justify-content:space-between;align-items:center;margin-top:auto;padding-top:10px;border-top:1px solid var(--border)}
.posted{font-size:0.75rem;color:var(--muted)}
.apply-btn{background:var(--accent);color:#0f172a;padding:7px 14px;border-radius:6px;text-decoration:none;font-size:0.82rem;font-weight:700;transition:opacity .15s;white-space:nowrap}
.apply-btn:hover{opacity:.85}
.apply-btn.no-link{background:var(--border);color:var(--muted);pointer-events:none;cursor:default}

.no-results{text-align:center;padding:60px;color:var(--muted)}
.no-results h2{font-size:1.5rem;margin-bottom:8px}

/* PAGINATION */
.pagination{display:flex;justify-content:center;gap:8px;margin-top:24px;flex-wrap:wrap}
.page-btn{background:var(--panel);border:1px solid var(--border);color:var(--muted);padding:7px 13px;border-radius:6px;cursor:pointer;font-size:0.84rem;transition:all .15s}
.page-btn:hover{border-color:var(--accent);color:var(--accent)}
.page-btn.active{background:var(--accent);color:#0f172a;border-color:var(--accent);font-weight:700}
</style>
</head>
<body>

<header>
  <h1>⚡ Job Pipeline Dashboard</h1>
  <div class="stats">
    <span id="stat-total" class="stat-pill">Loading…</span>
    <span id="stat-remote" class="stat-pill">—</span>
    <span id="stat-showing">—</span>
  </div>
</header>

<div class="layout">
  <aside>
    <!-- Keyword Search -->
    <div class="filter-section">
      <h3>🔍 Keyword Search</h3>
      <div class="search-box">
        <input type="text" id="searchInput" placeholder="Title, company, skill…" oninput="debouncedApply()">
      </div>
    </div>

    <!-- Remote -->
    <div class="filter-section">
      <h3>🌐 Remote</h3>
      <div class="toggle-row" onclick="toggleCheckbox('remoteToggle')">
        <label for="remoteToggle">Remote only</label>
        <input type="checkbox" id="remoteToggle">
      </div>
    </div>

    <!-- Source -->
    <div class="filter-section">
      <h3>📡 Source</h3>
      <div class="filter-group">
        <select id="sourceSelect">
          <option value="">All Sources</option>
        </select>
      </div>
    </div>

    <!-- Job Type -->
    <div class="filter-section">
      <h3>💼 Job Type</h3>
      <div class="filter-group">
        <select id="jobTypeSelect">
          <option value="">All Types</option>
          <option value="Full-time">Full-time</option>
          <option value="Internship / Student">Internship / Student</option>
          <option value="Contract / Freelance">Contract / Freelance</option>
          <option value="Part-time">Part-time</option>
        </select>
      </div>
    </div>

    <!-- Tech Tags -->
    <div class="filter-section">
      <h3>🏷️ Tech Tags</h3>
      <div class="tag-cloud" id="tagCloud">Loading…</div>
    </div>

    <!-- Sort -->
    <div class="filter-section">
      <h3>↕️ Sort By</h3>
      <div class="filter-group">
        <select id="sortSelect" onchange="applyFilters()">
          <option value="newest">Newest First</option>
          <option value="oldest">Oldest First</option>
          <option value="company">Company A–Z</option>
        </select>
      </div>
    </div>

    <button class="apply-filters-btn" onclick="applyFilters()">Apply Filters</button>
    <button class="clear-btn" onclick="clearFilters()">Clear All Filters</button>
  </aside>

  <main>
    <div id="loading">Loading jobs from PostgreSQL…</div>
    <div id="results" style="display:none">
      <div class="results-bar">
        <span id="resultsCount"></span>
      </div>
      <div class="grid" id="grid"></div>
      <div class="pagination" id="pagination"></div>
    </div>
  </main>
</div>

<script>
const PAGE_SIZE = 24;
let allJobs = [];
let filtered = [];
let currentPage = 1;
let activeTags = new Set();
let debounceTimer = null;

// ── Boot ──────────────────────────────────────────────────────────
async function boot() {
  const [jobsRes, filtersRes] = await Promise.all([
    fetch('/api/jobs').then(r => r.json()),
    fetch('/api/filters').then(r => r.json()),
  ]);

  allJobs = jobsRes;
  populateFilters(filtersRes);
  applyFilters();

  document.getElementById('loading').style.display = 'none';
  document.getElementById('results').style.display = 'block';

  const total = allJobs.length;
  const remote = allJobs.filter(j => j.is_remote).length;
  document.getElementById('stat-total').innerText = `${total} total jobs`;
  document.getElementById('stat-remote').innerText = `${remote} remote`;
}

// ── Populate sidebar from real data ──────────────────────────────
function populateFilters(filters) {
  // Sources
  const srcSel = document.getElementById('sourceSelect');
  filters.sources.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s; opt.innerText = s.charAt(0).toUpperCase() + s.slice(1);
    srcSel.appendChild(opt);
  });

  // Tech tags cloud
  const cloud = document.getElementById('tagCloud');
  cloud.innerHTML = '';
  filters.tech_tags.forEach(t => {
    const btn = document.createElement('button');
    btn.className = 'tag-btn';
    btn.innerText = t;
    btn.onclick = () => toggleTag(t, btn);
    cloud.appendChild(btn);
  });
}

function toggleTag(tag, btn) {
  if (activeTags.has(tag)) { activeTags.delete(tag); btn.classList.remove('active'); }
  else { activeTags.add(tag); btn.classList.add('active'); }
  applyFilters();
}

function toggleCheckbox(id) {
  const cb = document.getElementById(id);
  cb.checked = !cb.checked;
  applyFilters();
}

function debouncedApply() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(applyFilters, 220);
}

// ── Filtering ─────────────────────────────────────────────────────
function applyFilters() {
  const search = document.getElementById('searchInput').value.toLowerCase().trim();
  const remoteOnly = document.getElementById('remoteToggle').checked;
  const source = document.getElementById('sourceSelect').value;
  const jobType = document.getElementById('jobTypeSelect').value;
  const sort = document.getElementById('sortSelect').value;

  filtered = allJobs.filter(j => {
    if (remoteOnly && !j.is_remote) return false;
    if (source && j.source !== source) return false;
    if (jobType && j.job_type_normalized !== jobType) return false;

    if (activeTags.size > 0) {
      const jTags = (j.tags || []).map(t => t.toLowerCase());
      const hasAll = [...activeTags].every(t => jTags.some(jt => jt.includes(t.toLowerCase())));
      if (!hasAll) return false;
    }

    if (search) {
      const haystack = [j.title, j.company_name, j.description, ...(j.tags || [])].join(' ').toLowerCase();
      if (!haystack.includes(search)) return false;
    }

    return true;
  });

  // Sort
  filtered.sort((a, b) => {
    if (sort === 'newest') return (b.posted_at || '').localeCompare(a.posted_at || '');
    if (sort === 'oldest') return (a.posted_at || '').localeCompare(b.posted_at || '');
    if (sort === 'company') return (a.company_name || '').localeCompare(b.company_name || '');
    return 0;
  });

  currentPage = 1;
  document.getElementById('stat-showing').innerText = `${filtered.length} matching`;
  renderPage();
}

// ── Render ────────────────────────────────────────────────────────
function renderPage() {
  const grid = document.getElementById('grid');
  const pag = document.getElementById('pagination');
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const page = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  document.getElementById('resultsCount').innerText =
    `Showing ${filtered.length} job${filtered.length !== 1 ? 's' : ''} — page ${currentPage} of ${totalPages || 1}`;

  if (filtered.length === 0) {
    grid.innerHTML = '<div class="no-results" style="grid-column:1/-1"><h2>No jobs found</h2><p>Try different filters or clear all filters.</p></div>';
    pag.innerHTML = '';
    return;
  }

  grid.innerHTML = '';
  page.forEach(j => grid.appendChild(buildCard(j)));

  // Pagination
  pag.innerHTML = '';
  if (totalPages <= 1) return;

  const addBtn = (label, page, active) => {
    const btn = document.createElement('button');
    btn.className = 'page-btn' + (active ? ' active' : '');
    btn.innerText = label;
    if (!active) btn.onclick = () => { currentPage = page; renderPage(); window.scrollTo(0,0); };
    pag.appendChild(btn);
  };

  if (currentPage > 1) addBtn('← Prev', currentPage - 1, false);
  const start = Math.max(1, currentPage - 2);
  const end = Math.min(totalPages, currentPage + 2);
  for (let i = start; i <= end; i++) addBtn(i, i, i === currentPage);
  if (currentPage < totalPages) addBtn('Next →', currentPage + 1, false);
}

function buildCard(j) {
  const card = document.createElement('div');
  card.className = 'card';

  const srcClass = 'src-' + (j.source || 'other');
  const remBadge = j.is_remote
    ? `<span class="badge badge-remote">🌐 Remote</span>`
    : `<span class="badge badge-onsite">🏢 On-site</span>`;

  const locBadge = j.location_raw
    ? `<span class="badge badge-loc">📍 ${escHtml(j.location_raw.slice(0,28))}</span>`
    : '';

  const typeBadge = j.job_type_normalized && j.job_type_normalized !== 'Unknown'
    ? `<span class="badge badge-type">${escHtml(j.job_type_normalized)}</span>`
    : '';

  const techTags = (j.tech_tags || []).slice(0, 4).map(t =>
    `<span class="badge badge-tag tech">${escHtml(t)}</span>`).join('');
  const otherTags = (j.other_tags || []).slice(0, 2).map(t =>
    `<span class="badge badge-tag">${escHtml(t.slice(0, 20))}</span>`).join('');

  const descHtml = j.description
    ? `<p class="desc">${escHtml(j.description.slice(0, 250))}</p>` : '';

  const postedHtml = j.posted_at
    ? `<span class="posted">${formatDate(j.posted_at)}</span>` : `<span></span>`;

  const hasLink = j.apply_url && j.apply_url !== '#';
  const applyBtn = hasLink
    ? `<a href="${escHtml(j.apply_url)}" target="_blank" rel="noopener" class="apply-btn">Apply ↗</a>`
    : `<a class="apply-btn no-link">No Link</a>`;

  card.innerHTML = `
    <div class="card-top">
      <span class="company">${escHtml((j.company_name || 'Unknown').slice(0, 30))}</span>
      <span class="source-badge ${srcClass}">${escHtml(j.source || '')}</span>
    </div>
    <div class="job-title">${escHtml(j.title || 'Untitled')}</div>
    <div class="meta-row">${remBadge}${locBadge}${typeBadge}</div>
    <div class="meta-row">${techTags}${otherTags}</div>
    ${descHtml}
    <div class="card-footer">${postedHtml}${applyBtn}</div>
  `;
  return card;
}

// ── Helpers ───────────────────────────────────────────────────────
function clearFilters() {
  document.getElementById('searchInput').value = '';
  document.getElementById('remoteToggle').checked = false;
  document.getElementById('sourceSelect').value = '';
  document.getElementById('jobTypeSelect').value = '';
  document.getElementById('sortSelect').value = 'newest';
  activeTags.clear();
  document.querySelectorAll('.tag-btn').forEach(b => b.classList.remove('active'));
  applyFilters();
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const now = new Date();
    const diff = Math.floor((now - d) / 86400000);
    if (diff === 0) return 'Today';
    if (diff === 1) return '1 day ago';
    if (diff < 30) return diff + ' days ago';
    return d.toLocaleDateString('en-US', {month:'short', day:'numeric'});
  } catch { return ''; }
}

boot();
</script>
</body>
</html>
"""


def normalize_job_type(raw):
    if not raw:
        return "Unknown"
    r = raw.lower()
    if any(x in r for x in ["intern", "stageur", "student"]):
        return "Internship / Student"
    if any(x in r for x in ["freelance", "contract"]):
        return "Contract / Freelance"
    if any(x in r for x in ["part", "teilzeit"]):
        return "Part-time"
    if any(x in r for x in ["full", "permanent", "employee", "berufserfahren", "berufseinstieg", "experienced", "entry", "mid"]):
        return "Full-time"
    return "Other"


TECH_KEYWORDS = {
    "python", "django", "flask", "fastapi", "javascript", "typescript",
    "react", "next.js", "nextjs", "vue", "angular", "node", "node.js",
    "nodejs", "express", "postgresql", "postgres", "mysql", "mongodb",
    "redis", "docker", "kubernetes", "aws", "gcp", "azure", "devops",
    "ai/ml", "ai", "ml", "machine learning", "deep learning", "llm",
    "rag", "data science", "data engineering", "java", "kotlin", "rust",
    "go", "golang", "c++", "c#", ".net", "php", "ruby", "rails",
    "swift", "flutter", "dart", "graphql", "rest", "api", "microservices",
    "shopify", "wordpress", "ui/ux", "figma", "saas", "typescript",
}


class JobServerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress request logs

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path in ("/", "/index.html"):
            self._respond(200, "text/html; charset=utf-8", HTML.encode())

        elif parsed.path == "/api/jobs":
            jobs = self._fetch_jobs()
            self._respond(200, "application/json", json.dumps(jobs).encode())

        elif parsed.path == "/api/filters":
            filters = self._build_filters()
            self._respond(200, "application/json", json.dumps(filters).encode())

        else:
            self._respond(404, "text/plain", b"Not found")

    def _respond(self, code, content_type, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fetch_jobs(self):
        jobs = []
        try:
            with get_connection(autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            id, source, external_id, title, company_name,
                            location_raw, is_remote, remote_restriction,
                            job_type, experience_level, description_text,
                            apply_url, tags, posted_at, salary_min, salary_max, salary_currency
                        FROM jobs
                        ORDER BY posted_at DESC NULLS LAST, created_at DESC
                        LIMIT 1000;
                    """)
                    rows = cur.fetchall()

            for r in rows:
                tags = r["tags"] or []
                tech = [t for t in tags if t.lower().strip() in TECH_KEYWORDS]
                other = [t for t in tags if t.lower().strip() not in TECH_KEYWORDS]

                posted = None
                if r["posted_at"]:
                    try:
                        posted = r["posted_at"].isoformat()
                    except Exception:
                        pass

                salary = None
                if r["salary_min"] or r["salary_max"]:
                    curr = r["salary_currency"] or "$"
                    lo = r["salary_min"]
                    hi = r["salary_max"]
                    if lo and hi:
                        salary = f"{curr}{int(lo):,}–{int(hi):,}"
                    elif lo:
                        salary = f"From {curr}{int(lo):,}"
                    elif hi:
                        salary = f"Up to {curr}{int(hi):,}"

                jobs.append({
                    "id": str(r["id"]),
                    "source": r["source"],
                    "external_id": r["external_id"],
                    "title": r["title"],
                    "company_name": r["company_name"],
                    "location_raw": r["location_raw"],
                    "is_remote": r["is_remote"],
                    "remote_restriction": r["remote_restriction"],
                    "job_type": r["job_type"],
                    "job_type_normalized": normalize_job_type(r["job_type"]),
                    "experience_level": r["experience_level"],
                    "description": (r["description_text"] or "")[:500],
                    "apply_url": r["apply_url"],
                    "tags": tags,
                    "tech_tags": tech,
                    "other_tags": other,
                    "posted_at": posted,
                    "salary": salary,
                })
        except Exception as exc:
            logger.error("Error fetching jobs: %s", exc)
        return jobs

    def _build_filters(self):
        filters = {"sources": [], "tech_tags": []}
        try:
            with get_connection(autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT DISTINCT source FROM jobs ORDER BY source;")
                    filters["sources"] = [r["source"] for r in cur.fetchall()]

                    cur.execute("SELECT unnest(tags) as tag, count(*) as cnt FROM jobs GROUP BY tag ORDER BY cnt DESC LIMIT 200;")
                    all_tags = [r["tag"] for r in cur.fetchall()]
                    filters["tech_tags"] = sorted({t for t in all_tags if t.lower().strip() in TECH_KEYWORDS})
        except Exception as exc:
            logger.error("Error building filters: %s", exc)
        return filters


def main():
    port = 5000
    httpd = HTTPServer(("", port), JobServerHandler)
    print("=" * 52)
    print("  JOB PIPELINE DASHBOARD")
    print(f"  http://localhost:{port}")
    print("=" * 52)
    print("  Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
