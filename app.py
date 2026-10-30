#!/usr/bin/env python3
"""app.py — Local Web Dashboard & Feedback Loop (Step 5).

Provides:
- 4-Column Layout across Feed, Rejected, and Ollama Triage tabs:
  1. Job & Company Details
  2. Scores & Filters (MatchScorer, Laya Neural, Title-Rule, HardFilter)
  3. 🤖 Distinct Ollama Triage Column (Verdict pill, confidence bar, reasoning, bucket)
  4. Human Label & Action (One-click Accept, Good Fit, Maybe, Bad Fit, notes, wrongly_filtered)
- Feed Tab: Top jobs ranked by title-rule score and MatchScorer, showing Ollama triage verdict.
- Rejected Tab: Jobs that failed HardFilter grouped by failure reason with trigger snippet.
- Triage Tab: Dedicated view of Ollama active-learning suggestions from triage_suggestions_*.json.
- Header: Last daily run time, new jobs count, active model version, 150/30 training gate progress,
  and stale run warning (> 36 hours).
"""
import argparse
from datetime import datetime, timezone
import glob
import json
import logging
from pathlib import Path
import re
import sys
import urllib.parse
import uuid
from typing import Any
from http.server import HTTPServer, BaseHTTPRequestHandler

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection, execute_query
from src.matching.hard_filter import apply as apply_hard_filter, FilterReason
from src.matching.title_classifier import predict_tech_probability, get_title_role_penalty
from scripts.make_labeling_batch import score_title_rule, BOOST_WORDS, PENALTY_WORDS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_all_triage_suggestions():
    """Load and merge all triage_suggestions_*.json from data/ directory keyed by job_id."""
    data_dir = PROJECT_ROOT / "data"
    files = sorted(glob.glob(str(data_dir / "triage_suggestions_*.json")))
    merged = {}
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                items = data if isinstance(data, list) else data.get("suggestions", [])
                for item in items:
                    jid = item.get("job_id")
                    if jid:
                        merged[str(jid)] = item
        except Exception as e:
            logger.warning("Could not read triage file %s: %s", f, e)
    return merged


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Radar — Active Labeling Feedback Loop</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#090d16;--card-bg:#131c2e;--panel:#1a243b;--border:#263554;
    --accent:#38bdf8;--green:#22c55e;--green-dim:rgba(34,197,94,0.15);
    --amber:#f59e0b;--amber-dim:rgba(245,158,11,0.15);
    --red:#ef4444;--red-dim:rgba(239,68,68,0.15);
    --purple:#a78bfa;--purple-dim:rgba(167,139,250,0.15);
    --text:#f8fafc;--muted:#94a3b8;--radius:10px;
  }
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;flex-direction:column}
  
  /* HEADER */
  header{background:var(--panel);border-bottom:1px solid var(--border);padding:14px 28px;position:sticky;top:0;z-index:50}
  .header-top{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}
  .brand{display:flex;align-items:center;gap:12px}
  .brand h1{font-size:1.25rem;color:var(--accent);letter-spacing:-0.5px}
  .badge-model{background:rgba(56,189,248,0.15);border:1px solid var(--accent);color:var(--accent);padding:3px 8px;border-radius:6px;font-size:0.75rem;font-weight:600}
  
  .stats-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-size:0.82rem}
  .stat-pill{background:var(--card-bg);border:1px solid var(--border);padding:5px 12px;border-radius:20px;color:var(--text);font-weight:500}
  .stat-pill strong{color:var(--accent)}
  .stat-pill.gate{border-color:var(--amber);background:var(--amber-dim);color:var(--amber)}
  
  .warning-banner{margin-top:10px;background:rgba(239,68,68,0.2);border:1px solid var(--red);color:#fca5a5;padding:8px 14px;border-radius:8px;font-size:0.85rem;display:flex;align-items:center;gap:8px}
  
  /* TABS */
  .tabs-bar{display:flex;gap:8px;background:var(--bg);padding:12px 28px 0;border-bottom:1px solid var(--border)}
  .tab-btn{background:transparent;border:none;border-bottom:3px solid transparent;color:var(--muted);padding:10px 18px;font-size:0.95rem;font-weight:600;cursor:pointer;transition:all 0.15s ease}
  .tab-btn:hover{color:var(--text)}
  .tab-btn.active{color:var(--accent);border-bottom-color:var(--accent)}
  .tab-btn .badge{background:var(--panel);padding:2px 8px;border-radius:12px;font-size:0.75rem;margin-left:6px;color:var(--muted)}
  .tab-btn.active .badge{background:rgba(56,189,248,0.2);color:var(--accent)}
  .tab-btn.triage-tab.active{color:var(--purple);border-bottom-color:var(--purple)}
  .tab-btn.triage-tab.active .badge{background:var(--purple-dim);color:var(--purple)}
  .tab-btn.triage-tab.has-pending{color:var(--purple)}
  .tab-btn.triage-tab.has-pending .badge{background:var(--purple-dim);color:var(--purple)}
  
  /* MAIN CONTENT */
  main{flex:1;max-width:1500px;margin:0 auto;width:100%;padding:20px 24px;display:flex;flex-direction:column;gap:16px}
  
  .filter-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--panel);padding:12px 16px;border-radius:var(--radius);border:1px solid var(--border)}
  .filter-bar span{font-size:0.8rem;color:var(--muted);text-transform:uppercase;font-weight:700}
  .pill-filter{background:var(--card-bg);border:1px solid var(--border);color:var(--muted);padding:4px 12px;border-radius:16px;font-size:0.8rem;cursor:pointer}
  .pill-filter:hover{color:var(--text);border-color:var(--accent)}
  .pill-filter.active{background:var(--accent);color:#090d16;border-color:var(--accent);font-weight:700}
  
  /* GRID COLUMN HEADERS BAR */
  .column-headers{
    display:grid;
    grid-template-columns: 2.2fr 1.2fr 2fr 1.4fr;
    gap:16px;
    padding:8px 20px;
    background:rgba(26,36,59,0.5);
    border:1px solid var(--border);
    border-radius:8px;
    font-size:0.75rem;
    font-weight:700;
    color:var(--muted);
    letter-spacing:0.5px;
    text-transform:uppercase;
  }
  @media (max-width:1150px){ .column-headers{display:none} }
  
  /* JOB CARDS: 4 DISTINCT COLUMNS */
  .jobs-list{display:flex;flex-direction:column;gap:14px}
  .job-card{
    background:var(--card-bg);
    border:1px solid var(--border);
    border-radius:var(--radius);
    padding:16px 20px;
    display:grid;
    grid-template-columns: 2.2fr 1.2fr 2fr 1.4fr;
    gap:16px;
    align-items:stretch;
    transition:border-color 0.15s, opacity 0.3s ease;
  }
  .job-card:hover{border-color:#38bdf8}
  .job-card.labeled{opacity:0.25;pointer-events:none}
  
  @media (max-width:1150px){
    .job-card{grid-template-columns:1fr;gap:14px}
  }

  /* COLUMN 1: JOB DETAILS */
  .col-job{display:flex;flex-direction:column;gap:6px;border-right:1px solid rgba(38,53,84,0.6);padding-right:14px}
  @media (max-width:1150px){ .col-job{border-right:none;border-bottom:1px solid var(--border);padding-bottom:12px;padding-right:0} }
  .col-label-tag{font-size:0.68rem;color:var(--muted);text-transform:uppercase;font-weight:800;letter-spacing:0.6px;margin-bottom:2px}
  .job-title{font-size:1.05rem;font-weight:700;color:var(--text);text-decoration:none;line-height:1.3}
  .job-title:hover{color:var(--accent);text-decoration:underline}
  .job-company{font-size:0.88rem;color:#cbd5e1;font-weight:600}
  .job-location{font-size:0.8rem;color:var(--muted)}
  .tags-row{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
  .word-tag{display:inline-block;padding:2px 6px;border-radius:4px;font-size:0.72rem;font-weight:600}
  .tag-boost{background:rgba(34,197,94,0.15);color:var(--green);border:1px solid rgba(34,197,94,0.3)}
  .tag-penalty{background:rgba(239,68,68,0.15);color:var(--red);border:1px solid rgba(239,68,68,0.3)}
  .muted-tag{color:var(--muted);font-size:0.72rem}

  /* COLUMN 2: SCORES & FILTERS */
  .col-scores{display:flex;flex-direction:column;gap:6px;border-right:1px solid rgba(38,53,84,0.6);padding-right:14px;font-size:0.82rem}
  @media (max-width:1150px){ .col-scores{border-right:none;border-bottom:1px solid var(--border);padding-bottom:12px;padding-right:0} }
  .score-row{display:flex;justify-content:space-between;align-items:center}
  .score-val{font-weight:700}
  .score-val.ms{color:var(--accent)}
  .score-val.laya{color:var(--purple)}
  .chip-hf{padding:2px 6px;border-radius:4px;font-size:0.72rem;font-weight:700;text-transform:uppercase}
  .chip-hf.pass{background:var(--green-dim);color:var(--green);border:1px solid var(--green)}
  .chip-hf.review{background:var(--amber-dim);color:var(--amber);border:1px solid var(--amber)}
  .chip-hf.fail{background:var(--red-dim);color:var(--red);border:1px solid var(--red)}

  /* COLUMN 3: OLLAMA TRIAGE (DISTINCT COLUMN) */
  .col-triage{
    display:flex;
    flex-direction:column;
    gap:6px;
    border-right:1px solid rgba(38,53,84,0.6);
    padding-right:14px;
    background:rgba(167,139,250,0.03);
    padding:8px 12px;
    border-radius:6px;
    border:1px solid rgba(167,139,250,0.15);
  }
  @media (max-width:1150px){ .col-triage{border-right:none;border-bottom:1px solid var(--border);padding-bottom:12px;padding-right:0} }
  .triage-header-line{display:flex;justify-content:space-between;align-items:center;gap:6px;flex-wrap:wrap}
  .ollama-pill{padding:3px 10px;border-radius:14px;font-size:0.75rem;font-weight:800;text-transform:uppercase;letter-spacing:0.4px}
  .ollama-good{background:var(--green-dim);color:var(--green);border:1px solid var(--green)}
  .ollama-maybe{background:var(--amber-dim);color:var(--amber);border:1px solid var(--amber)}
  .ollama-bad{background:var(--red-dim);color:var(--red);border:1px solid var(--red)}
  .bucket-pill{padding:2px 8px;border-radius:4px;font-size:0.7rem;font-weight:700;text-transform:uppercase;background:var(--purple-dim);color:var(--purple);border:1px solid rgba(167,139,250,0.3)}
  .conf-bar-wrap{display:flex;align-items:center;gap:6px;margin:2px 0}
  .conf-bar-bg{flex:1;height:5px;background:var(--border);border-radius:3px;overflow:hidden}
  .conf-bar-fill{height:100%;border-radius:3px}
  .conf-label{font-size:0.72rem;color:var(--muted);white-space:nowrap}
  .ollama-quote{font-size:0.76rem;color:#cbd5e1;font-style:italic;line-height:1.3;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
  .triage-empty{color:var(--muted);font-size:0.78rem;font-style:italic;display:flex;flex-direction:column;gap:4px;justify-content:center;height:100%}

  /* COLUMN 4: HUMAN ACTION & LABEL */
  .col-action{display:flex;flex-direction:column;gap:8px}
  .accept-btn{
    border:1px solid rgba(167,139,250,0.5);
    background:rgba(167,139,250,0.18);
    color:var(--purple);
    font-weight:700;
    padding:6px 12px;
    border-radius:6px;
    font-size:0.8rem;
    cursor:pointer;
    transition:all 0.15s ease;
    display:flex;
    align-items:center;
    justify-content:center;
    gap:4px;
  }
  .accept-btn:hover{background:rgba(167,139,250,0.3);filter:brightness(1.15)}
  .btn-group{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px}
  .btn-label{border:none;padding:6px 4px;border-radius:6px;font-size:0.78rem;font-weight:700;cursor:pointer;transition:transform 0.08s ease, filter 0.15s ease;text-align:center}
  .btn-label:hover{filter:brightness(1.15);transform:translateY(-1px)}
  .btn-label:active{transform:translateY(1px)}
  .btn-good{background:var(--green);color:#090d16}
  .btn-maybe{background:var(--amber);color:#090d16}
  .btn-bad{background:var(--red);color:#ffffff}
  .reason-input{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:6px;font-size:0.78rem;outline:none}
  .reason-input:focus{border-color:var(--accent)}
  .wrong-toggle{display:flex;align-items:center;gap:6px;font-size:0.75rem;color:var(--muted);cursor:pointer;user-select:none}
  .wrong-toggle input{accent-color:var(--amber);cursor:pointer;width:14px;height:14px}
  .labeled-banner{display:none;background:var(--green-dim);border:1px solid var(--green);color:var(--green);padding:4px 8px;border-radius:6px;font-size:0.78rem;font-weight:600;text-align:center}
  .failure-snippet{color:#f87171;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;background:rgba(239,68,68,0.1);padding:4px 8px;border-radius:4px;font-size:0.75rem;display:block;margin-top:2px}
</style>
</head>
<body>

<header>
  <div class="header-top">
    <div class="brand">
      <h1>⚡ Job Radar</h1>
      <span class="badge-model" id="headerModelVer">Ranker v1 (Title-Rule + Soft Classifier)</span>
    </div>
    <div class="stats-row">
      <div class="stat-pill" id="statLastRun">Last Run: <strong>Loading...</strong></div>
      <div class="stat-pill" id="statNewJobs">New Jobs: <strong>Loading...</strong></div>
      <div class="stat-pill gate" id="statGateProgress">v2 labels: <strong>...</strong></div>
    </div>
  </div>
  <div id="staleWarning" class="warning-banner" style="display:none">
    ⚠️ <strong>Daily run is stale (&gt;36 hours old)!</strong> Run <code>python scripts/run_daily.py</code> to fetch fresh remote jobs.
  </div>
</header>

<div class="tabs-bar">
  <button class="tab-btn active" id="tabFeedBtn" onclick="switchTab('feed')">
    🌐 Feed (Passing Jobs) <span class="badge" id="feedCount">0</span>
  </button>
  <button class="tab-btn triage-tab" id="tabTriageBtn" onclick="switchTab('triage')">
    🤖 Ollama Triage <span class="badge" id="triageCount">0</span>
  </button>
  <button class="tab-btn" id="tabRejectedBtn" onclick="switchTab('rejected')">
    🚫 Rejected (HardFilter Audit) <span class="badge" id="rejectedCount">0</span>
  </button>
</div>

<main>
  <!-- Feed Tab Controls -->
  <div id="feedControls" class="filter-bar">
    <span>Sort:</span>
    <button class="pill-filter active" onclick="setFeedSort('rule', this)">Title-Rule Score</button>
    <button class="pill-filter" onclick="setFeedSort('match', this)">MatchScorer</button>
    <button class="pill-filter" onclick="setFeedSort('date', this)">Newest</button>
  </div>

  <!-- Triage Tab Controls -->
  <div id="triageControls" class="filter-bar" style="display:none">
    <span>Filter Bucket:</span>
    <button class="pill-filter active" onclick="filterTriage('ALL', this)">ALL</button>
    <button class="pill-filter" onclick="filterTriage('CONFLICT', this)">CONFLICT</button>
    <button class="pill-filter" onclick="filterTriage('UNCERTAIN', this)">UNCERTAIN</button>
    <button class="pill-filter" onclick="filterTriage('STRONG_CAND', this)">STRONG_CAND</button>
  </div>

  <!-- Rejected Tab Controls -->
  <div id="rejectedControls" class="filter-bar" style="display:none">
    <span>Filter Failure Reason:</span>
    <button class="pill-filter active" onclick="filterRejected('ALL', this)">ALL</button>
    <button class="pill-filter" onclick="filterRejected('TOO_SENIOR', this)">TOO_SENIOR</button>
    <button class="pill-filter" onclick="filterRejected('DEGREE_OR_EXP', this)">DEGREE_OR_EXP</button>
    <button class="pill-filter" onclick="filterRejected('REGION_LOCKED', this)">REGION_LOCKED</button>
    <button class="pill-filter" onclick="filterRejected('NOT_REMOTE', this)">NOT_REMOTE</button>
    <button class="pill-filter" onclick="filterRejected('NON_TECHNICAL', this)">NON_TECHNICAL</button>
    <button class="pill-filter" onclick="filterRejected('NON_ENGLISH', this)">NON_ENGLISH</button>
    <button class="pill-filter" onclick="filterRejected('UNPAID', this)">UNPAID</button>
  </div>

  <!-- 4 Column Headers Bar -->
  <div class="column-headers">
    <div>1. Job & Company</div>
    <div>2. Scores & Filters</div>
    <div id="col3Header">3. 🤖 Ollama Triage Column</div>
    <div>4. Human Label & Action</div>
  </div>

  <div id="jobsList" class="jobs-list">
    <div style="text-align:center;color:var(--muted);padding:40px;">Loading jobs...</div>
  </div>
</main>

<script>
let currentTab = 'feed';
let allFeedJobs = [];
let allRejectedJobs = [];
let allTriageJobs = [];
let currentRejectedFilter = 'ALL';
let currentFeedSort = 'rule';
let currentTriageFilter = 'ALL';

async function fetchStats() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    document.getElementById('statLastRun').innerHTML = `Last Run: <strong>${data.last_run_display}</strong>`;
    document.getElementById('statNewJobs').innerHTML = `New (24h): <strong>+${data.new_jobs_24h}</strong>`;
    document.getElementById('statGateProgress').innerHTML = `v2: <strong>${data.v2_total}/150</strong> | good_fit: <strong>${data.v2_good_fit}/30</strong>`;
    document.getElementById('headerModelVer').textContent = data.model_version;
    if (data.is_stale) {
      document.getElementById('staleWarning').style.display = 'flex';
    } else {
      document.getElementById('staleWarning').style.display = 'none';
    }
  } catch (err) { console.error('Failed to fetch stats:', err); }
}

async function loadFeed() {
  try {
    const res = await fetch('/api/feed');
    allFeedJobs = await res.json();
    document.getElementById('feedCount').textContent = allFeedJobs.length;
    if (currentTab === 'feed') renderFeed();
  } catch (err) { console.error('Failed to load feed:', err); }
}

async function loadRejected() {
  try {
    const res = await fetch('/api/rejected');
    allRejectedJobs = await res.json();
    document.getElementById('rejectedCount').textContent = allRejectedJobs.length;
    if (currentTab === 'rejected') renderRejected();
  } catch (err) { console.error('Failed to load rejected jobs:', err); }
}

async function loadTriage() {
  try {
    const res = await fetch('/api/triage');
    const data = await res.json();
    allTriageJobs = data.suggestions || [];
    const pending = allTriageJobs.filter(j => !j.already_labeled).length;
    document.getElementById('triageCount').textContent = pending;
    const tabBtn = document.getElementById('tabTriageBtn');
    if (pending > 0) tabBtn.classList.add('has-pending');
    else tabBtn.classList.remove('has-pending');
    if (currentTab === 'triage') renderTriage();
  } catch (err) { console.error('Failed to load triage:', err); }
}

function switchTab(tab) {
  currentTab = tab;
  document.getElementById('tabFeedBtn').classList.toggle('active', tab === 'feed');
  document.getElementById('tabTriageBtn').classList.toggle('active', tab === 'triage');
  document.getElementById('tabRejectedBtn').classList.toggle('active', tab === 'rejected');
  
  document.getElementById('feedControls').style.display = tab === 'feed' ? 'flex' : 'none';
  document.getElementById('triageControls').style.display = tab === 'triage' ? 'flex' : 'none';
  document.getElementById('rejectedControls').style.display = tab === 'rejected' ? 'flex' : 'none';
  
  const col3Hdr = document.getElementById('col3Header');
  if (tab === 'rejected') col3Hdr.textContent = '3. 🚫 Disqualification Trigger';
  else col3Hdr.textContent = '3. 🤖 Ollama Triage Column';

  if (tab === 'feed') renderFeed();
  else if (tab === 'triage') renderTriage();
  else renderRejected();
}

function setFeedSort(mode, btn) {
  currentFeedSort = mode;
  document.querySelectorAll('#feedControls .pill-filter').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderFeed();
}

function filterTriage(bucket, btn) {
  currentTriageFilter = bucket;
  document.querySelectorAll('#triageControls .pill-filter').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderTriage();
}

function filterRejected(reason, btn) {
  currentRejectedFilter = reason;
  document.querySelectorAll('#rejectedControls .pill-filter').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderRejected();
}

function renderFeed() {
  const container = document.getElementById('jobsList');
  let list = [...allFeedJobs];
  if (currentFeedSort === 'rule') list.sort((a,b) => b.title_score - a.title_score);
  else if (currentFeedSort === 'match') list.sort((a,b) => b.match_score - a.match_score);
  else if (currentFeedSort === 'date') list.sort((a,b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));

  if (!list.length) {
    container.innerHTML = `<div style="text-align:center;padding:50px;color:var(--muted)">No passing jobs to display. All current accessible jobs are labeled!</div>`;
    return;
  }
  container.innerHTML = list.map(j => renderCard(j, 'feed')).join('');
}

function renderTriage() {
  const container = document.getElementById('jobsList');
  let list = currentTriageFilter === 'ALL' ? allTriageJobs : allTriageJobs.filter(j => j.bucket === currentTriageFilter);
  list = [...list].sort((a, b) => {
    if (a.already_labeled !== b.already_labeled) return a.already_labeled ? 1 : -1;
    return (b.ollama_confidence || 0) - (a.ollama_confidence || 0);
  });
  if (!list.length) {
    container.innerHTML = `<div style="text-align:center;padding:50px;color:var(--muted)">
      No Ollama triage suggestions found${currentTriageFilter !== 'ALL' ? " for bucket '" + currentTriageFilter + "'" : ''}.<br>
      <span style="font-size:0.85rem;margin-top:8px;display:block">
        Run <code style="background:var(--panel);padding:2px 6px;border-radius:4px">python scripts/run_daily.py</code> to generate fresh suggestions.
      </span></div>`;
    return;
  }
  container.innerHTML = list.map(j => renderCard(j, 'triage')).join('');
}

function renderRejected() {
  const container = document.getElementById('jobsList');
  let list = currentRejectedFilter === 'ALL' ? allRejectedJobs : allRejectedJobs.filter(j => j.hf_reason === currentRejectedFilter);
  if (!list.length) {
    container.innerHTML = `<div style="text-align:center;padding:50px;color:var(--muted)">No rejected jobs matching filter '${currentRejectedFilter}'.</div>`;
    return;
  }
  container.innerHTML = list.map(j => renderCard(j, 'rejected')).join('');
}

function renderCard(j, viewMode) {
  const boostTags = (j.boosts || []).map(w => `<span class="word-tag tag-boost">+${w}</span>`).join('');
  const penaltyTags = (j.penalties || []).map(w => `<span class="word-tag tag-penalty">-${w}</span>`).join('');
  
  const hfClass = j.hf_passed ? (j.hf_reason === 'NEEDS_REVIEW' ? 'review' : 'pass') : 'fail';
  const hfText = j.hf_reason || (j.hf_passed ? 'PASS' : 'FAIL');
  const msVal = j.match_score != null ? Number(j.match_score).toFixed(0) : '—';
  const layaVal = j.laya_score != null ? (Number(j.laya_score) * 100).toFixed(0) + '%' : '—';
  
  // Column 3: Ollama Triage Content
  let col3Html = '';
  let quickAcceptBtn = '';
  
  if (viewMode === 'rejected') {
    col3Html = `
      <div class="col-label-tag">FILTER TRIGGER</div>
      <div><span class="chip-hf fail">${hfText}</span></div>
      ${j.hf_detail ? `<span class="failure-snippet">${escapeHtml(j.hf_detail)}</span>` : '<span style="color:var(--muted);font-size:0.75rem">No detail recorded</span>'}
    `;
  } else {
    // Feed or Triage view: show Ollama column
    const t = j.triage || (viewMode === 'triage' ? {
      ollama_label: j.ollama_label,
      ollama_confidence: j.ollama_confidence,
      ollama_reason: j.ollama_reason,
      bucket: j.bucket,
    } : null);

    if (t && t.ollama_label) {
      const oClass = t.ollama_label === 'good_fit' ? 'ollama-good' : (t.ollama_label === 'maybe' ? 'ollama-maybe' : 'ollama-bad');
      const oText = t.ollama_label === 'good_fit' ? 'Good Fit' : (t.ollama_label === 'maybe' ? 'Maybe' : 'Bad Fit');
      const conf = Math.round((t.ollama_confidence || 0) * 100);
      const confColor = conf >= 80 ? 'var(--green)' : (conf >= 60 ? 'var(--amber)' : 'var(--red)');
      
      col3Html = `
        <div class="col-label-tag">OLLAMA VERDICT</div>
        <div class="triage-header-line">
          <span class="ollama-pill ${oClass}">${oText}</span>
          ${t.bucket ? `<span class="bucket-pill">${escapeHtml(t.bucket)}</span>` : ''}
        </div>
        <div class="conf-bar-wrap">
          <span class="conf-label">${conf}% conf</span>
          <div class="conf-bar-bg"><div class="conf-bar-fill" style="width:${conf}%;background:${confColor}"></div></div>
        </div>
        <div class="ollama-quote" title="${escapeHtml(t.ollama_reason || '')}">
          &ldquo;${escapeHtml(t.ollama_reason || 'No reasoning provided')}&rdquo;
        </div>
      `;

      quickAcceptBtn = `
        <button class="accept-btn" onclick="acceptOllama('${j.id || j.job_id}', '${t.ollama_label}')" title="Accept Ollama suggestion">
          ✓ Accept Ollama (${oText})
        </button>
      `;
    } else {
      col3Html = `
        <div class="col-label-tag">OLLAMA TRIAGE</div>
        <div class="triage-empty">
          <span style="font-weight:600;color:var(--muted)">⚪ Not Yet Triaged</span>
          <span style="font-size:0.72rem;color:#64748b">Evaluated during scheduled run if interesting</span>
        </div>
      `;
    }
  }

  const jid = j.id || j.job_id;
  const isAlready = j.already_labeled;

  return `
    <div class="job-card${isAlready ? ' labeled' : ''}" id="card-${jid}">
      <!-- Col 1: Job Details -->
      <div class="col-job">
        <div class="col-label-tag">JOB & COMPANY</div>
        <a class="job-title" href="${escapeHtml(j.apply_url || '#')}" target="_blank" rel="noopener">${escapeHtml(j.title)}</a>
        <div class="job-company">🏢 <strong>${escapeHtml(j.company)}</strong></div>
        <div class="job-location">📍 ${escapeHtml(j.location || 'Remote')} &bull; 🌐 ${escapeHtml(j.source || '')}</div>
        <div class="tags-row">${boostTags || '<span class="muted-tag">No boosts</span>'} ${penaltyTags}</div>
      </div>

      <!-- Col 2: Scores & Filters -->
      <div class="col-scores">
        <div class="col-label-tag">SCORES & FILTERS</div>
        <div class="score-row">
          <span style="color:var(--muted)">MatchScorer:</span>
          <span class="score-val ms">${msVal} pts</span>
        </div>
        <div class="score-row">
          <span style="color:var(--muted)">Laya Neural:</span>
          <span class="score-val laya">${layaVal}</span>
        </div>
        <div class="score-row">
          <span style="color:var(--muted)">Title Rule:</span>
          <span class="score-val">${j.title_score > 0 ? '+' : ''}${j.title_score || 0}</span>
        </div>
        <div class="score-row">
          <span style="color:var(--muted)">HardFilter:</span>
          <span class="chip-hf ${hfClass}" title="${escapeHtml(j.hf_detail || '')}">${hfText}</span>
        </div>
      </div>

      <!-- Col 3: Ollama Triage Column (DISTINCT COLUMN) -->
      <div class="col-triage">
        ${col3Html}
      </div>

      <!-- Col 4: Human Action & Label -->
      <div class="col-action">
        <div class="col-label-tag">HUMAN REVIEW (v2)</div>
        ${quickAcceptBtn}
        <div class="btn-group">
          <button class="btn-label btn-good" onclick="submitLabel('${jid}', 'good_fit')">Good Fit</button>
          <button class="btn-label btn-maybe" onclick="submitLabel('${jid}', 'maybe')">Maybe</button>
          <button class="btn-label btn-bad" onclick="submitLabel('${jid}', 'bad_fit')">Bad Fit</button>
        </div>
        <input type="text" class="reason-input" id="note-${jid}" placeholder="Note (optional)...">
        <label class="wrong-toggle">
          <input type="checkbox" id="wrong-${jid}"> Wrongly filtered
        </label>
        <div class="labeled-banner" id="banner-${jid}">✓ Saved!</div>
      </div>
    </div>
  `;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function acceptOllama(jobId, label) {
  const noteInput = document.getElementById(`note-${jobId}`);
  if (noteInput && !noteInput.value.trim()) noteInput.value = 'Accepted Ollama suggestion';
  await submitLabel(jobId, label, true);
}

async function submitLabel(jobId, label, isOllamaAccept) {
  const noteInput = document.getElementById(`note-${jobId}`);
  const wrongInput = document.getElementById(`wrong-${jobId}`);
  const notes = noteInput ? noteInput.value.trim() : '';
  const wronglyFiltered = wrongInput ? wrongInput.checked : false;
  
  try {
    const res = await fetch('/api/label', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        job_id: jobId,
        label: label,
        notes: notes,
        wrongly_filtered: wronglyFiltered,
        source: isOllamaAccept ? 'triage_accept' : 'app',
      })
    });
    
    if (res.ok) {
      const card = document.getElementById(`card-${jobId}`);
      if (card) {
        card.classList.add('labeled');
        const banner = document.getElementById(`banner-${jobId}`);
        if (banner) banner.style.display = 'block';
        setTimeout(() => { card.style.display = 'none'; }, 350);
      }
      fetchStats();
      if (currentTab === 'triage') {
        const item = allTriageJobs.find(j => (j.job_id || j.id) === jobId);
        if (item) { item.already_labeled = true; item.existing_label = label; }
        const pending = allTriageJobs.filter(j => !j.already_labeled).length;
        document.getElementById('triageCount').textContent = pending;
      }
    } else {
      alert('Error saving label. Please check console.');
    }
  } catch (err) {
    console.error('Error submitting label:', err);
    alert('Failed to connect to backend.');
  }
}

fetchStats();
loadFeed();
loadTriage();
loadRejected();
</script>

</body>
</html>
"""


class AppServerHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for feedback loop labeling dashboard."""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
            return

        elif path == "/api/stats":
            self._handle_get_stats()
            return

        elif path == "/api/feed":
            self._handle_get_feed()
            return

        elif path == "/api/triage":
            self._handle_get_triage()
            return

        elif path == "/api/rejected":
            self._handle_get_rejected()
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path

        if path == "/api/label":
            self._handle_post_label()
            return

        self.send_error(404, "Not Found")

    def _handle_get_stats(self):
        """Header stats: last run time, new jobs, model version, v2 gate progress."""
        try:
            run_rows = execute_query("""
                SELECT started_at, inserted
                FROM source_runs
                ORDER BY started_at DESC
                LIMIT 1;
            """)
            last_run_time = run_rows[0]["started_at"] if run_rows else None

            new_jobs_rows = execute_query("""
                SELECT COALESCE(SUM(inserted), 0) AS total_inserted
                FROM source_runs
                WHERE started_at >= NOW() - INTERVAL '24 hours';
            """)
            new_jobs_24h = int(new_jobs_rows[0]["total_inserted"]) if new_jobs_rows else 0

            v2_rows = execute_query("""
                SELECT
                    COUNT(DISTINCT l.job_id) AS v2_total,
                    COUNT(DISTINCT CASE WHEN l.label = 'good_fit' THEN l.job_id END) AS v2_good_fit
                FROM laya_labels l
                JOIN jobs j ON l.job_id = j.id
                WHERE l.label_guideline_version = 'v2_role_fit_only'
                  AND j.exclude_reason IS NULL;
            """)
            v2_total = v2_rows[0]["v2_total"] if v2_rows else 0
            v2_good_fit = v2_rows[0]["v2_good_fit"] if v2_rows else 0

            is_stale = False
            last_run_display = "Never"
            if last_run_time:
                now_utc = datetime.now(timezone.utc)
                diff_hours = (now_utc - last_run_time).total_seconds() / 3600.0
                is_stale = diff_hours > 36.0
                last_run_display = last_run_time.strftime("%Y-%m-%d %H:%M UTC")

            payload = {
                "last_run_display": last_run_display,
                "new_jobs_24h": new_jobs_24h,
                "is_stale": is_stale,
                "model_version": "Title-Rule Ranker v1 (Head v2 experimental)",
                "v2_total": v2_total,
                "v2_good_fit": v2_good_fit,
            }
            self._send_json(payload)
        except Exception as e:
            logger.error("Error in get_stats: %s", e)
            self._send_json({"error": str(e)}, status=500)

    def _handle_get_feed(self):
        """Top unlabeled jobs that pass HardFilter with scores and Ollama triage verdict."""
        try:
            triage_map = load_all_triage_suggestions()
            rows = execute_query("""
                SELECT
                    j.id, j.title, j.company_name, j.location_raw, j.source, j.apply_url,
                    j.created_at, j.description_text, j.remote_restriction, j.is_remote,
                    j.experience_level, j.detected_language, j.is_unpaid, j.nepal_accessible,
                    j.tags, j.accessibility, j.reachable_from_nepal, j.reachable_reason,
                    COALESCE(m.match_score, 0.0) AS match_score,
                    laya.final_score AS laya_score
                FROM jobs j
                LEFT JOIN job_matches m ON j.id = m.job_id
                LEFT JOIN laya_labels l ON j.id = l.job_id
                LEFT JOIN LATERAL (
                    SELECT final_score FROM laya_job_scores
                    WHERE job_id = j.id
                    ORDER BY scored_at DESC
                    LIMIT 1
                ) laya ON true
                WHERE l.id IS NULL
                  AND j.canonical_job_id IS NULL
                  AND j.exclude_reason IS NULL
                ORDER BY j.created_at DESC
                LIMIT 1500;
            """)

            feed_items = []
            for r in rows:
                hf_res = apply_hard_filter(r)
                if not hf_res.passed:
                    continue

                title = r.get("title") or ""
                t_score = score_title_rule(title)
                boosts = [w for w in BOOST_WORDS if re.search(r"\b" + re.escape(w) + r"\b", title, re.IGNORECASE)]
                penalties = [w for w in PENALTY_WORDS if re.search(r"\b" + re.escape(w) + r"\b", title, re.IGNORECASE)]
                tech_prob = predict_tech_probability(title)
                role_penalty = get_title_role_penalty(title)

                jid_str = str(r["id"])
                tinfo = triage_map.get(jid_str)
                triage_payload = None
                if tinfo:
                    triage_payload = {
                        "ollama_label": tinfo.get("ollama_label") or tinfo.get("label"),
                        "ollama_confidence": tinfo.get("ollama_confidence") or tinfo.get("confidence"),
                        "ollama_reason": tinfo.get("ollama_reason") or tinfo.get("reason"),
                        "bucket": tinfo.get("triage_bucket") or tinfo.get("bucket"),
                    }

                feed_items.append({
                    "id": jid_str,
                    "title": title,
                    "company": r.get("company_name") or "Unknown",
                    "location": r.get("location_raw") or "Remote",
                    "source": r.get("source") or "",
                    "apply_url": r.get("apply_url") or "",
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                    "match_score": float(r["match_score"]),
                    "laya_score": float(r["laya_score"]) if r.get("laya_score") is not None else None,
                    "title_score": t_score,
                    "boosts": boosts,
                    "penalties": penalties,
                    "tech_prob": tech_prob,
                    "role_penalty": role_penalty,
                    "hf_passed": True,
                    "hf_reason": hf_res.reason.value,
                    "hf_detail": hf_res.detail,
                    "triage": triage_payload,
                })

            feed_items.sort(key=lambda x: x["title_score"], reverse=True)
            self._send_json(feed_items)
        except Exception as e:
            logger.error("Error in get_feed: %s", e)
            self._send_json({"error": str(e)}, status=500)

    def _handle_get_triage(self):
        """Load all merged triage suggestions and annotate each job with DB label status."""
        try:
            triage_map = load_all_triage_suggestions()
            if not triage_map:
                self._send_json({"suggestions": [], "total": 0, "pending": 0})
                return

            job_ids = list(triage_map.keys())
            existing = {}
            if job_ids:
                placeholders = ",".join(["%s"] * len(job_ids))
                rows = execute_query(
                    f"""
                    SELECT DISTINCT ON (job_id) job_id, label
                    FROM laya_labels
                    WHERE job_id IN ({placeholders})
                      AND label_guideline_version = 'v2_role_fit_only'
                    ORDER BY job_id, labeled_at DESC;
                    """,
                    tuple(job_ids),
                )
                for r in rows:
                    existing[str(r["job_id"])] = r["label"]

            out = []
            for jid, s in triage_map.items():
                already = jid in existing
                ms_val = s.get("ms_score") if s.get("ms_score") is not None else s.get("match_score")
                laya_val = s.get("laya_score")
                out.append({
                    "job_id": jid,
                    "id": jid,
                    "title": s.get("title", ""),
                    "company": s.get("company", ""),
                    "source": s.get("source", ""),
                    "apply_url": s.get("apply_url", ""),
                    "posted_date": s.get("posted_date", ""),
                    "match_score": float(ms_val) if ms_val is not None else None,
                    "laya_score": float(laya_val) if laya_val is not None and laya_val >= 0 else None,
                    "ms_laya_delta": s.get("ms_laya_delta"),
                    "bucket": s.get("triage_bucket") or s.get("bucket", "UNKNOWN"),
                    "ollama_label": s.get("ollama_label") or s.get("label", ""),
                    "ollama_confidence": s.get("ollama_confidence") or s.get("confidence"),
                    "ollama_reason": s.get("ollama_reason") or s.get("reason", ""),
                    "already_labeled": already,
                    "existing_label": existing.get(jid),
                    "hf_passed": True,
                    "hf_reason": "PASS",
                })

            self._send_json({
                "suggestions": out,
                "total": len(out),
                "pending": sum(1 for x in out if not x["already_labeled"]),
            })
        except Exception as e:
            logger.error("Error in get_triage: %s", e)
            self._send_json({"error": str(e)}, status=500)

    def _handle_get_rejected(self):
        """Unlabeled jobs that failed HardFilter, with trigger reasons and snippets."""
        try:
            rows = execute_query("""
                SELECT
                    j.id, j.title, j.company_name, j.location_raw, j.source, j.apply_url,
                    j.created_at, j.description_text, j.remote_restriction, j.is_remote,
                    j.experience_level, j.detected_language, j.is_unpaid, j.nepal_accessible,
                    j.tags, j.accessibility, j.reachable_from_nepal, j.reachable_reason,
                    COALESCE(m.match_score, 0.0) AS match_score
                FROM jobs j
                LEFT JOIN job_matches m ON j.id = m.job_id
                LEFT JOIN laya_labels l ON j.id = l.job_id
                WHERE l.id IS NULL
                  AND j.canonical_job_id IS NULL
                  AND j.exclude_reason IS NULL
                ORDER BY j.created_at DESC
                LIMIT 2000;
            """)

            rejected_items = []
            for r in rows:
                hf_res = apply_hard_filter(r)
                if hf_res.passed:
                    continue

                title = r.get("title") or ""
                t_score = score_title_rule(title)
                boosts = [w for w in BOOST_WORDS if re.search(r"\b" + re.escape(w) + r"\b", title, re.IGNORECASE)]
                penalties = [w for w in PENALTY_WORDS if re.search(r"\b" + re.escape(w) + r"\b", title, re.IGNORECASE)]
                tech_prob = predict_tech_probability(title)
                role_penalty = get_title_role_penalty(title)

                rejected_items.append({
                    "id": str(r["id"]),
                    "title": title,
                    "company": r.get("company_name") or "Unknown",
                    "location": r.get("location_raw") or "",
                    "source": r.get("source") or "",
                    "apply_url": r.get("apply_url") or "",
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                    "match_score": float(r["match_score"]),
                    "title_score": t_score,
                    "boosts": boosts,
                    "penalties": penalties,
                    "tech_prob": tech_prob,
                    "role_penalty": role_penalty,
                    "hf_passed": False,
                    "hf_reason": hf_res.reason.value,
                    "hf_detail": hf_res.detail,
                })

            self._send_json(rejected_items)
        except Exception as e:
            logger.error("Error in get_rejected: %s", e)
            self._send_json({"error": str(e)}, status=500)

    def _handle_post_label(self):
        """Immediately writes to laya_labels with label_guideline_version='v2_role_fit_only'."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body.decode("utf-8"))

            job_id_str = data.get("job_id")
            label = data.get("label")
            notes = (data.get("notes") or "").strip()
            wrongly_filtered = bool(data.get("wrongly_filtered", False))
            label_source = (data.get("source") or "app").strip()[:32]

            if not job_id_str or label not in ("good_fit", "maybe", "bad_fit"):
                self._send_json({"error": "Invalid job_id or label"}, status=400)
                return

            job_uuid = uuid.UUID(job_id_str)
            metadata = {
                "wrongly_filtered": wrongly_filtered,
                "source": label_source,
            }

            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO laya_labels (
                            job_id, label, notes, metadata, sampling_stratum,
                            label_guideline_version, labeled_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, NOW()
                        );
                        """,
                        (
                            str(job_uuid),
                            label,
                            notes,
                            json.dumps(metadata),
                            "app_feedback",
                            "v2_role_fit_only",
                        ),
                    )
                conn.commit()

            logger.info("Saved label via app: %s -> %s (wrongly_filtered=%s, source=%s)", job_id_str, label, wrongly_filtered, label_source)
            self._send_json({"success": True, "job_id": job_id_str, "label": label})
        except Exception as e:
            logger.error("Error in post_label: %s", e)
            self._send_json({"error": str(e)}, status=500)

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Start the Job Radar labeling feedback loop web app.")
    parser.add_argument("--port", type=int, default=5000, help="Port to serve on (default: 5000)")
    parser.add_argument("--no-docker-start", action="store_true", help="Skip automatic Docker/PostgreSQL startup.")
    args = parser.parse_args()

    if not args.no_docker_start:
        from src.db.docker_control import ensure_docker_and_postgres
        ensure_docker_and_postgres()

    port = args.port
    server = HTTPServer(("127.0.0.1", port), AppServerHandler)
    print("=" * 65)
    print(f"  JOB RADAR FEEDBACK LOOP DASHBOARD (app.py)")
    print(f"  Serving on: http://localhost:{port}")
    print("=" * 65)
    print("  Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
