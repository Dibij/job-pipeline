#!/usr/bin/env python3
"""
app.py — Local Web Dashboard for Remote Job Listings

USAGE:
    python app.py

SERVES:
    http://localhost:5000

FEATURES:
    - Reads directly from D:\\Code\\Job\\tools\\jobs.json
    - Interactive visual UI with search, salary, region, and tech tag filters
    - Dedicated "Nepal / Global Remote Only" toggle
    - Zero external dependencies required (uses standard library http.server)
"""

import os
import sys
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

TOOLS_DIR = Path(__file__).parent.resolve()
JOBS_JSON = TOOLS_DIR / "jobs.json"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remote Job Finder — Kshitish Pandit</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --accent-color: #38bdf8;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --border-color: #334155;
            --success-color: #4ade80;
            --badge-bg: #0284c7;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 0;
        }

        header {
            background-color: var(--card-bg);
            border-bottom: 1px solid var(--border-color);
            padding: 20px 40px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        header h1 {
            margin: 0;
            font-size: 1.5rem;
            color: var(--accent-color);
        }

        .container {
            max-width: 1200px;
            margin: 30px auto;
            padding: 0 20px;
        }

        .controls {
            background: var(--card-bg);
            padding: 20px;
            border-radius: 12px;
            border: 1px solid var(--border-color);
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            align-items: center;
            margin-bottom: 25px;
        }

        .input-group {
            display: flex;
            flex-direction: column;
            gap: 5px;
            flex: 1;
            min-width: 200px;
        }

        .input-group label {
            font-size: 0.85rem;
            color: var(--text-muted);
            font-weight: 600;
        }

        input[type="text"], input[type="number"], select {
            background: var(--bg-color);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 10px 12px;
            border-radius: 6px;
            font-size: 0.95rem;
            outline: none;
        }

        input[type="text"]:focus, select:focus {
            border-color: var(--accent-color);
        }

        .toggle-group {
            display: flex;
            align-items: center;
            gap: 10px;
            background: var(--bg-color);
            padding: 10px 16px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            cursor: pointer;
        }

        .toggle-group input {
            cursor: pointer;
            width: 18px;
            height: 18px;
        }

        .stats-bar {
            margin-bottom: 20px;
            color: var(--text-muted);
            font-size: 0.95rem;
            display: flex;
            justify-content: space-between;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: transform 0.2s ease, border-color 0.2s ease;
        }

        .card:hover {
            transform: translateY(-3px);
            border-color: var(--accent-color);
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 12px;
        }

        .company-name {
            font-size: 0.9rem;
            color: var(--text-muted);
            font-weight: 600;
        }

        .job-title {
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--text-main);
            margin: 4px 0 10px 0;
        }

        .badges {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-bottom: 12px;
        }

        .badge {
            background: rgba(56, 189, 248, 0.15);
            color: var(--accent-color);
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
        }

        .badge-loc {
            background: rgba(74, 222, 128, 0.15);
            color: var(--success-color);
        }

        .badge-source {
            background: rgba(148, 163, 184, 0.15);
            color: var(--text-muted);
        }

        .desc-snippet {
            font-size: 0.88rem;
            color: #cbd5e1;
            line-height: 1.5;
            margin-bottom: 16px;
            display: -webkit-box;
            -webkit-line-clamp: 4;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }

        .card-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-top: 12px;
            border-top: 1px solid var(--border-color);
        }

        .salary-text {
            font-size: 0.85rem;
            color: var(--success-color);
            font-weight: 600;
        }

        .apply-btn {
            background: var(--badge-bg);
            color: white;
            padding: 8px 14px;
            border-radius: 6px;
            text-decoration: none;
            font-size: 0.85rem;
            font-weight: 600;
            transition: background 0.2s ease;
        }

        .apply-btn:hover {
            background: var(--accent-color);
            color: var(--bg-color);
        }
    </style>
