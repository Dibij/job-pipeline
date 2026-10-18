"""Company-stratified train/val/test split for labeled training data.

Splits data/labeled_jobs_training.jsonl so that:
  - Every job from the same company always lands in the same split.
  - Split ratios are approximately 70 / 15 / 15.
  - Seed is fixed (42) for reproducibility.
  - Class counts are reported per split.
  - A warning is raised if any split has fewer than 5 good_fit rows.

Output files (also gitignored, in data/):
  data/splits/train.jsonl
  data/splits/val.jsonl
  data/splits/test.jsonl
"""
import json
import logging
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TRAINING_PATH = PROJECT_ROOT / "data" / "labeled_jobs_training.jsonl"
SPLITS_DIR    = PROJECT_ROOT / "data" / "splits"

TRAIN_RATIO = 0.70
VAL_RATIO   = 0.15
# TEST_RATIO is the remainder

SEED = 42
MIN_GOOD_FIT = 5  # warn if any split has fewer than this many good_fit rows


def load_training_data(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"Training file not found: {path}\n"
            "Run scripts/export_labeled_descriptions.py first."
        )
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _company_key(record: dict) -> str:
    """Return a normalized company key; fall back to 'unknown' if missing."""
    return (record.get("company") or "unknown").strip().lower()


def make_splits(
    training_path: Path = TRAINING_PATH,
    splits_dir: Path = SPLITS_DIR,
    seed: int = SEED,
) -> None:
    records = load_training_data(training_path)
    logger.info("Loaded %d records from %s", len(records), training_path)

    # We need company info — the training file has job_id + text + label.
    # We attach it from the bookkeeping file if present.
    bookkeeping_path = training_path.parent / "labeled_jobs_bookkeeping.jsonl"
    job_id_to_company: dict[int, str] = {}
    if bookkeeping_path.exists():
        with open(bookkeeping_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    jid = obj.get("job_id")
                    if jid is not None:
                        job_id_to_company[str(jid)] = (obj.get("company") or "unknown").strip().lower()
        logger.info("Loaded company map for %d jobs from bookkeeping file", len(job_id_to_company))
    else:
        logger.warning("Bookkeeping file not found; all jobs treated as company='unknown'")

    # Group job_ids by company
    company_to_records: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        jid = r.get("job_id")
        company = job_id_to_company.get(str(jid), "unknown") if jid is not None else "unknown"
        r["_company"] = company
        company_to_records[company].append(r)

    companies = list(company_to_records.keys())
    rng = random.Random(seed)
    rng.shuffle(companies)

    total = len(records)
    train_target = int(total * TRAIN_RATIO)
    val_target   = int(total * VAL_RATIO)

    train_records: list[dict] = []
    val_records:   list[dict] = []
    test_records:  list[dict] = []

    for company in companies:
        company_jobs = company_to_records[company]
        if len(train_records) < train_target:
            train_records.extend(company_jobs)
        elif len(val_records) < val_target:
            val_records.extend(company_jobs)
        else:
            test_records.extend(company_jobs)

    # Strip the internal _company key before writing
    def _strip(records: list[dict]) -> list[dict]:
        return [{k: v for k, v in r.items() if k != "_company"} for r in records]

    train_clean = _strip(train_records)
    val_clean   = _strip(val_records)
    test_clean  = _strip(test_records)

    splits_dir.mkdir(parents=True, exist_ok=True)
    for name, split in [("train", train_clean), ("val", val_clean), ("test", test_clean)]:
        path = splits_dir / f"{name}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for r in split:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        logger.info("Wrote %s: %s records → %s", name, len(split), path)

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------
    print("\n" + "=" * 64)
    print("  SPLIT REPORT  (seed=%d, company-stratified)" % seed)
    print("=" * 64)
    all_labels = sorted({r["label"] for r in records})
    header = f"  {'split':<8} {'total':>6}  " + "  ".join(f"{lbl:>10}" for lbl in all_labels)
    print(header)
    print("  " + "-" * (len(header) - 2))

    warnings: list[str] = []
    for name, split in [("train", train_clean), ("val", val_clean), ("test", test_clean)]:
        counts = Counter(r["label"] for r in split)
        row = f"  {name:<8} {len(split):>6}  " + "  ".join(f"{counts.get(lbl, 0):>10}" for lbl in all_labels)
        print(row)
        gf = counts.get("good_fit", 0)
        if gf < MIN_GOOD_FIT:
            warnings.append(f"  WARNING: '{name}' split has only {gf} good_fit rows (minimum {MIN_GOOD_FIT}). "
                            f"Do not report metrics from it.")

    print(f"\n  Companies assigned: {len(companies)}")
    print(f"  Unique companies in train: {len({r['_company'] for r in train_records})}")
    print(f"  Unique companies in val:   {len({r['_company'] for r in val_records})}")
    print(f"  Unique companies in test:  {len({r['_company'] for r in test_records})}")

    if warnings:
        print()
        for w in warnings:
            print(w)
        logger.warning("Some splits are too small for reliable metrics — see warnings above.")
    else:
        print("\n  All splits meet the minimum good_fit threshold.")

    print("=" * 64 + "\n")


if __name__ == "__main__":
    make_splits()
