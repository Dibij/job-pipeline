"""Export human-labeled job descriptions to two local files.

Bookkeeping file (data/labeled_jobs_bookkeeping.jsonl):
    job_id, title, company, source, label, rating, notes,
    label_guideline_version, description_clean

Training file (data/labeled_jobs_training.jsonl):
    job_id, text ("TITLE: {title}\\n\\n{description_clean}"), label, is_synthetic

The description_clean field has HTML tags/entities stripped, mojibake fixed
(cp1252→utf-8 fallback; ftfy used if installed), and whitespace normalized.

Both files are gitignored (data/ is excluded from the repo).
"""
import html
import json
import logging
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import execute_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOOKKEEPING_PATH = PROJECT_ROOT / "data" / "labeled_jobs_bookkeeping.jsonl"
TRAINING_PATH    = PROJECT_ROOT / "data" / "labeled_jobs_training.jsonl"

# ---------------------------------------------------------------------------
# Description cleaning
# ---------------------------------------------------------------------------

# Try to import ftfy for superior mojibake repair
try:
    import ftfy as _ftfy
    _HAS_FTFY = True
except ImportError:
    _HAS_FTFY = False

# Mojibake detection: sequences like â€™  Ã©  Â» produced by UTF-8 bytes
# decoded as cp1252/ISO-8859-1.
_MOJIBAKE_RE = re.compile(r"[\u00c2\u00c3\u00e2][\u0080-\u00bf]")


def _fix_mojibake(text: str) -> str:
    """Try to recover UTF-8 text that was decoded as cp1252."""
    try:
        return text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def clean_description(raw: str) -> tuple[str, dict[str, int]]:
    """Clean a job description; return (cleaned_text, counts_per_rule)."""
    counts = {"html_entities": 0, "html_tags": 0, "mojibake": 0, "whitespace": 0}
    text = raw or ""

    # 1. HTML entities  (&amp; &nbsp; &#39; …)
    decoded = html.unescape(text)
    if decoded != text:
        counts["html_entities"] = 1
    text = decoded

    # 2. HTML tags  (<p> <br/> <strong> …)
    stripped = re.sub(r"<[^>]+>", " ", text)
    if stripped != text:
        counts["html_tags"] = 1
    text = stripped

    # 3. Mojibake
    if _MOJIBAKE_RE.search(text):
        if _HAS_FTFY:
            fixed = _ftfy.fix_text(text)
        else:
            fixed = _fix_mojibake(text)
        if fixed != text:
            counts["mojibake"] = 1
        text = fixed

    # 4. Normalize whitespace (collapse runs, strip edges)
    normalized = re.sub(r"[ \t]+", " ", text)          # multiple spaces/tabs → one space
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)  # 3+ newlines → 2
    normalized = normalized.strip()
    if normalized != text:
        counts["whitespace"] = 1
    text = normalized

    return text, counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _extract_meta_fields(meta_raw) -> tuple:
    """Return (rating, source_from_meta) from the metadata JSONB column."""
    if isinstance(meta_raw, str):
        try:
            meta_raw = json.loads(meta_raw)
        except Exception:
            meta_raw = {}
    meta = meta_raw or {}
    return meta.get("rating"), meta.get("source")


