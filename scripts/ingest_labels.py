"""Ingest human-labeled jobs into PostgreSQL database (Task 7.7b).

Reads and validates labeling CSVs.
Inserts valid labels into `laya_labels` table without overwriting prior records.
Stores sampling_stratum and label_guideline_version from the CSV (added in 7.7b).
Uses per-row savepoints to prevent single bad rows from aborting the entire batch.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path
import sys
import uuid
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

VALID_LABELS = {"good_fit", "maybe", "bad_fit"}
LABEL_MAPPING = {
    "drop": "bad_fit",
}
MAX_STRATUM_LEN = 64
MAX_GUIDELINE_VER_LEN = 64


def load_and_validate_csv(csv_path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Read CSV and perform pre-flight validation.

    Returns:
        (valid_records, stats)
    """
    rows = []
    for enc in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
        try:
            with open(csv_path, "r", encoding=enc) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            break
        except UnicodeDecodeError:
            continue

    total_rows = len(rows)
    valid_records = []
    skipped_empty = 0
    skipped_invalid = 0
    mapped_count = 0

    for idx, row in enumerate(rows, start=1):
        raw_id = (row.get("job_id") or "").strip()
        raw_label = (row.get("my_label") or "").strip().lower()
        notes = (row.get("notes") or "").strip()
        stratum = (row.get("sampling_stratum") or "").strip()
        guideline_ver = (row.get("label_guideline_version") or "").strip()

        # 1. Check for empty label
        if not raw_label or raw_label in ("nan", "none", "null"):
            skipped_empty += 1
            continue

        # 2. Check label validity or map alias
        target_label = raw_label
        original_label = None
        if raw_label in LABEL_MAPPING:
            target_label = LABEL_MAPPING[raw_label]
            original_label = raw_label
            mapped_count += 1
        elif raw_label not in VALID_LABELS:
            logger.warning(
                "Row %d: Invalid label '%s' for job %s. Must be one of: %s",
                idx, raw_label, raw_id, VALID_LABELS
            )
            skipped_invalid += 1
            continue

        # 3. Check UUID validity
        try:
            job_uuid = uuid.UUID(raw_id)
        except ValueError:
            logger.warning("Row %d: Invalid UUID '%s'", idx, raw_id)
            skipped_invalid += 1
            continue

        # 4. Check / truncate string lengths to prevent DB overflow
        if len(stratum) > MAX_STRATUM_LEN:
            logger.warning(
                "Row %d: sampling_stratum '%s' exceeds %d chars; truncating",
                idx, stratum, MAX_STRATUM_LEN
            )
            stratum = stratum[:MAX_STRATUM_LEN]

        if len(guideline_ver) > MAX_GUIDELINE_VER_LEN:
            logger.warning(
                "Row %d: label_guideline_version '%s' exceeds %d chars; truncating",
                idx, guideline_ver, MAX_GUIDELINE_VER_LEN
            )
            guideline_ver = guideline_ver[:MAX_GUIDELINE_VER_LEN]

        # Metadata
        meta = {
            "source_csv": csv_path.name,
            "title": row.get("title", ""),
            "company": row.get("company", ""),
            "laya_score": row.get("laya_score"),
            "avg_confidence": row.get("avg_confidence"),
        }
        if original_label:
            meta["original_label"] = original_label

        valid_records.append({
            "job_id": str(job_uuid),
            "label": target_label,
            "notes": notes,
            "metadata": json.dumps(meta),
            "sampling_stratum": stratum or None,
            "label_guideline_version": guideline_ver or None,
        })

    stats = {
        "total_rows": total_rows,
        "ready_to_insert": len(valid_records),
        "skipped_empty": skipped_empty,
        "skipped_invalid": skipped_invalid,
        "mapped_count": mapped_count,
    }
    return valid_records, stats


def ingest_labels_from_csv(csv_path: Path, dry_run: bool = False):
    if not csv_path.exists():
        logger.error("File not found: %s", csv_path)
        return

    logger.info("Reading labels from: %s", csv_path)
    valid_records, stats = load_and_validate_csv(csv_path)

    logger.info("-" * 50)
    logger.info("PRE-FLIGHT VALIDATION:")
    logger.info("  Total rows in CSV:   %d", stats["total_rows"])
    logger.info("  Ready to insert:     %d (including %d mapped from 'drop' -> 'bad_fit')",
                stats["ready_to_insert"], stats["mapped_count"])
    logger.info("  Skipped (unlabeled): %d", stats["skipped_empty"])
    logger.info("  Skipped (invalid):   %d", stats["skipped_invalid"])
    logger.info("-" * 50)

    if dry_run:
        logger.info("[DRY RUN] Skipping database insertion.")
        return

    inserted = 0
    failed = 0

    with get_connection(autocommit=False) as conn:
        with conn.cursor() as cur:
            for rec in valid_records:
                try:
                    # Savepoint per row: an error rolls back only this row,
                    # leaving the transaction healthy for subsequent rows.
                    with conn.transaction():
                        cur.execute("""
                            INSERT INTO laya_labels
                                (job_id, label, notes, metadata, sampling_stratum, label_guideline_version)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (job_id, labeled_at) DO NOTHING;
                        """, (
                            rec["job_id"],
                            rec["label"],
                            rec["notes"],
                            rec["metadata"],
                            rec["sampling_stratum"],
                            rec["label_guideline_version"],
                        ))
                    inserted += 1
                except Exception as e:
                    logger.error("Failed to insert label for %s: %s", rec["job_id"], e)
                    failed += 1

            conn.commit()

    logger.info("=" * 50)
    logger.info("INGESTION SUMMARY:")
    logger.info("  Inserted Labels:     %d", inserted)
    logger.info("  Failed (DB errors):  %d", failed)
    logger.info("  Skipped (unlabeled): %d", stats["skipped_empty"])
    logger.info("  Skipped (invalid):   %d", stats["skipped_invalid"])
    logger.info("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest human labels from CSV.")
    parser.add_argument("csv_file", type=str, help="Path to labeled CSV file.")
    parser.add_argument("--dry-run", action="store_true", help="Validate without inserting into DB.")
    args = parser.parse_args()
    ingest_labels_from_csv(Path(args.csv_file), dry_run=args.dry_run)
