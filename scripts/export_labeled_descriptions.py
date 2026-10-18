"""Export human-labeled job descriptions locally for synthetic generation.

Strips all metadata and identifiers (no job_id, no external_id, no company name,
no job title, no URLs, no locations), preserving strictly the human label and the
full job description text.

Output:
    data/labeled_job_descriptions.jsonl
"""
import argparse
import json
import logging
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "labeled_job_descriptions.jsonl"


def export_labeled_descriptions(output_path: Path = DEFAULT_OUTPUT_PATH, deduplicate: bool = True) -> int:
    """Fetch labeled jobs and export anonymized descriptions to JSONL."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Order by labeled_at ASC so later labels overwrite earlier ones during deduplication
    rows = execute_query("""
        SELECT l.job_id, l.label, l.metadata, l.labeled_at, j.description_text
        FROM laya_labels l
        JOIN jobs j ON l.job_id = j.id
        WHERE j.description_text IS NOT NULL AND trim(j.description_text) != ''
        ORDER BY l.labeled_at ASC NULLS FIRST;
    """)

    if not rows:
        logger.warning("No labeled jobs with description text found in database.")
        return 0

    if deduplicate:
        # Keep latest label per job_id
        unique_jobs = {}
        for r in rows:
            unique_jobs[str(r["job_id"])] = r
        records_to_export = list(unique_jobs.values())
    else:
        records_to_export = rows

    label_counts = {}
    with open(output_path, "w", encoding="utf-8") as f:
        for r in records_to_export:
            label = r["label"]
            label_counts[label] = label_counts.get(label, 0) + 1

            meta = r.get("metadata") or {}
            rating = None
            if isinstance(meta, dict):
                rating = meta.get("rating")
            elif isinstance(meta, str):
                try:
                    meta_dict = json.loads(meta)
                    rating = meta_dict.get("rating")
                except Exception:
                    pass

            record = {
                "label": label,
                "description": r["description_text"].strip(),
            }
            if rating is not None:
                record["rating"] = rating

            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info("Successfully exported %d anonymized labeled descriptions to %s", len(records_to_export), output_path)
    print("\n" + "=" * 60)
    print("  ANONYMIZED LABELED DESCRIPTIONS EXPORTED")
    print("=" * 60)
    print(f"  Target File:     {output_path}")
    print(f"  Total Postings:  {len(records_to_export)}")
    print(f"  Breakdown:")
    for lbl, cnt in sorted(label_counts.items(), key=lambda x: -x[1]):
        pct = (cnt / len(records_to_export)) * 100
        print(f"    - {lbl:<12}: {cnt:3} ({pct:.1f}%)")
    print(f"  Identifiers:     STRIPPED (no IDs, titles, companies, or URLs)")
    print("=" * 60 + "\n")

    return len(records_to_export)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export anonymized labeled job descriptions locally.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to output JSONL file (defaults to data/labeled_job_descriptions.jsonl).",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Export all label events rather than deduplicating to the latest label per job.",
    )
    args = parser.parse_args()
    export_labeled_descriptions(output_path=args.output, deduplicate=not args.no_dedup)