def export(
    bookkeeping_path: Path = BOOKKEEPING_PATH,
    training_path: Path = TRAINING_PATH,
) -> None:
    bookkeeping_path.parent.mkdir(parents=True, exist_ok=True)
    training_path.parent.mkdir(parents=True, exist_ok=True)

    rows = execute_query("""
        SELECT
            l.job_id,
            l.label,
            l.notes,
            l.metadata,
            l.label_guideline_version,
            l.labeled_at,
            j.title,
            j.company_name,
            j.source,
            j.description_text,
            j.detected_language
        FROM laya_labels l
        JOIN jobs j ON l.job_id = j.id
        ORDER BY l.labeled_at ASC NULLS FIRST;
    """)

    if not rows:
        logger.warning("No labeled rows found. Nothing exported.")
        return

    # Deduplicate: keep the latest label per job_id
    unique: dict[int, dict] = {}
    for r in rows:
        unique[r["job_id"]] = dict(r)
    records = list(unique.values())
    logger.info("Fetched %d label events → %d unique jobs after deduplication", len(rows), len(records))

    # -----------------------------------------------------------------------
    # Cleaning pass
    # -----------------------------------------------------------------------
    total_counts = {"html_entities": 0, "html_tags": 0, "mojibake": 0, "whitespace": 0}
    before_after_examples: list[tuple[str, str]] = []

    cleaned_records = []
    for r in records:
        raw = (r["description_text"] or "").strip()
        cleaned, counts = clean_description(raw)
        for k in total_counts:
            total_counts[k] += counts[k]

        changed = any(v for v in counts.values())
        if changed and len(before_after_examples) < 5:
            before_after_examples.append((raw[:300], cleaned[:300]))

        r["description_clean"] = cleaned
        cleaned_records.append(r)

    # -----------------------------------------------------------------------
    # Print cleaning report
    # -----------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("  DESCRIPTION CLEANING REPORT")
    print("=" * 64)
    print(f"  Total records:       {len(cleaned_records)}")
    print(f"  ftfy available:      {'yes' if _HAS_FTFY else 'no (cp1252 fallback used)'}")
    for rule, cnt in total_counts.items():
        print(f"  Rows changed [{rule:<15}]: {cnt}")

    if before_after_examples:
        print("\n  --- Before / After Examples (up to 5) ---")
        for i, (bef, aft) in enumerate(before_after_examples, 1):
            print(f"\n  [{i}] BEFORE: {repr(bef[:120])}")
            print(f"      AFTER:  {repr(aft[:120])}")

    # -----------------------------------------------------------------------
    # Non-English rows report
    # -----------------------------------------------------------------------
    non_english = [r for r in cleaned_records if (r.get("detected_language") or "english") != "english"]
    print("\n" + "=" * 64)
    print("  NON-ENGLISH ROWS (not excluded — awaiting your decision)")
    print("=" * 64)
    if non_english:
        for r in non_english:
            print(
                f"  job_id={r['job_id']}  lang={r['detected_language']!r:12s}"
                f"  label={r['label']!r:10s}  title={str(r.get('title',''))[:60]!r}"
            )
    else:
        print("  None found.")

    # -----------------------------------------------------------------------
    # Write bookkeeping file
    # -----------------------------------------------------------------------
    label_counts: dict[str, int] = {}
    with open(bookkeeping_path, "w", encoding="utf-8") as f:
        for r in cleaned_records:
            label = r["label"]
            label_counts[label] = label_counts.get(label, 0) + 1
            rating, _src = _extract_meta_fields(r.get("metadata"))
            record = {
                "job_id":                  r["job_id"],
                "title":                   r.get("title"),
                "company":                 r.get("company_name"),
                "source":                  r.get("source"),
                "label":                   label,
                "rating":                  rating,
                "notes":                   r.get("notes"),
                "label_guideline_version": r.get("label_guideline_version"),
                "description_clean":       r["description_clean"],
            }
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    logger.info("Bookkeeping file written: %s (%d records)", bookkeeping_path, len(cleaned_records))

    # -----------------------------------------------------------------------
    # Write training file
    # -----------------------------------------------------------------------
    with open(training_path, "w", encoding="utf-8") as f:
        for r in cleaned_records:
            title = (r.get("title") or "").strip()
            text = f"TITLE: {title}\n\n{r['description_clean']}" if title else r["description_clean"]
            record = {
                "job_id":       r["job_id"],
                "text":         text,
                "label":        r["label"],
                "is_synthetic": False,
            }
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    logger.info("Training file written: %s (%d records)", training_path, len(cleaned_records))

    # -----------------------------------------------------------------------
    # Join check: old JSONL vs jobs table
    # -----------------------------------------------------------------------
    old_jsonl = PROJECT_ROOT / "data" / "labeled_job_descriptions.jsonl"
    if old_jsonl.exists():
        import hashlib
        db_hashes: dict[str, int] = {}
        hash_rows = execute_query("SELECT id, description_text FROM jobs WHERE description_text IS NOT NULL;")
        for hr in hash_rows:
            h = hashlib.md5((hr["description_text"] or "").strip().encode()).hexdigest()
            db_hashes[h] = hr["id"]

        matched = unmatched = 0
        unmatched_labels: list[str] = []
        with open(old_jsonl, encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                desc = (obj.get("description") or "").strip()
                h = hashlib.md5(desc.encode()).hexdigest()
                if h in db_hashes:
                    matched += 1
                else:
                    unmatched += 1
                    unmatched_labels.append(obj.get("label", "?"))

        print("\n" + "=" * 64)
        print("  JOIN CHECK: old labeled_job_descriptions.jsonl vs jobs table")
        print("=" * 64)
        print(f"  Old JSONL total:   {matched + unmatched}")
        print(f"  Matched by hash:   {matched}")
        print(f"  Unmatched:         {unmatched}")
        if unmatched_labels:
            from collections import Counter
            print(f"  Unmatched labels:  {dict(Counter(unmatched_labels))}")
    else:
        print("\n  (old labeled_job_descriptions.jsonl not found — skipping join check)")

    # -----------------------------------------------------------------------
    # Final summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("  EXPORT COMPLETE")
    print("=" * 64)
    print(f"  Bookkeeping: {bookkeeping_path}")
    print(f"  Training:    {training_path}")
    print(f"  Total:       {len(cleaned_records)} records")
    print("  Label breakdown:")
    for lbl, cnt in sorted(label_counts.items(), key=lambda x: -x[1]):
        print(f"    {lbl:<12}: {cnt:3}  ({cnt/len(cleaned_records)*100:.1f}%)")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    export()
