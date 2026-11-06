# Kshitish Pandit
**Software Engineer (Python, Full-Stack & Data Pipelines)**

Kathmandu, Nepal | [dibijsharma@gmail.com](mailto:dibijsharma@gmail.com) | +977-9703995826  
[GitHub: github.com/Dibij](https://github.com/Dibij) | [LinkedIn: linkedin.com/in/kshitish-pandit](https://www.linkedin.com/in/kshitish-pandit)

---

## Professional Summary
Software Engineer specializing in Python backend services, resilient data ingestion pipelines, and full-stack review tools (React / TypeScript / Next.js). Experienced in designing ELT architectures, Pydantic validation, document parsing, PostgreSQL schema management, and LLM-assisted evaluation workflows. Strong track record of shipping maintainable, tested software with practical experience in Linux, Docker, automated evaluation, and developer tooling.

---

## Technical Skills
- **Languages:** Python (3.12+), TypeScript, JavaScript, SQL, Rust
- **Backend & APIs:** FastAPI, Django, Django REST Framework, Flask, Pydantic (v2), Psycopg 3, Requests, Celery, RESTful API design, rate-limiting, error handling
- **Frontend:** React, Next.js (App Router), TypeScript, Tailwind CSS, Vite
- **Databases & Storage:** PostgreSQL, Supabase, SQLite, schema design, migrations, data integrity checks, SHA-256 deduplication, ELT staging
- **AI & Document Pipelines:** LLM API integrations (Ollama, OpenRouter, Transformers), PDF/document parsing, hierarchical text chunking, active-learning triage, prompt engineering, automated evaluation & benchmarking
- **Tools & Infrastructure:** Linux/Bash, Docker, Docker Compose, Git, GitHub Actions, systemd, pytest, AST parsing (Babel)

---

## Featured Engineering Projects

### **Modular Data Ingestion & Evaluation Pipeline**
*Python (3.12+), PostgreSQL, Pydantic v2, Ollama (LLM), Psycopg 3, Flask, Docker*
- **Pluggable Ingestion Architecture:** Designed an automated ELT pipeline ingesting semi-structured data across 15+ external JSON APIs, RSS feeds, and direct ATS endpoints with isolated per-source failure boundaries and polite rate-limiting.
- **Data Validation & Deduplication:** Preserved raw payloads in PostgreSQL staging tables to guarantee zero data loss; enforced strict Pydantic v2 validation models and SHA-256 hashing to eliminate cross-platform duplicates.
- **Automated Filtering & Scoring:** Built a multi-gate rule filter combined with a TF-IDF title classifier and modern transformer scoring models for automated eligibility assessment and regression tracking.
- **Active-Learning LLM Triage:** Implemented an active-learning triage system leveraging local Ollama LLMs (`qwen2.5`) to classify uncertain records, with interactive human-in-the-loop review before persisting labels.
- **Web Audit Dashboard:** Developed a full-stack Flask/HTML web dashboard to inspect pipeline yield, audit hard-filter rejection snippets, and submit live ground-truth feedback directly to the database.
- **Production Automation & Testing:** Automated scheduled execution with file locking (`pipeline.lock`), log rotation, systemd/cron scripting, and comprehensive `pytest` test suites.

### **Suisik — Academic Document Extraction & Learning Platform**
*Next.js (TypeScript), Django, Supabase/PostgreSQL, Celery, LLM APIs*
- **Document & Knowledge Extraction:** Built an academic document ingestion pipeline extracting structured chapters, topics, and knowledge items from multi-page PDF and DOCX documents into hierarchical graph representations.
- **Multi-Model LLM Workflows:** Integrated multi-provider LLM APIs with fallback routing (OpenRouter) to generate, validate, and evaluate structured assessment questions and claim checks.
- **Full-Stack Review Application:** Designed a responsive web dashboard in Next.js (App Router, TypeScript) for reviewing generated content, tracking user progress, and inspecting extraction quality.
- **Database Migrations & Data Integrity:** Handled relational database migrations in Supabase (PostgreSQL), writing SQL scripts to resolve schema drift, repair orphan records, and enforce Row-Level Security (RLS) policies.

### **Verya — Visual Code Manipulation & Developer Tool**
*Open Source | React, TypeScript, Babel AST, Vite*
- **Bidirectional Visual Editing:** Created an open-source desktop developer tool allowing visual UI editing of React/TypeScript components with bidirectional code synchronization into clean source files.
- **AST Code Transformations:** Implemented Babel Abstract Syntax Tree (AST) transformations to safely parse, modify, and format code without introducing syntax errors or unintended side effects.
- **Safe Session Isolation:** Designed an isolated session architecture that provides instant preview diffs and conflict detection before writing changes back to the user's repository.

### **Essay Tracker — Desktop Writing Analysis App**
*React, TypeScript, Tauri (Rust), SQLite*
- Built a cross-platform desktop writing application with a React/TypeScript frontend and a high-performance Rust (Tauri) backend.
- Implemented local SQLite persistence and text analysis algorithms calculating vocabulary diversity, repetition frequency, and lexical evolution metrics over time.

### **AI-Task — Multi-Agent Benchmark & Simulation Harness**
*Python, Algorithmic Evaluation, Matplotlib*
- Built a simulation and benchmarking test harness running multi-agent pathfinding algorithms under partially observable conditions across hundreds of pseudo-random seeds.
- Generated automated statistical evaluations measuring survival rate, collision avoidance, and step efficiency to benchmark algorithmic trade-offs.

---

## Education & Certifications
- **Bachelor's in Computer Science (Artificial Intelligence focus)** — Softwarica College of IT and E-Commerce, Kathmandu
- **Diploma in Data Science and Machine Learning** — Vrit Technologies
- **LangChain + Gemini for LLM Applications**
