"""GroupKFold cross-validation split by company (5 folds, seed 42).

Splits data/labeled_jobs_training.jsonl into 5 folds such that:
  - Every job from the same company is strictly assigned to one fold.
  - No company appears in both the train and validation sets of any fold.
  - Class counts and good_fit counts are verified per fold.
  - Refuses to report evaluation metrics if any fold has fewer than 5 good_fit cases.

Output directory:
  data/splits/
    fold_0_train.jsonl, fold_0_val.jsonl
    ...
    fold_4_train.jsonl, fold_4_val.jsonl
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
BOOKKEEPING_PATH = PROJECT_ROOT / "data" / "labeled_jobs_bookkeeping.jsonl"
SPLITS_DIR    = PROJECT_ROOT / "data" / "splits"

N_SPLITS = 5
SEED = 42
MIN_GOOD_FIT_REQUIRED = 5


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


def load_company_map(bookkeeping_path: Path) -> dict[str, str]:
    job_id_to_company: dict[str, str] = {}
    if bookkeeping_path.exists():
        with open(bookkeeping_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    jid = obj.get("job_id")
                    if jid is not None:
                        company = (obj.get("company") or "unknown").strip().lower()
                        job_id_to_company[str(jid)] = company
    return job_id_to_company


def make_group_kfold_splits(
    training_path: Path = TRAINING_PATH,
    bookkeeping_path: Path = BOOKKEEPING_PATH,
    splits_dir: Path = SPLITS_DIR,
    n_splits: int = N_SPLITS,
    seed: int = SEED,
) -> None:
    records = load_training_data(training_path)
    logger.info("Loaded %d training records from %s", len(records), training_path)

    job_id_to_company = load_company_map(bookkeeping_path)

    # Group records by company
    company_groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        jid = str(r.get("job_id"))
        comp = job_id_to_company.get(jid, "unknown")
        r["_company"] = comp
        company_groups[comp].append(r)

    companies = list(company_groups.keys())
    # Deterministic shuffle by seed
    rng = random.Random(seed)
    rng.shuffle(companies)

    # Distribute companies to folds with greedy load-balancing
    fold_companies: list[list[str]] = [[] for _ in range(n_splits)]
    fold_sample_counts: list[int] = [0] * n_splits

    # Sort companies by number of jobs descending for better balance
    companies_by_size = sorted(companies, key=lambda c: len(company_groups[c]), reverse=True)
    for c in companies_by_size:
        # Assign to fold with smallest sample count
        min_fold = min(range(n_splits), key=lambda i: fold_sample_counts[i])
        fold_companies[min_fold].append(c)
        fold_sample_counts[min_fold] += len(company_groups[c])

    splits_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 68)
    print(f"  GROUP K-FOLD SPLIT REPORT  (5 Folds, Grouped by Company, seed={seed})")
    print("=" * 68)
    header = f"  {'Fold':<6} {'Val Total':>9} {'bad_fit':>9} {'maybe':>7} {'good_fit':>10}  {'Companies':>10}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    has_insufficient_good_fit = False
    fold_stats = []

    for fold_idx in range(n_splits):
        val_comps = set(fold_companies[fold_idx])
        val_records = [r for c in val_comps for r in company_groups[c]]
        train_records = [
            r for c, group in company_groups.items() if c not in val_comps for r in group
        ]

        def _strip(recs: list[dict]) -> list[dict]:
            return [{k: v for k, v in r.items() if k != "_company"} for r in recs]

        val_clean = _strip(val_records)
        train_clean = _strip(train_records)

        # Write files
        val_path = splits_dir / f"fold_{fold_idx}_val.jsonl"
        train_path = splits_dir / f"fold_{fold_idx}_train.jsonl"
        with open(val_path, "w", encoding="utf-8") as f:
            for r in val_clean:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        with open(train_path, "w", encoding="utf-8") as f:
            for r in train_clean:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

        # Counts
        val_counts = Counter(r["label"] for r in val_clean)
        gf_count = val_counts.get("good_fit", 0)
        mb_count = val_counts.get("maybe", 0)
        bf_count = val_counts.get("bad_fit", 0)

        fold_stats.append((fold_idx, len(val_clean), bf_count, mb_count, gf_count, len(val_comps)))
        print(f"  {fold_idx:<6} {len(val_clean):>9} {bf_count:>9} {mb_count:>7} {gf_count:>10}  {len(val_comps):>10}")

        if gf_count < MIN_GOOD_FIT_REQUIRED:
            has_insufficient_good_fit = True

    print("=" * 68)

    print("\n[GOOD_FIT COUNTS PER FOLD]")
    for f_idx, tot, bf, mb, gf, n_c in fold_stats:
        status = "INSUFFICIENT (< 5)" if gf < MIN_GOOD_FIT_REQUIRED else "OK (>= 5)"
        print(f"  Fold {f_idx}: {gf} good_fit rows ({status})")

    if has_insufficient_good_fit:
        print("\n" + "!" * 68)
        print("  [REFUSAL] REFUSING TO PRINT EVALUATION METRICS")
        print("!" * 68)
        print(f"  Reason: One or more folds have fewer than {MIN_GOOD_FIT_REQUIRED} 'good_fit' validation rows.")
        print("  Evaluating model accuracy/F1 on folds with < 5 positive targets is")
        print("  statistically unreliable and produces noisy/misleading metrics.")
        print("  Metrics reporting is BLOCKED until more good_fit labels are acquired.")
        print("!" * 68 + "\n")
    else:
        print("\nAll folds have at least 5 good_fit examples. Metrics may be computed.\n")


if __name__ == "__main__":
    make_group_kfold_splits()
