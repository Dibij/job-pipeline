"""Ingest human-labeled jobs into PostgreSQL database (Task 7.8).

Reads and validates labeling CSVs.
Inserts valid labels into `laya_labels` table without overwriting prior records.
"""
import argparse
import csv
import json
import logging
from pathlib import Path
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

VALID_LABELS = {"good_fit", "maybe", "bad_fit"}


def ingest_labels_from_csv(csv_path: Path):
    if not csv_path.exists():
        logger.error("File not found: %s", csv_path)
        return

    logger.info("Reading labels from: %s", csv_path)
    inserted = 0
    skipped_empty = 0
    skipped_invalid = 0
    skipped_duplicate = 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    with get_connection(autocommit=False) as conn:
        with conn.cursor() as cur:
            for row in rows:
                raw_id = row.get("job_id", "").strip()
                raw_label = row.get("my_label", "").strip().lower()
                notes = row.get("notes", "").strip()

                if not raw_label:
                    skipped_empty += 1
                    continue

                if raw_label not in VALID_LABELS:
                    logger.warning("Invalid label '%s' for job %s. Must be one of: %s",
                                   raw_label, raw_id, VALID_LABELS)
                    skipped_invalid += 1
                    continue

                try:
                    job_uuid = uuid.UUID(raw_id)
                except ValueError:
                    logger.warning("Invalid UUID: %s", raw_id)
                    skipped_invalid += 1
                    continue

                # Store metadata from other columns
                meta = {
                    "source_csv": csv_path.name,
                    "title": row.get("title", ""),
                    "company": row.get("company", ""),
                    "laya_score": row.get("laya_score"),
                    "avg_confidence": row.get("avg_confidence")
                }

                try:
                    cur.execute("""
                        INSERT INTO laya_labels (job_id, label, notes, metadata)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (job_id, labeled_at) DO NOTHING;
                    """, (str(job_uuid), raw_label, notes, json.dumps(meta)))
                    inserted += 1
                except Exception as e:
                    logger.error("Failed to insert label for %s: %s", raw_id, e)
            conn.commit()

    logger.info("=" * 50)
    logger.info("INGESTION SUMMARY:")
    logger.info("  Inserted Labels:    %d", inserted)
    logger.info("  Skipped (unlabeled): %d", skipped_empty)
    logger.info("  Skipped (invalid):   %d", skipped_invalid)
    logger.info("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest human labels from CSV.")
    parser.add_argument("csv_file", type=str, help="Path to labeled CSV file.")
    args = parser.parse_args()
    ingest_labels_from_csv(Path(args.csv_file))
