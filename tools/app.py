#!/usr/bin/env python3
"""
app.py — Local Web Dashboard for Job Listings with CV Match Scoring,
Reachability Filtering, and In-Browser Human Labeling & Rating.

USAGE:
    python tools/app.py

SERVES:
    http://localhost:5000
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import urllib.parse
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler

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
<title>Job Pipeline & CV Matcher — Labeling Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f172a;--panel:#1e293b;--border:#334155;
  --accent:#38bdf8;--green:#4ade80;--red:#f87171;--amber:#fbbf24;--purple:#c084fc;
  --text:#f8fafc;--muted:#94a3b8;
  --radius:10px;
}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);min-height:100vh}

/* HEADER */
header{background:var(--panel);border-bottom:1px solid var(--border);padding:14px 28px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:10;flex-wrap:wrap;gap:10px}
header h1{font-size:1.25rem;color:var(--accent);letter-spacing:-0.5px}
.stats{display:flex;gap:10px;font-size:0.82rem;color:var(--muted);align-items:center;flex-wrap:wrap}
.stat-pill{background:rgba(56,189,248,.1);border:1px solid rgba(56,189,248,.2);padding:4px 10px;border-radius:20px;color:var(--accent);font-weight:600}
.stat-pill.green{background:rgba(74,222,128,.1);border-color:rgba(74,222,128,.2);color:var(--green)}
.stat-pill.purple{background:rgba(192,132,252,.12);border-color:rgba(192,132,252,.3);color:var(--purple)}

/* LAYOUT */
.layout{display:flex;height:calc(100vh - 54px)}
aside{width:320px;flex-shrink:0;background:var(--panel);border-right:1px solid var(--border);overflow-y:auto;padding:18px 16px;display:flex;flex-direction:column;gap:16px}
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
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}

/* CARD */
.card{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:18px;display:flex;flex-direction:column;gap:12px;transition:border-color .15s,transform .15s;position:relative}
.card:hover{border-color:var(--accent);transform:translateY(-2px)}
.card.high-match{border-color:rgba(74,222,128,.4);background:linear-gradient(180deg, rgba(74,222,128,.04) 0%, var(--panel) 100%)}
.card.is-good-fit{border-color:rgba(74,222,128,.6)}
.card.is-bad-fit{opacity:0.85;border-color:rgba(248,113,113,.4)}

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
.badge-reach-acc{background:rgba(74,222,128,.15);color:var(--green);border:1px solid rgba(74,222,128,.3)}
.badge-reach-unk{background:rgba(251,191,36,.12);color:var(--amber);border:1px solid rgba(251,191,36,.25)}
.badge-reach-blk{background:rgba(248,113,113,.12);color:var(--red);border:1px solid rgba(248,113,113,.25)}

.desc{font-size:0.84rem;color:#94a3b8;line-height:1.55;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}

/* LABELING & RATING BOX */
.label-box{background:rgba(15,23,42,.7);border:1px solid var(--border);border-radius:8px;padding:10px 12px;display:flex;flex-direction:column;gap:8px;margin-top:auto}
.label-top{display:flex;justify-content:space-between;align-items:center}
.label-heading{font-size:0.72rem;text-transform:uppercase;letter-spacing:0.8px;color:var(--muted);font-weight:700}
.badge-status{font-size:0.7rem;padding:2px 7px;border-radius:10px;font-weight:700}
.badge-status.unlabeled{background:rgba(148,163,184,.1);color:var(--muted);border:1px solid var(--border)}
.badge-status.good_fit{background:rgba(74,222,128,.15);color:var(--green);border:1px solid rgba(74,222,128,.3)}
.badge-status.maybe{background:rgba(251,191,36,.15);color:var(--amber);border:1px solid rgba(251,191,36,.3)}
.badge-status.bad_fit{background:rgba(248,113,113,.15);color:var(--red);border:1px solid rgba(248,113,113,.3)}

.rating-row{display:flex;align-items:center;justify-content:space-between;gap:6px}
.stars{display:flex;gap:3px;font-size:1.15rem;line-height:1}
.star{cursor:pointer;color:#475569;transition:color .12s,transform .12s;user-select:none}
.star:hover,.star.active{color:var(--amber);transform:scale(1.15)}
.rating-text{font-size:0.75rem;color:var(--muted);font-weight:600}

.btn-group{display:flex;gap:5px;align-items:center}
.fit-btn{flex:1;background:var(--panel);border:1px solid var(--border);color:var(--text);padding:6px 6px;border-radius:6px;font-size:0.75rem;font-weight:700;cursor:pointer;transition:all .15s;text-align:center;user-select:none}
.fit-btn:hover{filter:brightness(1.2)}
.fit-btn.good.active{background:rgba(74,222,128,.2);border-color:var(--green);color:var(--green);box-shadow:0 0 10px rgba(74,222,128,.25)}
.fit-btn.maybe.active{background:rgba(251,191,36,.2);border-color:var(--amber);color:var(--amber);box-shadow:0 0 10px rgba(251,191,36,.25)}
.fit-btn.bad.active{background:rgba(248,113,113,.2);border-color:var(--red);color:var(--red);box-shadow:0 0 10px rgba(248,113,113,.25)}
.btn-del{flex:0 0 26px;height:26px;background:transparent;border:1px solid var(--border);color:var(--muted);border-radius:6px;cursor:pointer;font-size:0.8rem;transition:all .15s}
.btn-del:hover{color:var(--red);border-color:var(--red)}

.notes-row{display:flex;gap:5px;margin-top:2px}
.notes-input{flex:1;background:var(--bg);border:1px solid var(--border);color:var(--text);font-size:0.78rem;padding:5px 8px;border-radius:5px;outline:none;transition:border-color .15s}
.notes-input:focus{border-color:var(--accent)}
.notes-save-btn{background:var(--panel);border:1px solid var(--border);color:var(--muted);font-size:0.73rem;padding:5px 8px;border-radius:5px;cursor:pointer;font-weight:600;transition:all .15s}
.notes-save-btn:hover{color:var(--accent);border-color:var(--accent)}

.card-footer{display:flex;justify-content:space-between;align-items:center;margin-top:4px;padding-top:10px;border-top:1px solid var(--border)}
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
    <span id="stat-labeled" class="stat-pill purple">🏷️ 0 Labeled</span>
    <span id="stat-showing">—</span>
  </div>
</header>

<div class="layout">
  <aside>
    <!-- Label & Rating Filter -->
    <div class="filter-section">
      <h3>🏷️ Human Label Filter</h3>
      <div class="filter-group">
        <select id="labelFilterSelect" onchange="applyFilters()">
          <option value="all">All Jobs (Labeled & Unlabeled)</option>
          <option value="unlabeled">⚡ Unlabeled Only (Ready to Label)</option>
          <option value="labeled">✓ Already Labeled</option>
          <option value="good_fit">👍 Good Fit Only</option>
          <option value="maybe">🤔 Maybe Only</option>
          <option value="bad_fit">👎 Bad Fit Only</option>
        </select>
      </div>
    </div>

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
          <input type="checkbox" id="nepalOnly">
        </div>
      </div>
    </div>

    <!-- Keyword Search -->
    <div class="filter-section">
      <h3>🔍 Keyword Search</h3>
      <div class="search-box">
        <input type="text" id="searchInput" placeholder="Python, React, Remote…" oninput="debouncedApply()">
      </div>
    </div>

    <!-- Reachability Filter -->
    <div class="filter-section">
      <h3>🇳🇵 Nepal Reachability</h3>
      <div class="filter-group">
        <select id="reachabilitySelect" onchange="applyFilters()">
          <option value="all">All Reachability States</option>
          <option value="accessible">Accessible Only</option>
          <option value="unknown">Unknown (Needs Check)</option>
          <option value="non_blocked">Accessible + Unknown (Non-blocked)</option>
          <option value="blocked">Blocked Only</option>
        </select>
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
          <option value="unlabeled_first">Unlabeled First</option>
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

  updateHeaderStats();
}

function updateHeaderStats() {
  const total = allJobs.length;
  const strongMatches = allJobs.filter(j => j.match_score >= 50).length;
  const labeled = allJobs.filter(j => j.user_label);
  const goodFit = labeled.filter(j => j.user_label === 'good_fit').length;
  const maybe = labeled.filter(j => j.user_label === 'maybe').length;
  const badFit = labeled.filter(j => j.user_label === 'bad_fit').length;

  document.getElementById('stat-total').innerText = `${total} total jobs`;
  document.getElementById('stat-matched').innerText = `${strongMatches} top matches (50%+)`;
  document.getElementById('stat-labeled').innerText = `🏷️ ${labeled.length} labeled (${goodFit} good, ${maybe} maybe, ${badFit} bad)`;
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
  const labelFilter = document.getElementById('labelFilterSelect').value;
  const hideSenior = document.getElementById('hideSenior').checked;
  const hideGerman = document.getElementById('hideGerman').checked;
  const hideUnpaid = document.getElementById('hideUnpaid').checked;
  const nepalOnly = document.getElementById('nepalOnly').checked;
  const reachability = document.getElementById('reachabilitySelect').value;
  const remoteOnly = document.getElementById('remoteToggle').checked;
  const seniority = document.getElementById('senioritySelect').value;
  const minScore = parseFloat(document.getElementById('minScoreSelect').value) || 0;
  const sort = document.getElementById('sortSelect').value;

  filtered = allJobs.filter(j => {
    // Label filter
    if (labelFilter === 'unlabeled' && j.user_label) return false;
    if (labelFilter === 'labeled' && !j.user_label) return false;
    if (labelFilter === 'good_fit' && j.user_label !== 'good_fit') return false;
    if (labelFilter === 'maybe' && j.user_label !== 'maybe') return false;
    if (labelFilter === 'bad_fit' && j.user_label !== 'bad_fit') return false;

    // Reachability
    if (reachability === 'accessible' && j.reachable_from_nepal !== 'accessible') return false;
    if (reachability === 'unknown' && j.reachable_from_nepal !== 'unknown') return false;
    if (reachability === 'non_blocked' && j.reachable_from_nepal === 'blocked') return false;
    if (reachability === 'blocked' && j.reachable_from_nepal !== 'blocked') return false;

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
    if (sort === 'unlabeled_first') {
      const aLab = a.user_label ? 1 : 0;
      const bLab = b.user_label ? 1 : 0;
      if (aLab !== bLab) return aLab - bLab;
      return (b.match_score || 0) - (a.match_score || 0);
    }
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
    grid.innerHTML = '<div class="no-results" style="grid-column:1/-1"><h2>No matching jobs found</h2><p>Try clearing your filters or changing the label filter.</p></div>';
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
  let cardClass = 'card';
  if (j.user_label === 'good_fit') cardClass += ' is-good-fit';
  else if (j.user_label === 'bad_fit') cardClass += ' is-bad-fit';
  else if (isHighMatch) cardClass += ' high-match';
  card.className = cardClass;
  card.id = `card-${j.id}`;

  // Score Badge
  let scoreClass = 'score-low';
  if (j.match_score >= 60) scoreClass = 'score-high';
  else if (j.match_score >= 35) scoreClass = 'score-mid';
  const scoreBadge = `<span class="score-badge ${scoreClass}">🎯 ${Math.round(j.match_score)}% Match</span>`;

  // Remote badge
  const remBadge = j.is_remote
    ? `<span class="badge badge-remote">🌐 Remote</span>`
    : `<span class="badge badge-onsite">🏢 On-site</span>`;

  // Reachability badge
  let reachBadge = '';
  if (j.reachable_from_nepal === 'accessible') {
    reachBadge = `<span class="badge badge-reach-acc">🇳🇵 Accessible</span>`;
  } else if (j.reachable_from_nepal === 'blocked') {
    reachBadge = `<span class="badge badge-reach-blk" title="${escHtml(j.reachable_reason || '')}">🚫 Blocked</span>`;
  } else {
    reachBadge = `<span class="badge badge-reach-unk" title="${escHtml(j.reachable_reason || '')}">❓ Unknown</span>`;
  }

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

  // Label section markup
  const labelBoxHtml = renderLabelBox(j);

  card.innerHTML = `
    <div class="card-top">
      <span class="company">${escHtml((j.company_name || 'Unknown').slice(0, 30))}</span>
      ${scoreBadge}
    </div>
    <div class="job-title">${escHtml(j.title || 'Untitled')}</div>
    <div class="meta-row">${remBadge}${reachBadge}${expBadge}</div>
    ${flagsHtml ? `<div class="meta-row">${flagsHtml}</div>` : ''}
    ${matchedSkillsHtml ? `<div class="meta-row">${matchedSkillsHtml}</div>` : ''}
    ${descHtml}
    ${labelBoxHtml}
    <div class="card-footer">${postedHtml}${applyBtn}</div>
  `;
  return card;
}

function renderLabelBox(j) {
  const currentLabel = j.user_label || '';
  const currentRating = j.user_rating || 0;
  const currentNotes = j.user_notes || '';

  let statusBadge = '<span class="badge-status unlabeled">Unlabeled</span>';
  if (currentLabel === 'good_fit') statusBadge = '<span class="badge-status good_fit">✓ Good Fit</span>';
  else if (currentLabel === 'maybe') statusBadge = '<span class="badge-status maybe">✓ Maybe</span>';
  else if (currentLabel === 'bad_fit') statusBadge = '<span class="badge-status bad_fit">✓ Bad Fit</span>';

  const starsHtml = [1, 2, 3, 4, 5].map(starNum => {
    const active = starNum <= currentRating ? 'active' : '';
    return `<span class="star ${active}" onclick="rateJob('${j.id}', ${starNum})" title="${starNum} Star${starNum > 1 ? 's' : ''}">★</span>`;
  }).join('');

  const ratingText = currentRating > 0 ? `${currentRating}/5` : '';

  return `
    <div class="label-box" id="label-box-${j.id}">
      <div class="label-top">
        <span class="label-heading">🏷️ Fit Label & Rating</span>
        <span id="badge-status-${j.id}">${statusBadge}</span>
      </div>

      <div class="rating-row">
        <div class="stars" id="stars-${j.id}">
          ${starsHtml}
        </div>
        <span class="rating-text" id="rating-text-${j.id}">${ratingText}</span>
      </div>

      <div class="btn-group">
        <button class="fit-btn good ${currentLabel === 'good_fit' ? 'active' : ''}" onclick="labelJob('${j.id}', 'good_fit')">
          👍 Good Fit
        </button>
        <button class="fit-btn maybe ${currentLabel === 'maybe' ? 'active' : ''}" onclick="labelJob('${j.id}', 'maybe')">
          🤔 Maybe
        </button>
        <button class="fit-btn bad ${currentLabel === 'bad_fit' ? 'active' : ''}" onclick="labelJob('${j.id}', 'bad_fit')">
          👎 Bad Fit
        </button>
        ${currentLabel ? `<button class="btn-del" title="Clear label" onclick="labelJob('${j.id}', 'clear')">✕</button>` : ''}
      </div>

      <div class="notes-row">
        <input type="text" class="notes-input" id="notes-${j.id}" placeholder="Notes (e.g. requires 5+ yrs)..." value="${escHtml(currentNotes)}" onkeydown="if(event.key==='Enter') saveNotes('${j.id}')">
        <button class="notes-save-btn" id="notes-btn-${j.id}" onclick="saveNotes('${j.id}')">Save</button>
      </div>
    </div>
  `;
}

async function labelJob(jobId, label) {
  const job = allJobs.find(j => j.id === jobId);
  const notesInput = document.getElementById(`notes-${jobId}`);
  const notes = notesInput ? notesInput.value.trim() : (job ? job.user_notes : '');

  let rating = job ? job.user_rating : null;
  if (label === 'good_fit' && (!rating || rating < 4)) rating = 5;
  else if (label === 'maybe' && (!rating || rating !== 3)) rating = 3;
  else if (label === 'bad_fit' && (!rating || rating > 2)) rating = 1;
  else if (label === 'clear') rating = null;

  try {
    const res = await fetch('/api/label', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: jobId,
        label: label,
        notes: notes,
        rating: rating,
      }),
    });
    const data = await res.json();
    if (data.success) {
      if (job) {
        job.user_label = data.label;
        job.user_notes = data.notes;
        job.user_rating = data.rating;
      }
      updateCardLabelUI(jobId);
      updateHeaderStats();
    } else {
      alert('Error saving label: ' + (data.error || 'Unknown error'));
    }
  } catch (err) {
    alert('Network error saving label: ' + err.message);
  }
}

async function rateJob(jobId, stars) {
  const job = allJobs.find(j => j.id === jobId);
  let label = 'good_fit';
  if (stars <= 2) label = 'bad_fit';
  else if (stars === 3) label = 'maybe';
  else label = 'good_fit';

  const notesInput = document.getElementById(`notes-${jobId}`);
  const notes = notesInput ? notesInput.value.trim() : (job ? job.user_notes : '');

  try {
    const res = await fetch('/api/label', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: jobId,
        label: label,
        notes: notes,
        rating: stars,
      }),
    });
    const data = await res.json();
    if (data.success) {
      if (job) {
        job.user_label = data.label;
        job.user_notes = data.notes;
        job.user_rating = data.rating;
      }
      updateCardLabelUI(jobId);
      updateHeaderStats();
    }
  } catch (err) {
    alert('Network error saving rating: ' + err.message);
  }
}

async function saveNotes(jobId) {
  const job = allJobs.find(j => j.id === jobId);
  if (!job) return;

  const notesInput = document.getElementById(`notes-${jobId}`);
  const notes = notesInput ? notesInput.value.trim() : '';
  const label = job.user_label || 'maybe';
  const rating = job.user_rating || null;
  const btn = document.getElementById(`notes-btn-${jobId}`);

  try {
    const res = await fetch('/api/label', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: jobId,
        label: label,
        notes: notes,
        rating: rating,
      }),
    });
    const data = await res.json();
    if (data.success) {
      job.user_notes = data.notes;
      if (btn) {
        btn.innerText = '✓ Saved';
        btn.style.color = 'var(--green)';
        setTimeout(() => {
          if (btn) {
            btn.innerText = 'Save';
            btn.style.color = '';
          }
        }, 1500);
      }
    }
  } catch (err) {
    alert('Failed to save notes: ' + err.message);
  }
}

function updateCardLabelUI(jobId) {
  const job = allJobs.find(j => j.id === jobId);
  if (!job) return;

  const box = document.getElementById(`label-box-${jobId}`);
  if (box) {
    box.outerHTML = renderLabelBox(job);
  }

  const card = document.getElementById(`card-${jobId}`);
  if (card) {
    card.classList.remove('is-good-fit', 'is-bad-fit');
    if (job.user_label === 'good_fit') card.classList.add('is-good-fit');
    else if (job.user_label === 'bad_fit') card.classList.add('is-bad-fit');
  }
}

function clearFilters() {
  document.getElementById('searchInput').value = '';
  document.getElementById('labelFilterSelect').value = 'all';
  document.getElementById('reachabilitySelect').value = 'all';
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

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/label":
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length)
            try:
                data = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                self._respond(400, "application/json", json.dumps({"error": "Invalid JSON body"}).encode())
                return

            res, code = self._handle_label_job(data)
            self._respond(code, "application/json", json.dumps(res).encode())
        else:
            self._respond(404, "text/plain", b"Not found")

    def _respond(self, code, content_type, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_label_job(self, data: dict):
        """Save or clear human label & rating in laya_labels table."""
        job_id_str = str(data.get("job_id") or "").strip()
        label = str(data.get("label") or "").strip().lower()
        notes = str(data.get("notes") or "").strip()
        rating = data.get("rating")

        if rating is not None:
            try:
                rating = int(rating)
                if not (1 <= rating <= 5):
                    rating = None
            except (ValueError, TypeError):
                rating = None

        if not job_id_str:
            return {"error": "Missing job_id"}, 400

        try:
            job_uuid = uuid.UUID(job_id_str)
        except ValueError:
            return {"error": f"Invalid UUID: {job_id_str}"}, 400

        # Handle clear/remove label
        if label in ("clear", "unlabeled", "none", ""):
            try:
                with get_connection(autocommit=True) as conn:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM laya_labels WHERE job_id = %s;", (str(job_uuid),))
                return {
                    "success": True,
                    "job_id": str(job_uuid),
                    "label": None,
                    "notes": "",
                    "rating": None,
                }, 200
            except Exception as exc:
                logger.error("Error clearing label for %s: %s", job_id_str, exc)
                return {"error": str(exc)}, 500

        VALID_LABELS = {"good_fit", "maybe", "bad_fit"}
        if label not in VALID_LABELS:
            return {"error": f"Invalid label '{label}'. Must be one of {list(VALID_LABELS)}"}, 400

        metadata = {
            "source": "web_ui",
            "rating": rating,
        }

        gate_failed = data.get("gate_failed")
        workplace_type = data.get("workplace_type")
        country_restriction = data.get("country_restriction")
        seniority = data.get("seniority")
        degree_required = str(data.get("degree_required")) if data.get("degree_required") is not None else None
        years_required = data.get("years_required")
        pay_type = data.get("pay_type")
        tz_overlap_required = data.get("tz_overlap_required")

        try:
            with get_connection(autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO laya_labels
                            (job_id, label, notes, metadata, sampling_stratum, label_guideline_version,
                             gate_failed, workplace_type, country_restriction, seniority, degree_required,
                             years_required, pay_type, tz_overlap_required, labeled_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (job_id, labeled_at) DO UPDATE SET
                            label = EXCLUDED.label,
                            notes = EXCLUDED.notes,
                            metadata = EXCLUDED.metadata,
                            gate_failed = EXCLUDED.gate_failed,
                            workplace_type = EXCLUDED.workplace_type,
                            country_restriction = EXCLUDED.country_restriction,
                            seniority = EXCLUDED.seniority,
                            degree_required = EXCLUDED.degree_required,
                            years_required = EXCLUDED.years_required,
                            pay_type = EXCLUDED.pay_type,
                            tz_overlap_required = EXCLUDED.tz_overlap_required;
                    """, (
                        str(job_uuid),
                        label,
                        notes,
                        json.dumps(metadata),
                        "web_ui",
                        "v1",
                        gate_failed,
                        workplace_type,
                        country_restriction,
                        seniority,
                        degree_required,
                        years_required,
                        pay_type,
                        tz_overlap_required,
                    ))
            return {
                "success": True,
                "job_id": str(job_uuid),
                "label": label,
                "notes": notes,
                "rating": rating,
            }, 200
        except Exception as exc:
            logger.error("Error saving label for %s: %s", job_id_str, exc)
            return {"error": str(exc)}, 500

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
                            j.is_unpaid, j.nepal_accessible, j.reachable_from_nepal, j.reachable_reason,
                            j.description_text, j.apply_url, j.tags, j.posted_at, j.salary_min, j.salary_max,
                            COALESCE(m.match_score, 0.0) as match_score,
                            COALESCE(m.matched_skills, '{}') as matched_skills,
                            m.score_breakdown,
                            lbl.label as user_label,
                            lbl.notes as user_notes,
                            lbl.metadata as user_metadata,
                            lbl.labeled_at as user_labeled_at
                        FROM jobs j
                        LEFT JOIN job_matches m ON m.job_id = j.id
                        LEFT JOIN LATERAL (
                            SELECT label, notes, metadata, labeled_at
                            FROM laya_labels
                            WHERE job_id = j.id
                            ORDER BY labeled_at DESC
                            LIMIT 1
                        ) lbl ON TRUE
                        ORDER BY m.match_score DESC NULLS LAST, j.posted_at DESC NULLS LAST
                        LIMIT 3000;
                    """)
                    rows = cur.fetchall()

            for r in rows:
                tags = r["tags"] or []
                tech = [t for t in tags if t.lower().strip() in TECH_KEYWORDS]
                posted = r["posted_at"].isoformat() if r["posted_at"] else None
                breakdown = r["score_breakdown"] or {}
                flags = breakdown.get("flags") or []

                meta = r.get("user_metadata") or {}
                rating = meta.get("rating") if isinstance(meta, dict) else None

                jobs.append({
                    "id": str(r["id"]),
                    "source": r["source"],
                    "external_id": r["external_id"],
                    "title": r["title"],
                    "company_name": r["company_name"],
                    "location_raw": r["location_raw"],
                    "is_remote": r["is_remote"],
                    "remote_restriction": r["remote_restriction"],
                    "reachable_from_nepal": r.get("reachable_from_nepal") or "unknown",
                    "reachable_reason": r.get("reachable_reason") or "",
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
                    "user_label": r.get("user_label"),
                    "user_notes": r.get("user_notes") or "",
                    "user_rating": rating,
                    "user_labeled_at": r["user_labeled_at"].isoformat() if r.get("user_labeled_at") else None,
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
    print("=" * 56)
    print("  JOB PIPELINE & CV MATCHER — IN-BROWSER LABELING")
    print(f"  http://localhost:{port}")
    print("=" * 56)
    print("  Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
