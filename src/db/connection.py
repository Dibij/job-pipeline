"""Database connection handling with Psycopg 3."""
import logging
from contextlib import contextmanager
from typing import Generator, Dict, Any
import psycopg
from psycopg.rows import dict_row

from src import config

logger = logging.getLogger(__name__)


@contextmanager
def get_connection(autocommit: bool = False) -> Generator[psycopg.Connection, None, None]:
    """Context manager providing a psycopg connection to the pipeline database."""
    conn = psycopg.connect(
        host=config.POSTGRES_HOST,
        port=config.POSTGRES_PORT,
        dbname=config.POSTGRES_DB,
        user=config.POSTGRES_USER,
        password=config.POSTGRES_PASSWORD,
        autocommit=autocommit,
        row_factory=dict_row,
    )
    try:
        yield conn
    finally:
        conn.close()


def check_db_health() -> Dict[str, Any]:
    """Runs a ping query against PostgreSQL and returns server metadata."""
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version(), current_database(), current_user;")
            row = cur.fetchone()
            return {
                "status": "healthy",
                "database": row["current_database"],
                "user": row["current_user"],
                "version": row["version"],
            }


def execute_query(sql: str, params: Any = None) -> list:
    """Convenience helper to run a query and return rows as dictionaries."""
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is not None:
                return cur.fetchall()
            return []


if __name__ == "__main__":
    health = check_db_health()
    print(f"PostgreSQL Status: {health['status'].upper()}")
    print(f"Database:          {health['database']}")
    print(f"User:              {health['user']}")
    print(f"Version:           {health['version'].split(',')[0]}")
    print("\nTable Row Counts:")
    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name != 'schema_migrations'
                ORDER BY table_name;
            """)
            tables = [row["table_name"] for row in cur.fetchall()]
            for tbl in tables:
                cur.execute(f"SELECT count(*) FROM {tbl};")
                cnt = cur.fetchone()["count"]
                print(f"  - {tbl}: {cnt}")
            
            # Print breakdown of raw_job_listings by source if populated
            cur.execute("SELECT source, count(*) FROM raw_job_listings GROUP BY source;")
            sources = cur.fetchall()
            if sources:
                print("\nRaw Staged by Source:")
                for s in sources:
                    print(f"  - {s['source']}: {s['count']} job(s)")
