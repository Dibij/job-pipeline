"""scripts/ingest_triage_suggestions.py — Review & ingest Ollama triage suggestions.

Reads the JSON output of smart_label_triage.py, lets you confirm/override each
suggestion interactively (or pass --auto-ingest for non-interactive batch mode),
then writes confirmed labels to laya_labels with label_guideline_version='v2_role_fit_only'.

Usage:
    # Interactive review (recommended):
    python scripts/ingest_triage_suggestions.py data/triage_suggestions_YYYYMMDD_HHMM.json

    # Non-interactive: ingest only high-confidence good_fit suggestions (confidence >= 0.8)
    python scripts/ingest_triage_suggestions.py data/triage_suggestions_*.json --auto-ingest --min-confidence 0.8
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import uuid

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_connection

VALID_LABELS = {"good_fit", "maybe", "bad_fit"}


def ingest_label(
    conn,
    job_id: str,
    label: str,
    notes: str,
    model_source: str,
) -> bool:
    """Insert a single label into laya_labels. Returns True on success."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO laya_labels
                    (job_id, label, notes, sampling_stratum, label_guideline_version, labeled_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (job_id) DO NOTHING;
            """, (
                uuid.UUID(job_id),
                label,
                notes,
                "ollama_triage",
                "v2_role_fit_only",
                datetime.now(timezone.utc),
            ))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"  DB error for {job_id}: {e}")
        return False


def interactive_review(suggestions: list, conn) -> tuple[int, int, int]:
    """Walk through suggestions interactively. Returns (ingested, skipped, overridden)."""
    ingested = skipped = overridden = 0
    total = len(suggestions)

    print(f"\nReviewing {total} suggestions. Commands: [Enter]=accept, [label]=override, [s]=skip, [q]=quit\n")

    for i, s in enumerate(suggestions, 1):
        title = s["title"]
        company = s.get("company", "Unknown")
        label = s["ollama_label"]
        conf = s["ollama_confidence"]
        reason = s["ollama_reason"]
        ms = s.get("ms_score", "?")
        ly = s.get("laya_score", "?")
        icon = {"good_fit": "[OK]", "maybe": "[?] ", "bad_fit": "[X] "}.get(label, "[ ]")

        print(f"[{i}/{total}] {icon} {label.upper()} ({conf:.0%} conf)  MS={ms}  Laya={ly}")
        print(f"  Title:   {title}")
        print(f"  Company: {company}")
        print(f"  Reason:  {reason}")

        while True:
            raw = input("  Action [Enter=accept / good_fit|maybe|bad_fit / s=skip / q=quit]: ").strip().lower()
            if raw == "" or raw == "accept":
                final_label = label
                break
            elif raw in VALID_LABELS:
                final_label = raw
                overridden += 1
                break
            elif raw == "s":
                skipped += 1
                print()
                break
            elif raw == "q":
                print("Quitting review early.")
                return ingested, skipped, overridden
            else:
                print("  [!] Invalid input. Use Enter, good_fit, maybe, bad_fit, s, or q.")

        if raw not in ("s", "q"):
            notes = f"Ollama ({s.get('ollama_model','?')}): {reason}"
            if ingest_label(conn, s["job_id"], final_label, notes, s.get("ollama_model", "?")):
                ingested += 1
                print(f"  [OK] Saved {final_label}\n")
            else:
                skipped += 1

    return ingested, skipped, overridden


def auto_ingest(suggestions: list, conn, min_confidence: float) -> tuple[int, int]:
    """Non-interactive: ingest only suggestions with confidence >= min_confidence."""
    ingested = skipped = 0
    for s in suggestions:
        if s["ollama_confidence"] >= min_confidence:
            notes = f"Ollama auto ({s.get('ollama_model','?')}): {s['ollama_reason']}"
            if ingest_label(conn, s["job_id"], s["ollama_label"], notes, s.get("ollama_model", "?")):
                ingested += 1
                print(f"  [OK] {s['ollama_label']:<10} ({s['ollama_confidence']:.0%})  {s['title'][:60]}")
            else:
                skipped += 1
        else:
            skipped += 1
    return ingested, skipped


def main():
    parser = argparse.ArgumentParser(description="Review and ingest Ollama triage suggestions.")
    parser.add_argument("file", help="Path to triage_suggestions_*.json from smart_label_triage.py")
    parser.add_argument("--auto-ingest", action="store_true", help="Non-interactive auto-ingest")
    parser.add_argument("--min-confidence", type=float, default=0.80,
                        help="Min Ollama confidence for auto-ingest (default 0.80)")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    suggestions = json.loads(path.read_text(encoding="utf-8"))
    print(f"\nLoaded {len(suggestions)} suggestions from {path.name}")

    # Filter out any that already have labels in DB
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT job_id::text FROM laya_labels;")
            already_labeled = {r["job_id"] for r in cur.fetchall()}

    new_suggestions = [s for s in suggestions if s["job_id"] not in already_labeled]
    already_done = len(suggestions) - len(new_suggestions)
    if already_done:
        print(f"  ({already_done} already labeled in DB — skipping)")

    if not new_suggestions:
        print("All suggestions already ingested. Done.")
        return

    good_fits = [s for s in new_suggestions if s["ollama_label"] == "good_fit"]
    maybes = [s for s in new_suggestions if s["ollama_label"] == "maybe"]
    bad_fits = [s for s in new_suggestions if s["ollama_label"] == "bad_fit"]
    print(f"  good_fit: {len(good_fits)}  maybe: {len(maybes)}  bad_fit: {len(bad_fits)}")

    with get_connection() as conn:
        if args.auto_ingest:
            print(f"\nAuto-ingesting (confidence >= {args.min_confidence:.0%})...")
            ingested, skipped = auto_ingest(new_suggestions, conn, args.min_confidence)
            print(f"\nDone. Ingested: {ingested}  Skipped (low confidence / error): {skipped}")
        else:
            ingested, skipped, overridden = interactive_review(new_suggestions, conn)
            print(f"\nDone. Ingested: {ingested}  Skipped: {skipped}  Overridden: {overridden}")


if __name__ == "__main__":
    main()
