"""scripts/export_gold.py -- Export frozen gold labels snapshot for evaluation harness.

Exports distinct jobs labeled under 'v2_role_fit_only'.
Zero full JD text is exported to adhere to third-party content and ToS policies;
only description SHA-256 hashes and short preview snippets (<=200 chars) are included.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import datetime, timezone
import logging
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

GOLD_DIR = PROJECT_ROOT / "evals" / "gold"


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 digest of a local file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_text_hash(text: str | None) -> str:
    """Compute SHA-256 of text."""
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def export_gold_dataset(output_dir: Path = GOLD_DIR) -> Path:
    """Export v2_role_fit_only labels from PostgreSQL to a frozen gold CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    output_csv = output_dir / f"gold_{today_str}.csv"
    latest_csv = output_dir / "gold_latest.csv"

    query = """
        SELECT DISTINCT ON (j.id)
            j.id AS job_id,
            COALESCE(j.company_name, 'unknown') AS company,
            COALESCE(j.source, 'unknown') AS source,
            COALESCE(j.title, '') AS title,
            l.label AS label,
            l.label_guideline_version AS guideline_version,
            COALESCE(j.exclude_reason, '') AS exclude_reason,
            j.description_text AS description_raw,
            l.labeled_at AS labeled_at
        FROM laya_labels l
        JOIN jobs j ON l.job_id = j.id
        WHERE l.label_guideline_version = 'v2_role_fit_only'
        ORDER BY j.id, l.labeled_at DESC NULLS LAST, l.id DESC;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()

    if not rows:
        raise RuntimeError("No v2_role_fit_only labels found in database.")

    fieldnames = [
        "job_id",
        "company",
        "source",
        "title",
        "label",
        "guideline_version",
        "description_hash",
        "description_snippet",
        "exclude_reason",
    ]

    records: List[Dict[str, Any]] = []
    class_counts: Dict[str, int] = {}
    companies = set()

    for r in rows:
        desc = r.get("description_raw") or ""
        snippet = " ".join(desc[:200].split())
        record = {
            "job_id": str(r["job_id"]),
            "company": str(r["company"]).strip(),
            "source": str(r["source"]).strip(),
            "title": str(r["title"]).strip(),
            "label": str(r["label"]).strip(),
            "guideline_version": str(r["guideline_version"]).strip(),
            "description_hash": compute_text_hash(desc),
            "description_snippet": snippet,
            "exclude_reason": str(r.get("exclude_reason") or "").strip(),
        }
        records.append(record)
        lbl = record["label"]
        class_counts[lbl] = class_counts.get(lbl, 0) + 1
        companies.add(record["company"].lower())

    # Sort records deterministically by job_id for reproducible hashes
    records.sort(key=lambda x: x["job_id"])

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    shutil.copyfile(output_csv, latest_csv)

    file_hash = compute_file_sha256(output_csv)
    sha_file = output_dir / f"gold_{today_str}.sha256"
    sha_latest = output_dir / "gold_latest.sha256"
    sha_file.write_text(f"{file_hash}  {output_csv.name}\n", encoding="utf-8")
    sha_latest.write_text(f"{file_hash}  gold_latest.csv\n", encoding="utf-8")

    logger.info("==================================================")
    logger.info("GOLD DATASET EXPORT COMPLETE")
    logger.info("Destination:        %s", output_csv)
    logger.info("Latest alias:       %s", latest_csv)
    logger.info("Distinct jobs (n):  %d", len(records))
    logger.info("Distinct companies: %d", len(companies))
    logger.info("Class distribution: %s", class_counts)
    logger.info("SHA-256 hash:       %s", file_hash)
    logger.info("==================================================")

    return output_csv


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export frozen gold dataset.")
    parser.add_argument("--out-dir", type=Path, default=GOLD_DIR, help="Output directory")
    args = parser.parse_args()
    export_gold_dataset(output_dir=args.out_dir)
