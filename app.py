#!/usr/bin/env python3
"""app.py — Local Web Dashboard & Feedback Loop (Step 5).

Provides:
- Feed Tab: Top jobs ranked by title-rule score and MatchScorer, with breakdown and HardFilter status.
- Rejected Tab: Jobs that failed HardFilter grouped by failure reason with the trigger snippet.
- Interactive Labeling on EVERY job: good_fit, maybe, bad_fit, free-text reason, wrongly_filtered checkbox.
  Writes directly to PostgreSQL laya_labels stamped label_guideline_version="v2_role_fit_only".
- Header: Last daily run time, new jobs count, active model version, 150/30 training gate progress,
  and stale run warning (> 36 hours).
"""
import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import urllib.parse
import uuid
from typing import Any
from http.server import HTTPServer, BaseHTTPRequestHandler
import re


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection, execute_query
from src.matching.hard_filter import apply as apply_hard_filter, FilterReason
from src.matching.title_classifier import predict_tech_probability, get_title_role_penalty
from scripts.make_labeling_batch import score_title_rule, BOOST_WORDS, PENALTY_WORDS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

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
  
  /* MAIN CONTENT */
  main{flex:1;max-width:1400px;margin:0 auto;width:100%;padding:20px 28px;display:flex;flex-direction:column;gap:16px}
  
  .filter-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--panel);padding:12px 16px;border-radius:var(--radius);border:1px solid var(--border)}
  .filter-bar span{font-size:0.8rem;color:var(--muted);text-transform:uppercase;font-weight:700}
  .pill-filter{background:var(--card-bg);border:1px solid var(--border);color:var(--muted);padding:4px 12px;border-radius:16px;font-size:0.8rem;cursor:pointer}
  .pill-filter:hover{color:var(--text);border-color:var(--accent)}
  .pill-filter.active{background:var(--accent);color:#090d16;border-color:var(--accent);font-weight:700}
  
  /* JOB CARDS */
  .jobs-list{display:flex;flex-direction:column;gap:14px}
  .job-card{background:var(--card-bg);border:1px solid var(--border);border-radius:var(--radius);padding:18px 22px;display:flex;flex-direction:column;gap:12px;transition:border-color 0.15s, opacity 0.3s ease}
  .job-card:hover{border-color:#3b82f6}
  .job-card.labeled{opacity:0.25;pointer-events:none}
  
  .card-header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
  .job-title{font-size:1.15rem;font-weight:700;color:var(--text);text-decoration:none}
  .job-title:hover{color:var(--accent);text-decoration:underline}
  .job-meta{display:flex;gap:12px;font-size:0.85rem;color:var(--muted);margin-top:4px;flex-wrap:wrap}
  .job-meta strong{color:#cbd5e1}
  
  .scores-badge{display:flex;gap:8px;align-items:center;flex-shrink:0}
  .score-chip{padding:4px 10px;border-radius:6px;font-size:0.85rem;font-weight:700}
  .chip-rule{background:rgba(56,189,248,0.15);color:var(--accent);border:1px solid rgba(56,189,248,0.3)}
  .chip-hf{padding:4px 8px;border-radius:6px;font-size:0.75rem;font-weight:700;text-transform:uppercase}
  .chip-hf.pass{background:var(--green-dim);color:var(--green);border:1px solid var(--green)}
  .chip-hf.review{background:var(--amber-dim);color:var(--amber);border:1px solid var(--amber)}
  .chip-hf.fail{background:var(--red-dim);color:var(--red);border:1px solid var(--red)}
  
  /* DETAILS & BREAKDOWN */
  .breakdown-box{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px 14px;font-size:0.82rem;display:flex;flex-direction:column;gap:6px}
  .breakdown-row{display:flex;justify-content:space-between;align-items:center}
  .word-tag{display:inline-block;padding:2px 6px;border-radius:4px;font-size:0.75rem;font-weight:600;margin-right:4px}
  .tag-boost{background:rgba(34,197,94,0.15);color:var(--green);border:1px solid rgba(34,197,94,0.3)}
  .tag-penalty{background:rgba(239,68,68,0.15);color:var(--red);border:1px solid rgba(239,68,68,0.3)}
  .failure-snippet{color:#f87171;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;background:rgba(239,68,68,0.1);padding:4px 8px;border-radius:4px;margin-top:4px;display:block}
  
  /* LABELING ACTIONS */
  .labeling-bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-top:1px solid var(--border);padding-top:12px;margin-top:4px}
  .reason-input{flex:1;min-width:240px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:6px;font-size:0.85rem;outline:none}
  .reason-input:focus{border-color:var(--accent)}
  
  .wrong-toggle{display:flex;align-items:center;gap:6px;font-size:0.82rem;color:var(--muted);cursor:pointer;user-select:none}
  .wrong-toggle input{accent-color:var(--amber);cursor:pointer;width:15px;height:15px}
  
  .btn-group{display:flex;gap:6px}
  .btn-label{border:none;padding:8px 16px;border-radius:6px;font-size:0.85rem;font-weight:700;cursor:pointer;transition:transform 0.08s ease, filter 0.15s ease}
  .btn-label:hover{filter:brightness(1.15);transform:translateY(-1px)}
  .btn-label:active{transform:translateY(1px)}
  .btn-good{background:var(--green);color:#090d16}
  .btn-maybe{background:var(--amber);color:#090d16}
  .btn-bad{background:var(--red);color:#ffffff}
  
  .labeled-banner{display:none;background:var(--green-dim);border:1px solid var(--green);color:var(--green);padding:6px 12px;border-radius:6px;font-size:0.85rem;font-weight:600}
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

  <div id="jobsList" class="jobs-list">
    <div style="text-align:center;color:var(--muted);padding:40px;">Loading jobs...</div>
  </div>
</main>

<script>
let currentTab = 'feed';
let allFeedJobs = [];
let allRejectedJobs = [];
let currentRejectedFilter = 'ALL';
let currentFeedSort = 'rule';

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
  } catch (err) {
    console.error('Failed to fetch stats:', err);
  }
}

async function loadFeed() {
  try {
    const res = await fetch('/api/feed');
    allFeedJobs = await res.json();
    document.getElementById('feedCount').textContent = allFeedJobs.length;
    if (currentTab === 'feed') renderFeed();
  } catch (err) {
    console.error('Failed to load feed:', err);
  }
}

async function loadRejected() {
  try {
    const res = await fetch('/api/rejected');
    allRejectedJobs = await res.json();
    document.getElementById('rejectedCount').textContent = allRejectedJobs.length;
    if (currentTab === 'rejected') renderRejected();
  } catch (err) {
    console.error('Failed to load rejected jobs:', err);
  }
}

function switchTab(tab) {
  currentTab = tab;
  document.getElementById('tabFeedBtn').classList.toggle('active', tab === 'feed');
  document.getElementById('tabRejectedBtn').classList.toggle('active', tab === 'rejected');
  document.getElementById('feedControls').style.display = tab === 'feed' ? 'flex' : 'none';
  document.getElementById('rejectedControls').style.display = tab === 'rejected' ? 'flex' : 'none';
  
  if (tab === 'feed') renderFeed();
  else renderRejected();
}

function setFeedSort(mode, btn) {
  currentFeedSort = mode;
  document.querySelectorAll('#feedControls .pill-filter').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderFeed();
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
  if (currentFeedSort === 'rule') {
    list.sort((a,b) => b.title_score - a.title_score);
  } else if (currentFeedSort === 'match') {
    list.sort((a,b) => b.match_score - a.match_score);
  } else if (currentFeedSort === 'date') {
    list.sort((a,b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
  }
  
  if (!list.length) {
    container.innerHTML = `<div style="text-align:center;padding:50px;color:var(--muted)">No passing jobs to display. All current accessible jobs are labeled!</div>`;
    return;
  }
  
  container.innerHTML = list.map(j => renderCard(j, false)).join('');
}

function renderRejected() {
  const container = document.getElementById('jobsList');
  let list = allRejectedJobs;
  if (currentRejectedFilter !== 'ALL') {
    list = list.filter(j => j.hf_reason === currentRejectedFilter);
  }
  
  if (!list.length) {
    container.innerHTML = `<div style="text-align:center;padding:50px;color:var(--muted)">No rejected jobs matching filter '${currentRejectedFilter}'.</div>`;
    return;
  }
  
  container.innerHTML = list.map(j => renderCard(j, true)).join('');
}

function renderCard(j, isRejected) {
  const boostTags = (j.boosts || []).map(w => `<span class="word-tag tag-boost">+${w}</span>`).join('');
  const penaltyTags = (j.penalties || []).map(w => `<span class="word-tag tag-penalty">-${w}</span>`).join('');
  
  const hfClass = j.hf_passed ? (j.hf_reason === 'NEEDS_REVIEW' ? 'review' : 'pass') : 'fail';
  const hfText = j.hf_reason || (j.hf_passed ? 'PASS' : 'FAIL');
  
  return `
    <div class="job-card" id="card-${j.id}">
      <div class="card-header">
        <div>
          <a class="job-title" href="${j.apply_url || '#'}" target="_blank" rel="noopener">${escapeHtml(j.title)}</a>
          <div class="job-meta">
            <span>🏢 <strong>${escapeHtml(j.company)}</strong></span>
            <span>📍 ${escapeHtml(j.location || 'Remote')}</span>
            <span>🌐 Source: <strong>${escapeHtml(j.source)}</strong></span>
          </div>
        </div>
        <div class="scores-badge">
          <span class="score-chip chip-rule" title="Title Rule Score">Score: ${j.title_score > 0 ? '+' : ''}${j.title_score}</span>
          <span class="chip-hf ${hfClass}" title="${escapeHtml(j.hf_detail || '')}">${hfText}</span>
        </div>
      </div>
      
      <div class="breakdown-box">
        <div class="breakdown-row">
          <span>Keywords Breakdown:</span>
          <div>${boostTags || '<span style="color:var(--muted);font-size:0.75rem">No boost words</span>'} ${penaltyTags}</div>
        </div>
        <div class="breakdown-row">
          <span>MatchScorer: <strong>${j.match_score} pts</strong> | Tech Probability: <strong>${(j.tech_prob * 100).toFixed(0)}%</strong></span>
          <span>Role Soft Penalty: <strong>${j.role_penalty > 0 ? '-' + j.role_penalty + ' pts' : '0 pts'}</strong></span>
        </div>
        ${j.hf_detail ? `<span class="failure-snippet">Filter trigger: ${escapeHtml(j.hf_detail)}</span>` : ''}
      </div>
      
      <div class="labeling-bar">
        <input type="text" class="reason-input" id="note-${j.id}" placeholder="Reason for your judgment (optional, e.g. 'Too senior', 'Great junior stack')...">
        <label class="wrong-toggle" title="Flag if HardFilter incorrectly rejected this role">
          <input type="checkbox" id="wrong-${j.id}"> Wrongly filtered
        </label>
        <div class="btn-group">
          <button class="btn-label btn-good" onclick="submitLabel('${j.id}', 'good_fit')">Good Fit</button>
          <button class="btn-label btn-maybe" onclick="submitLabel('${j.id}', 'maybe')">Maybe</button>
          <button class="btn-label btn-bad" onclick="submitLabel('${j.id}', 'bad_fit')">Bad Fit</button>
        </div>
        <div class="labeled-banner" id="banner-${j.id}">✓ Saved!</div>
      </div>
    </div>
  `;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function submitLabel(jobId, label) {
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
      })
    });
    
    if (res.ok) {
      const card = document.getElementById(`card-${jobId}`);
      if (card) {
        card.classList.add('labeled');
        const banner = document.getElementById(`banner-${jobId}`);
        if (banner) banner.style.display = 'inline-block';
        setTimeout(() => {
          card.style.display = 'none';
        }, 350);
      }
      // Refresh stats
      fetchStats();
    } else {
      alert('Error saving label. Please check console.');
    }
  } catch (err) {
    console.error('Error submitting label:', err);
    alert('Failed to connect to backend.');
  }
}

// Initial load
fetchStats();
loadFeed();
loadRejected();
</script>

</body>
</html>
"""


class AppServerHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler for feedback loop labeling dashboard."""

    def log_message(self, format, *args):
        # Keep server output quiet for API calls
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
            # Last run
            run_rows = execute_query("""
                SELECT started_at, inserted
                FROM source_runs
                ORDER BY started_at DESC
                LIMIT 1;
            """)
            last_run_time = run_rows[0]["started_at"] if run_rows else None

            # New jobs inserted in the last 24h
            new_jobs_rows = execute_query("""
                SELECT COALESCE(SUM(inserted), 0) AS total_inserted
                FROM source_runs
                WHERE started_at >= NOW() - INTERVAL '24 hours';
            """)
            new_jobs_24h = int(new_jobs_rows[0]["total_inserted"]) if new_jobs_rows else 0

            # Training gate counts
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

            # Check if run is stale (> 36 hours old)
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
        """Top unlabeled jobs that pass HardFilter (PASS or NEEDS_REVIEW)."""
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

                feed_items.append({
                    "id": str(r["id"]),
                    "title": title,
                    "company": r.get("company_name") or "Unknown",
                    "location": r.get("location_raw") or "Remote",
                    "source": r.get("source") or "",
                    "apply_url": r.get("apply_url") or "",
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                    "match_score": float(r["match_score"]),
                    "title_score": t_score,
                    "boosts": boosts,
                    "penalties": penalties,
                    "tech_prob": tech_prob,
                    "role_penalty": role_penalty,
                    "hf_passed": True,
                    "hf_reason": hf_res.reason.value,
                    "hf_detail": hf_res.detail,
                })

            feed_items.sort(key=lambda x: x["title_score"], reverse=True)
            self._send_json(feed_items)
        except Exception as e:
            logger.error("Error in get_feed: %s", e)
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

            if not job_id_str or label not in ("good_fit", "maybe", "bad_fit"):
                self._send_json({"error": "Invalid job_id or label"}, status=400)
                return

            job_uuid = uuid.UUID(job_id_str)
            metadata = {
                "wrongly_filtered": wrongly_filtered,
                "source": "app",
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

            logger.info("Saved label via app: %s -> %s (wrongly_filtered=%s)", job_id_str, label, wrongly_filtered)
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
    args = parser.parse_args()

    port = args.port
    server = HTTPServer(("", port), AppServerHandler)
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
