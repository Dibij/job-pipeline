# Scheduled Pipeline Execution via Docker / Cron

If you prefer to run the daily pipeline in a background container or on a Linux server/NAS instead of Windows Task Scheduler, follow this guide.

---

## 1. Docker Compose Setup

A single container service running the scheduled runner daily at 06:00 UTC using `cron` or `ofelia`.

### `Dockerfile`
```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    cron \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Set up crontab (runs at 06:00 UTC daily)
RUN echo "0 6 * * * cd /app && /usr/local/bin/python scripts/run_scheduled.py >> /app/logs/cron.log 2>&1" > /etc/cron.d/job-pipeline \
    && chmod 0644 /etc/cron.d/job-pipeline \
    && crontab /etc/cron.d/job-pipeline

CMD ["cron", "-f"]
```

### `docker-compose.yml`
```yaml
version: '3.8'

services:
  pipeline:
    build: .
    container_name: job-pipeline-runner
    environment:
      - DB_HOST=postgres
      - DB_PORT=5432
      - DB_NAME=job_pipeline
      - DB_USER=postgres
      - DB_PASSWORD=${DB_PASSWORD}
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./FEED.md:/app/FEED.md
    depends_on:
      - postgres
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    container_name: job-pipeline-db
    environment:
      - POSTGRES_DB=job_pipeline
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

volumes:
  pgdata:
```

---

## 2. Linux Crontab (Host Direct)

If running directly on a Linux VPS without Docker:

```bash
# Open crontab editor
crontab -e

# Run every day at 06:00 local time
0 6 * * * cd /path/to/Job && .venv/bin/python scripts/run_scheduled.py >> logs/cron.log 2>&1
```

---

## 3. Safety Guarantees Maintained
Regardless of the runtime environment (Windows Task Scheduler, Docker, or Linux cron):
- **Overlapping Lock**: `data/pipeline.lock` guarantees that runs cannot execute concurrently.
- **Rotating Logs**: Handled via `logs/scheduled_run.log` (5MB rotating window, 5 backups).
- **Metric Tracking**: Records each run's timestamps and counts to the PostgreSQL `source_runs` table.
- **Failure Exit**: Non-zero exit code ensures cron/orchestrator notifications on error.
