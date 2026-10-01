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
