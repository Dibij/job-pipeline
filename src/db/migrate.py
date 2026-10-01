"""Database migration runner."""
import logging
from pathlib import Path
from typing import List
from src.db.connection import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def ensure_migration_table():
    """Ensure schema_migrations table exists to track applied migrations."""
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)


def get_applied_migrations() -> set:
    """Fetch set of migration file names already executed."""
    ensure_migration_table()
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations;")
            rows = cur.fetchall()
            return {row["version"] for row in rows}


def run_migrations() -> List[str]:
    """Execute all pending migration scripts in alphanumeric order."""
    ensure_migration_table()
    applied = get_applied_migrations()
    applied_this_run = []

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        logger.info("No migration files found in %s", MIGRATIONS_DIR)
        return applied_this_run

    with get_connection(autocommit=False) as conn:
        with conn.cursor() as cur:
            for sql_path in sql_files:
                filename = sql_path.name
                if filename in applied:
                    logger.debug("Migration already applied: %s", filename)
                    continue

                logger.info("Applying migration: %s", filename)
                sql_content = sql_path.read_text(encoding="utf-8")
                cur.execute(sql_content)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s);",
                    (filename,),
                )
                applied_this_run.append(filename)

        conn.commit()

    if applied_this_run:
        logger.info("Successfully applied %d migration(s): %s", len(applied_this_run), applied_this_run)
    else:
        logger.info("Database is already up to date. No pending migrations.")

    return applied_this_run


if __name__ == "__main__":
    run_migrations()
