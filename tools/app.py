#!/usr/bin/env python3
"""
app.py — Local Web Dashboard for Job Listings with CV Match Scoring and Smart Filters.

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
    "shopify", "wordpress", "ui/ux", "figma", "saas",
}

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Pipeline & CV Matcher</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f172a;--panel:#1e293b;--border:#334155;
  --accent:#38bdf8;--green:#4ade80;--red:#f87171;--amber:#fbbf24;
  --text:#f8fafc;--muted:#94a3b8;
  --radius:10px;
}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);min-height:100vh}

/* HEADER */
header{background:var(--panel);border-bottom:1px solid var(--border);padding:14px 28px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:10}
header h1{font-size:1.25rem;color:var(--accent);letter-spacing:-0.5px}
.stats{display:flex;gap:14px;font-size:0.82rem;color:var(--muted);align-items:center}
.stat-pill{background:rgba(56,189,248,.1);border:1px solid rgba(56,189,248,.2);padding:4px 10px;border-radius:20px;color:var(--accent);font-weight:600}
.stat-pill.green{background:rgba(74,222,128,.1);border-color:rgba(74,222,128,.2);color:var(--green)}

/* LAYOUT */
.layout{display:flex;height:calc(100vh - 54px)}
aside{width:310px;flex-shrink:0;background:var(--panel);border-right:1px solid var(--border);overflow-y:auto;padding:18px 16px;display:flex;flex-direction:column;gap:16px}
main{flex:1;overflow-y:auto;padding:20px 24px}

/* SIDEBAR FILTERS */
.filter-section h3{font-size:0.72rem;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:8px;font-weight:700}
.search-box{display:flex;flex-direction:column;gap:6px}
.search-box input{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:9px 12px;border-radius:6px;font-size:0.9rem;width:100%;outline:none}
.search-box input:focus{border-color:var(--accent)}

.filter-group{display:flex;flex-direction:column;gap:6px}
.filter-group select{width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:8px 10px;border-radius:6px;font-size:0.85rem;outline:none;cursor:pointer}
.filter-group select:focus{border-color:var(--accent)}

.toggle-list{display:flex;flex-direction:column;gap:6px}
.toggle-row{display:flex;align-items:center;justify-content:space-between;background:var(--bg);border:1px solid var(--border);border-radius:7px;padding:8px 12px;cursor:pointer}
.toggle-row label{font-size:0.84rem;cursor:pointer;font-weight:500;user-select:none}
.toggle-row input[type=checkbox]{width:16px;height:16px;accent-color:var(--accent);cursor:pointer}

.tag-cloud{display:flex;flex-wrap:wrap;gap:5px}
.tag-btn{background:rgba(56,189,248,.08);border:1px solid rgba(56,189,248,.2);color:var(--muted);padding:3px 8px;border-radius:4px;font-size:0.74rem;cursor:pointer;transition:all .15s}
.tag-btn:hover,.tag-btn.active{background:rgba(56,189,248,.25);color:var(--accent);border-color:var(--accent)}

.apply-filters-btn{background:var(--accent);color:#0f172a;border:none;padding:10px 0;border-radius:8px;font-weight:700;font-size:0.88rem;cursor:pointer;width:100%;transition:opacity .15s}
.apply-filters-btn:hover{opacity:.85}
.clear-btn{background:transparent;border:1px solid var(--border);color:var(--muted);padding:7px 0;border-radius:8px;font-size:0.8rem;cursor:pointer;width:100%;transition:all .15s}
.clear-btn:hover{border-color:var(--red);color:var(--red)}

/* RESULTS BAR */
.results-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:8px}
.results-bar span{color:var(--muted);font-size:0.88rem}

/* LOADING */
#loading{text-align:center;padding:60px;color:var(--muted);font-size:1.1rem}

/* JOB GRID */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px}

/* CARD */
.card{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:18px;display:flex;flex-direction:column;gap:12px;transition:border-color .15s,transform .15s;position:relative}
.card:hover{border-color:var(--accent);transform:translateY(-2px)}
.card.high-match{border-color:rgba(74,222,128,.4);background:linear-gradient(180deg, rgba(74,222,128,.04) 0%, var(--panel) 100%)}

.card-top{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.company{font-size:0.82rem;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.5px}

.score-badge{font-size:0.75rem;padding:3px 9px;border-radius:12px;font-weight:800;letter-spacing:.3px}
.score-high{background:rgba(74,222,128,.15);color:var(--green);border:1px solid rgba(74,222,128,.3)}
.score-mid{background:rgba(251,191,36,.15);color:var(--amber);border:1px solid rgba(251,191,36,.3)}
.score-low{background:rgba(148,163,184,.1);color:var(--muted);border:1px solid var(--border)}

.job-title{font-size:1.05rem;font-weight:700;line-height:1.35;color:var(--text)}

.meta-row{display:flex;flex-wrap:wrap;gap:5px}
.badge{padding:3px 8px;border-radius:4px;font-size:0.72rem;font-weight:600}
.badge-remote{background:rgba(74,222,128,.12);color:var(--green);border:1px solid rgba(74,222,128,.2)}
.badge-onsite{background:rgba(148,163,184,.1);color:var(--muted);border:1px solid var(--border)}
.badge-loc{background:rgba(56,189,248,.1);color:var(--accent);border:1px solid rgba(56,189,248,.2)}
.badge-type{background:rgba(167,139,250,.1);color:#a78bfa;border:1px solid rgba(167,139,250,.2)}
.badge-exp{background:rgba(56,189,248,.15);color:var(--accent);border:1px solid rgba(56,189,248,.3);text-transform:uppercase}
.badge-exp.senior{background:rgba(248,113,113,.12);color:var(--red);border-color:rgba(248,113,113,.25)}
.badge-skill{background:rgba(74,222,128,.12);color:var(--green);border:1px solid rgba(74,222,128,.25)}
.badge-tag{background:rgba(56,189,248,.06);color:var(--muted);border:1px solid var(--border)}
.badge-flag{background:rgba(248,113,113,.12);color:var(--red);border:1px solid rgba(248,113,113,.25)}

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
  <h1>⚡ Job Pipeline & CV Matcher</h1>
  <div class="stats">
    <span id="stat-total" class="stat-pill">Loading…</span>
    <span id="stat-matched" class="stat-pill green">—</span>
    <span id="stat-showing">—</span>
  </div>
</header>

<div class="layout">
  <aside>
    <!-- Smart Clean Toggles -->
    <div class="filter-section">
      <h3>🛡️ Smart Clean Filters</h3>
      <div class="toggle-list">
        <div class="toggle-row" onclick="toggleCheckbox('hideSenior')">
          <label for="hideSenior">Hide Senior Roles</label>
          <input type="checkbox" id="hideSenior" checked>
        </div>
        <div class="toggle-row" onclick="toggleCheckbox('hideGerman')">
          <label for="hideGerman">Hide German Postings</label>
          <input type="checkbox" id="hideGerman" checked>
        </div>
        <div class="toggle-row" onclick="toggleCheckbox('hideUnpaid')">
          <label for="hideUnpaid">Hide Unpaid Jobs</label>
          <input type="checkbox" id="hideUnpaid" checked>
        </div>
        <div class="toggle-row" onclick="toggleCheckbox('nepalOnly')">
          <label for="nepalOnly">Accessible from Nepal</label>
          <input type="checkbox" id="nepalOnly" checked>
        </div>
      </div>
    </div>

    <!-- Keyword Search -->
    <div class="filter-section">
      <h3>🔍 Keyword Search</h3>
      <div class="search-box">
        <input type="text" id="searchInput" placeholder="Python, Django, React…" oninput="debouncedApply()">
      </div>
    </div>

    <!-- Seniority Selector -->
    <div class="filter-section">
      <h3>🎓 Seniority Level</h3>
      <div class="filter-group">
        <select id="senioritySelect" onchange="applyFilters()">
          <option value="">All Experience Levels</option>
          <option value="entry_friendly">Junior & Internships Only</option>
          <option value="intern">Internships Only</option>
          <option value="junior">Junior Only</option>
          <option value="unspecified">Unspecified Level</option>
        </select>
      </div>
    </div>

    <!-- Min Match Score -->
    <div class="filter-section">
      <h3>🎯 Min Match Score</h3>
      <div class="filter-group">
        <select id="minScoreSelect" onchange="applyFilters()">
          <option value="0">Any Score (0%+)</option>
          <option value="25">Fair Match (25%+)</option>
          <option value="50">Good Match (50%+)</option>
          <option value="60">Strong Match (60%+)</option>
        </select>
      </div>
    </div>

    <!-- Remote Toggle -->
    <div class="filter-section">
      <h3>🌐 Work Location</h3>
      <div class="toggle-row" onclick="toggleCheckbox('remoteToggle')">
        <label for="remoteToggle">100% Remote Only</label>
        <input type="checkbox" id="remoteToggle">
      </div>
    </div>

    <!-- Tech Tags Cloud -->
    <div class="filter-section">
      <h3>🏷️ Matched Tech Skills</h3>
      <div class="tag-cloud" id="tagCloud">Loading…</div>
    </div>

    <!-- Sort By -->
    <div class="filter-section">
      <h3>↕️ Sort By</h3>
      <div class="filter-group">
        <select id="sortSelect" onchange="applyFilters()">
          <option value="match_desc">Highest Match Score First</option>
          <option value="newest">Newest First</option>
          <option value="company">Company A–Z</option>
        </select>
      </div>
    </div>

    <button class="apply-filters-btn" onclick="applyFilters()">Apply Filters</button>
    <button class="clear-btn" onclick="clearFilters()">Reset All Filters</button>
  </aside>

  <main>
    <div id="loading">Loading and ranking jobs from PostgreSQL…</div>
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
  const strongMatches = allJobs.filter(j => j.match_score >= 50).length;
  document.getElementById('stat-total').innerText = `${total} total jobs in DB`;
  document.getElementById('stat-matched').innerText = `${strongMatches} top matches (50%+)`;
}

function populateFilters(filters) {
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
  debounceTimer = setTimeout(applyFilters, 200);
}

function applyFilters() {
  const search = document.getElementById('searchInput').value.toLowerCase().trim();
  const hideSenior = document.getElementById('hideSenior').checked;
  const hideGerman = document.getElementById('hideGerman').checked;
  const hideUnpaid = document.getElementById('hideUnpaid').checked;
  const nepalOnly = document.getElementById('nepalOnly').checked;
  const remoteOnly = document.getElementById('remoteToggle').checked;
  const seniority = document.getElementById('senioritySelect').value;
  const minScore = parseFloat(document.getElementById('minScoreSelect').value) || 0;
  const sort = document.getElementById('sortSelect').value;

  filtered = allJobs.filter(j => {
    if (hideSenior && (j.experience_level === 'senior' || (j.flags || []).includes('SENIOR'))) return false;
    if (hideGerman && (j.detected_language === 'german' || (j.flags || []).includes('GERMAN'))) return false;
    if (hideUnpaid && (j.is_unpaid || (j.flags || []).includes('UNPAID'))) return false;
    if (nepalOnly && (!j.nepal_accessible || (j.flags || []).includes('INACCESSIBLE'))) return false;
    if (remoteOnly && !j.is_remote) return false;

    if (seniority === 'entry_friendly' && !['junior', 'intern'].includes(j.experience_level)) return false;
    if (seniority && seniority !== 'entry_friendly' && j.experience_level !== seniority) return false;

    if (j.match_score < minScore) return false;

    if (activeTags.size > 0) {
      const jTags = (j.tags || []).map(t => t.toLowerCase());
      const hasAll = [...activeTags].every(t => jTags.some(jt => jt.includes(t.toLowerCase())));
      if (!hasAll) return false;
    }

    if (search) {
      const haystack = [j.title, j.company_name, j.description, ...(j.tags || []), ...(j.matched_skills || [])].join(' ').toLowerCase();
      if (!haystack.includes(search)) return false;
    }

    return true;
  });

  // Sort
  filtered.sort((a, b) => {
    if (sort === 'match_desc') return (b.match_score || 0) - (a.match_score || 0);
    if (sort === 'newest') return (b.posted_at || '').localeCompare(a.posted_at || '');
    if (sort === 'company') return (a.company_name || '').localeCompare(b.company_name || '');
    return 0;
  });

  currentPage = 1;
  document.getElementById('stat-showing').innerText = `${filtered.length} matching criteria`;
  renderPage();
}

function renderPage() {
  const grid = document.getElementById('grid');
  const pag = document.getElementById('pagination');
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const page = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  document.getElementById('resultsCount').innerText =
    `Showing ${filtered.length} curated jobs — page ${currentPage} of ${totalPages || 1}`;

  if (filtered.length === 0) {
    grid.innerHTML = '<div class="no-results" style="grid-column:1/-1"><h2>No matching jobs found</h2><p>Try turning off "Hide Senior" or reducing the minimum match score.</p></div>';
    pag.innerHTML = '';
    return;
  }

  grid.innerHTML = '';
  page.forEach(j => grid.appendChild(buildCard(j)));

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
  const isHighMatch = j.match_score >= 50;
  card.className = 'card' + (isHighMatch ? ' high-match' : '');

  // Score Badge
  let scoreClass = 'score-low';
  if (j.match_score >= 60) scoreClass = 'score-high';
  else if (j.match_score >= 35) scoreClass = 'score-mid';
  const scoreBadge = `<span class="score-badge ${scoreClass}">🎯 ${Math.round(j.match_score)}% Match</span>`;

  // Remote badge
  const remBadge = j.is_remote
    ? `<span class="badge badge-remote">🌐 Remote</span>`
    : `<span class="badge badge-onsite">🏢 On-site</span>`;

  // Seniority badge
  const expClass = j.experience_level === 'senior' ? 'badge-exp senior' : 'badge-exp';
  const expBadge = j.experience_level && j.experience_level !== 'unspecified'
    ? `<span class="badge ${expClass}">${escHtml(j.experience_level)}</span>` : '';

  // Matched Skills Badges
  const matchedSkillsHtml = (j.matched_skills || []).slice(0, 5).map(s =>
    `<span class="badge badge-skill">✓ ${escHtml(s)}</span>`).join('');

  // Warning Flags
  const flagsHtml = (j.flags || []).map(f =>
    `<span class="badge badge-flag">⚠️ ${escHtml(f)}</span>`).join('');

  const descHtml = j.description
    ? `<p class="desc">${escHtml(j.description.slice(0, 260))}</p>` : '';

  const postedHtml = j.posted_at
    ? `<span class="posted">${formatDate(j.posted_at)}</span>` : `<span></span>`;

  const hasLink = j.apply_url && j.apply_url !== '#';
  const applyBtn = hasLink
    ? `<a href="${escHtml(j.apply_url)}" target="_blank" rel="noopener" class="apply-btn">Apply Now ↗</a>`
    : `<a class="apply-btn no-link">No Link</a>`;

  card.innerHTML = `
    <div class="card-top">
      <span class="company">${escHtml((j.company_name || 'Unknown').slice(0, 30))}</span>
      ${scoreBadge}
    </div>
    <div class="job-title">${escHtml(j.title || 'Untitled')}</div>
    <div class="meta-row">${remBadge}${expBadge}</div>
    ${flagsHtml ? `<div class="meta-row">${flagsHtml}</div>` : ''}
    ${matchedSkillsHtml ? `<div class="meta-row">${matchedSkillsHtml}</div>` : ''}
    ${descHtml}
    <div class="card-footer">${postedHtml}${applyBtn}</div>
  `;
  return card;
}

function clearFilters() {
  document.getElementById('searchInput').value = '';
  document.getElementById('hideSenior').checked = false;
  document.getElementById('hideGerman').checked = false;
  document.getElementById('hideUnpaid').checked = false;
  document.getElementById('nepalOnly').checked = false;
  document.getElementById('remoteToggle').checked = false;
  document.getElementById('senioritySelect').value = '';
  document.getElementById('minScoreSelect').value = '0';
  document.getElementById('sortSelect').value = 'match_desc';
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


class JobServerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

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
                            j.id, j.source, j.external_id, j.title, j.company_name,
                            j.location_raw, j.is_remote, j.remote_restriction,
                            j.job_type, j.experience_level, j.detected_language,
                            j.is_unpaid, j.nepal_accessible, j.description_text,
                            j.apply_url, j.tags, j.posted_at, j.salary_min, j.salary_max,
                            COALESCE(m.match_score, 0.0) as match_score,
                            COALESCE(m.matched_skills, '{}') as matched_skills,
                            m.score_breakdown
                        FROM jobs j
                        LEFT JOIN job_matches m ON m.job_id = j.id
                        ORDER BY m.match_score DESC NULLS LAST, j.posted_at DESC NULLS LAST
                        LIMIT 1000;
                    """)
                    rows = cur.fetchall()

            for r in rows:
                tags = r["tags"] or []
                tech = [t for t in tags if t.lower().strip() in TECH_KEYWORDS]
                posted = r["posted_at"].isoformat() if r["posted_at"] else None
                breakdown = r["score_breakdown"] or {}
                flags = breakdown.get("flags") or []

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
                    "experience_level": r["experience_level"] or "unspecified",
                    "detected_language": r["detected_language"] or "english",
                    "is_unpaid": bool(r["is_unpaid"]),
                    "nepal_accessible": bool(r["nepal_accessible"]),
                    "description": (r["description_text"] or "")[:400],
                    "apply_url": r["apply_url"],
                    "tags": tags,
                    "tech_tags": tech,
                    "match_score": float(r["match_score"]),
                    "matched_skills": r["matched_skills"] or [],
                    "flags": flags,
                    "posted_at": posted,
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
    print("  JOB PIPELINE & CV MATCHER DASHBOARD")
    print(f"  http://localhost:{port}")
    print("=" * 52)
    print("  Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