</head>
<body>

    <header>
        <h1>🌏 Remote Job Dashboard</h1>
        <span style="font-size:0.9rem; color:var(--text-muted)">User: Kshitish Pandit</span>
    </header>

    <div class="container">
        
        <div class="controls">
            <div class="input-group">
                <label for="searchInput">Search Keyword</label>
                <input type="text" id="searchInput" placeholder="Title, tech, keyword...">
            </div>

            <div class="input-group">
                <label for="tagSelect">Tech Stack Tag</label>
                <select id="tagSelect">
                    <option value="">All Tech Stacks</option>
                    <option value="react">React</option>
                    <option value="python">Python</option>
                    <option value="node">Node.js</option>
                    <option value="typescript">TypeScript</option>
                    <option value="flutter">Flutter / Mobile</option>
                    <option value="rust">Rust</option>
                    <option value="ai">AI / ML / RAG</option>
                </select>
            </div>

            <div class="toggle-group" id="nepalToggleBox">
                <input type="checkbox" id="nepalToggle" checked>
                <label for="nepalToggle" style="cursor:pointer; font-size:0.9rem; font-weight:600">🇳🇵 Nepal / Global Remote Only</label>
            </div>
        </div>

        <div class="stats-bar">
            <span id="showingCount">Showing 0 jobs</span>
            <span id="totalCount">Total in Database: 0</span>
        </div>

        <div class="grid" id="jobsGrid">
            <!-- Cards rendered dynamically -->
        </div>

    </div>

    <script>
        let allJobs = [];

        async function loadJobs() {
            try {
                const res = await fetch('/api/jobs');
                allJobs = await res.json();
                document.getElementById('totalCount').innerText = `Total in Database: ${allJobs.length}`;
                renderJobs();
            } catch (e) {
                console.error("Error loading jobs:", e);
            }
        }

        function isNepalFriendly(loc) {
            if (!loc) return true;
            const l = loc.lower ? loc.lower() : String(loc).toLowerCase();
            const restricted = ["usa only", "us only", "eu only", "uk only", "canada only", "latam only"];
            if (restricted.some(r => l.includes(r))) return false;
            return true;
        }

        function renderJobs() {
            const search = document.getElementById('searchInput').value.toLowerCase();
            const tag = document.getElementById('tagSelect').value.toLowerCase();
            const nepalOnly = document.getElementById('nepalToggle').checked;

            const filtered = allJobs.filter(j => {
                const title = (j.title || '').toLowerCase();
                const company = (j.company || '').toLowerCase();
                const desc = (j.description || '').toLowerCase();
                const loc = (j.location || '').toLowerCase();
                const tags = (j.tags || []).map(t => String(t).toLowerCase());

                if (nepalOnly && !isNepalFriendly(loc)) return false;

                if (tag) {
                    const tagMatch = tags.some(t => t.includes(tag)) || title.includes(tag) || desc.includes(tag);
                    if (!tagMatch) return false;
                }

                if (search) {
                    const searchMatch = title.includes(search) || company.includes(search) || desc.includes(search) || tags.some(t => t.includes(search));
                    if (!searchMatch) return false;
                }

                return true;
            });

            document.getElementById('showingCount').innerText = `Showing ${filtered.length} matching jobs`;
            const grid = document.getElementById('jobsGrid');
            grid.innerHTML = '';

            filtered.forEach(j => {
                const card = document.createElement('div');
                card.className = 'card';
                
                const tagsHtml = (j.tags || []).slice(0, 4).map(t => `<span class="badge">${t}</span>`).join('');

                card.innerHTML = `
                    <div>
                        <div class="card-header">
                            <span class="company-name">${j.company || 'Unknown Company'}</span>
                            <span class="badge badge-source">${j.source || 'Web'}</span>
                        </div>
                        <h2 class="job-title">${j.title}</h2>
                        <div class="badges">
                            <span class="badge badge-loc">📍 ${j.location || 'Worldwide'}</span>
                            ${tagsHtml}
                        </div>
                        <p class="desc-snippet">${j.description || 'No description preview available.'}</p>
                    </div>
                    <div class="card-footer">
                        <span class="salary-text">${j.salary && j.salary !== 'Not Listed' ? j.salary : 'Salary Unspecified'}</span>
                        <a href="${j.url}" target="_blank" class="apply-btn">View Job ↗</a>
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        document.getElementById('searchInput').addEventListener('input', renderJobs);
        document.getElementById('tagSelect').addEventListener('change', renderJobs);
        document.getElementById('nepalToggle').addEventListener('change', renderJobs);

        loadJobs();
    </script>
</body>
</html>
"""

class JobServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif parsed.path == "/api/jobs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            if JOBS_JSON.exists():
                with open(JOBS_JSON, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b"[]")
        else:
            self.send_response(404)
            self.end_headers()

def main():
    port = 5000
    server_address = ('', port)
    httpd = HTTPServer(server_address, JobServerHandler)
    print("==================================================")
    print(f"  LOCAL REMOTE JOB DASHBOARD IS LIVE AT:")
    print(f"  👉  http://localhost:{port}")
    print("==================================================")
    print("  Press Ctrl+C to stop the server.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server stopped cleanly.")

if __name__ == "__main__":
    main()
