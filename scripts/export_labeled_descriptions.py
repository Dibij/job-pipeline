"""Export human-labeled job descriptions to two local files.

Bookkeeping file (data/labeled_jobs_bookkeeping.jsonl):
    job_id, title, company, source, label, rating, notes,
    label_guideline_version, description_clean

Training file (data/labeled_jobs_training.jsonl):
    job_id, text ("TITLE: {title_clean}\\n\\n{description_clean}"), label, is_synthetic

The description_clean and title_clean fields have HTML tags/entities stripped,
mojibake fixed (targeted regex latin-1→utf-8 sequence re-decoding), and whitespace normalized.

Non-English rows (detected using title + first 500 chars) are kept in the bookkeeping file
but strictly excluded from the training file.

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
from src.enrichment.enricher import JobEnricher

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

# Mojibake detection: multi-byte UTF-8 sequences that were decoded as latin-1/cp1252
_MOJIBAKE_PATTERN = re.compile(
    r"([\xc2-\xdf][\x80-\xbf]|[\xe0-\xef][\x80-\xbf]{2}|[\xf0-\xf4][\x80-\xbf]{3})+"
)


def _fix_mojibake(text: str) -> str:
    """Recover UTF-8 byte sequences that were mistakenly decoded as latin-1."""
    if _HAS_FTFY:
        return _ftfy.fix_text(text)

    def repl(match):
        s = match.group(0)
        try:
            return s.encode("latin-1").decode("utf-8")
        except UnicodeDecodeError:
            return s

    return _MOJIBAKE_PATTERN.sub(repl, text)


def clean_text(raw: str) -> tuple[str, dict[str, int]]:
    """Clean text by unescaping entities, stripping HTML, fixing mojibake, normalizing whitespace."""
    counts = {"html_entities": 0, "html_tags": 0, "mojibake": 0, "whitespace": 0}
    text = raw or ""

    # 1. HTML entities (&amp; &nbsp; &#39; …) - unescape twice for double-escaped entities
    decoded = html.unescape(text)
    decoded = html.unescape(decoded)
    if decoded != text:
        counts["html_entities"] = 1
    text = decoded

    # 2. HTML tags (<p> <br/> <strong> …)
    stripped = re.sub(r"<[^>]+>", " ", text)
    if stripped != text:
        counts["html_tags"] = 1
    text = stripped

    # 3. Mojibake repair
    fixed = _fix_mojibake(text)
    if fixed != text:
        counts["mojibake"] = 1
    text = fixed

    # 4. Normalize whitespace (collapse runs, strip edges)
    normalized = re.sub(r"[ \t]+", " ", text)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
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
    unique: dict[str, dict] = {}
    for r in rows:
        unique[str(r["job_id"])] = dict(r)
    records = list(unique.values())
    logger.info("Fetched %d label events → %d unique jobs after deduplication", len(rows), len(records))

    # -----------------------------------------------------------------------
    # Cleaning pass & Language detection
    # -----------------------------------------------------------------------
    total_counts = {"html_entities": 0, "html_tags": 0, "mojibake": 0, "whitespace": 0}
    before_after_examples: list[tuple[str, str]] = []

    cleaned_records = []
    for r in records:
        raw_desc = (r["description_text"] or "").strip()
        raw_title = (r.get("title") or "").strip()

        cleaned_desc, desc_counts = clean_text(raw_desc)
        cleaned_title, title_counts = clean_text(raw_title)

        for k in total_counts:
            total_counts[k] += int(desc_counts[k] > 0 or title_counts[k] > 0)

        changed = any(v for v in desc_counts.values()) or any(v for v in title_counts.values())
        if changed and len(before_after_examples) < 5:
            before_after_examples.append((raw_desc[:300], cleaned_desc[:300]))

        r["title_clean"] = cleaned_title
        r["description_clean"] = cleaned_desc

        # Re-detect language using title + first 500 chars of description
        r["detected_lang_fresh"] = JobEnricher.detect_language(cleaned_title, cleaned_desc)

        cleaned_records.append(r)

    # -----------------------------------------------------------------------
    # Print cleaning report
    # -----------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("  DESCRIPTION CLEANING REPORT")
    print("=" * 64)
    print(f"  Total records:       {len(cleaned_records)}")
    print(f"  ftfy available:      {'yes' if _HAS_FTFY else 'no (regex latin-1 fallback used)'}")
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
    non_english = [r for r in cleaned_records if r["detected_lang_fresh"] != "english"]
    print("\n" + "=" * 64)
    print("  NON-ENGLISH ROWS (excluded from training file, kept in bookkeeping)")
    print("=" * 64)
    if non_english:
        for r in non_english:
            print(
                f"  job_id={r['job_id']}  lang={r['detected_lang_fresh']!r:10s}"
                f"  label={r['label']!r:10s}  title={str(r.get('title',''))[:50]!r}"
            )
    else:
        print("  None found.")

    # -----------------------------------------------------------------------
    # Write bookkeeping file (All records, including non-English)
    # -----------------------------------------------------------------------
    has_notes = 0
    has_rating = 0
    has_source = 0

    with open(bookkeeping_path, "w", encoding="utf-8") as f:
        for r in cleaned_records:
            rating, _src = _extract_meta_fields(r.get("metadata"))
            notes = r.get("notes")
            source = r.get("source")

            if notes and str(notes).strip():
                has_notes += 1
            if rating is not None and str(rating).strip() != "":
                has_rating += 1
            if source and str(source).strip():
                has_source += 1

            record = {
                "job_id":                  str(r["job_id"]),
                "title":                   r.get("title_clean") or r.get("title"),
                "company":                 r.get("company_name"),
                "source":                  source,
                "label":                   r["label"],
                "rating":                  rating,
                "notes":                   notes,
                "label_guideline_version": r.get("label_guideline_version"),
                "description_clean":       r["description_clean"],
            }
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    logger.info("Bookkeeping file written: %s (%d records)", bookkeeping_path, len(cleaned_records))

    # -----------------------------------------------------------------------
    # Write training file (English only! Non-English excluded)
    # -----------------------------------------------------------------------
    training_records = [r for r in cleaned_records if r["detected_lang_fresh"] == "english"]
    training_label_counts: dict[str, int] = {}

    with open(training_path, "w", encoding="utf-8") as f:
        for r in training_records:
            label = r["label"]
            training_label_counts[label] = training_label_counts.get(label, 0) + 1
            title = (r.get("title_clean") or "").strip()
            text = f"TITLE: {title}\n\n{r['description_clean']}" if title else r["description_clean"]
            record = {
                "job_id":       str(r["job_id"]),
                "text":         text,
                "label":        label,
                "is_synthetic": False,
            }
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    logger.info("Training file written: %s (%d records; %d non-English excluded)",
                training_path, len(training_records), len(non_english))

    # -----------------------------------------------------------------------
    # Join check: old JSONL vs jobs table
    # -----------------------------------------------------------------------
    old_jsonl = PROJECT_ROOT / "data" / "labeled_job_descriptions.jsonl"
    if old_jsonl.exists():
        import hashlib
        db_hashes: dict[str, str] = {}
        hash_rows = execute_query("SELECT id, description_text FROM jobs WHERE description_text IS NOT NULL;")
        for hr in hash_rows:
            # Note: The old export hashed raw jobs.description_text before any cleaning
            h = hashlib.md5((hr["description_text"] or "").strip().encode("utf-8")).hexdigest()
            db_hashes[h] = str(hr["id"])

        matched = unmatched = 0
        unmatched_labels: list[str] = []
        with open(old_jsonl, encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                desc = (obj.get("description") or "").strip()
                h = hashlib.md5(desc.encode("utf-8")).hexdigest()
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
        print("  Explanation: Old JSONL was generated directly from uncleaned")
        print("  raw jobs.description_text, matching DB raw text MD5 exactly.")
    else:
        print("\n  (old labeled_job_descriptions.jsonl not found — skipping join check)")

    # -----------------------------------------------------------------------
    # Final summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("  EXPORT COMPLETE")
    print("=" * 64)
    print(f"  Bookkeeping:        {bookkeeping_path} ({len(cleaned_records)} rows)")
    print(f"    - non-empty notes:  {has_notes}")
    print(f"    - non-empty rating: {has_rating}")
    print(f"    - non-empty source: {has_source}")
    print(f"  Training (English): {training_path} ({len(training_records)} rows; {len(non_english)} non-English excluded)")
    print("  Training Label breakdown:")
    for lbl, cnt in sorted(training_label_counts.items(), key=lambda x: -x[1]):
        print(f"    {lbl:<12}: {cnt:3}  ({cnt/len(training_records)*100:.1f}%)")
    print("=" * 64 + "\n")


if __name__ == "__main__":
    export()
