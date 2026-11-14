# Kshitish Pandit
**Backend & Platform Software Engineer**

Kathmandu, Nepal | [dibijsharma@gmail.com](mailto:dibijsharma@gmail.com) | +977-9703995826  
[GitHub: github.com/Dibij](https://github.com/Dibij) | [LinkedIn: linkedin.com/in/kshitish-pandit](https://www.linkedin.com/in/kshitish-pandit)

---

## Professional Summary
Backend and platform software engineer experienced in architecting resilient data pipelines, asynchronous job processing engines, RESTful microservices, and high-integrity storage architectures across Python (FastAPI, Django), Java, Node.js, and Rust. Proven background in PostgreSQL schema design, ELT ingestion pipelines, connection pooling, Docker containerization, and production Linux deployment automation.

---

## Technical Skills
- **Languages:** Python (3.12+), Java, SQL, Rust, JavaScript/Node.js, Bash
- **Backend Frameworks:** FastAPI, Django, Django REST Framework, Django Channels (WebSockets), Express.js, Celery
- **Databases & Caching:** PostgreSQL, Psycopg 3, MySQL, SQLite, Supabase, Redis, Firebase/Firestore, schema migrations
- **Platform & Infrastructure:** Docker, Docker Compose, Linux/systemd, Git, GitHub Actions, cron automation, pytest, RESTful API design, rate-limiting

---

## Featured Backend & Platform Projects

### **Modular Data Ingestion & Evaluation Pipeline**
*Python (3.12+), PostgreSQL, Pydantic v2, Psycopg 3, Flask, Docker*
- Engineered an automated ELT pipeline aggregating semi-structured feeds from 15+ external JSON APIs, RSS feeds, and direct ATS endpoints with isolated per-source failure boundaries and polite rate-limiting.
- Preserved raw payloads in PostgreSQL staging tables to guarantee zero data loss; enforced strict Pydantic v2 validation models and SHA-256 hashing to eliminate cross-source duplicate records.
- Automated scheduled execution with process file locking (`pipeline.lock`), log rotation, systemd/cron automation, and comprehensive `pytest` test suites.
- Built an internal Flask management dashboard to monitor pipeline throughput, audit rejection logs, and submit live ground-truth feedback directly to the database.

### **Suisik — Backend & Asynchronous Job Processing Platform**
*Python, Django, Django REST Framework, Celery, Redis, PostgreSQL*
- Architected core backend services for an EdTech SaaS platform: REST APIs, document ingestion pipelines, and asynchronous Celery worker pools backed by Redis for CPU-intensive document chunking and LLM generation.
- Implemented custom rate-limiting middleware, structured exception handlers, database connection pooling, and health-check endpoints for operational reliability.
- Managed Supabase (PostgreSQL) migrations, writing SQL scripts to resolve schema drift, clean orphan records, and enforce Row-Level Security (RLS) policies.

### **YAMDUT — Ride-Sharing Platform Backend**
*Team Project | Java, Gradle, MySQL, REST APIs*
- Architected core backend services for a ride-sharing platform covering driver dispatch matching, authentication, and trip lifecycle management.
- Designed normalized relational database schemas in MySQL, indexing spatial coordinates for efficient driver-rider proximity lookups.
- Authored technical architecture documentation covering RESTful API contracts, database schemas, and service-layer patterns.

### **Notification Server Microservice**
*Node.js, Express.js, Firebase Admin SDK, Cloud Firestore*
- Built and deployed a production microservice delivering FCM push notifications, resolving device tokens and managing delivery state against Cloud Firestore.
- Designed lightweight REST endpoints with structured payload validation to ensure resilient message queuing and error recovery.

### **Shame Desktop & Cross-Platform Sync Engine**
*Rust, Tauri, SQLite, Supabase*
- Built a low-overhead native application backend in Rust (Tauri) interacting with local SQLite databases via transactional migrations, with cloud synchronization to Supabase/PostgreSQL.

---

## Certifications
- Diploma in Data Science and Machine Learning — Vrit Technologies
- LangChain + Gemini for LLM Applications

---

## Education
**Softwarica College of IT and E-Commerce**, Kathmandu  
Bachelor's in Computer Science (Artificial Intelligence focus)
