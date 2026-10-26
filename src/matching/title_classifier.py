"""Learned title role-type classifier (Step 3).

Trains a char n-gram TF-IDF + LogisticRegression model on human labels and weak supervision
to classify titles as technical (1) vs non-technical (0).
Provides soft penalty scores instead of hard keyword blocklists.
"""
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODEL_PATH = PROJECT_ROOT / "models" / "title_classifier.joblib"

logger = logging.getLogger(__name__)

_TECH_RE = re.compile(
    r"\b(engineer|developer|software|programmer|fullstack|full-stack|backend|frontend|"
    r"data scientist|machine learning|python|ai|ml|architect|devops|sre|cloud|systems)\b",
    re.IGNORECASE,
)
_NON_TECH_RE = re.compile(
    r"\b(sales|account executive|marketing|recruiter|recruiting|copywriter|content editor|"
    r"paralegal|payroll|fitness|receptionist|nurse|phlebotomy|legal|counsel|brand ambassador|"
    r"admissions|booking|customer success manager|sales representative|appointment setter)\b",
    re.IGNORECASE,
)

_GLOBAL_MODEL: Optional[Pipeline] = None


def build_training_dataset() -> Tuple[List[str], List[str], List[int], List[bool], List[Optional[str]]]:
    """Gather title dataset from PostgreSQL for weak supervision and human evaluations."""
    from src.db.connection import execute_query
    from src.matching.hard_filter import _check_non_technical

    db_jobs = execute_query(
        """
        SELECT id, title, company_name
        FROM jobs
        WHERE exclude_reason IS NULL AND title IS NOT NULL;
        """
    )

    labeled_jobs = execute_query(
        """
        SELECT DISTINCT ON (j.id) j.id, l.label, j.title, j.company_name
        FROM laya_labels l
        JOIN jobs j ON l.job_id = j.id
        WHERE j.exclude_reason IS NULL
        ORDER BY j.id, l.labeled_at DESC NULLS LAST;
        """
    )
    labeled_dict = {str(r["id"]): (r["label"], r["title"], r["company_name"]) for r in labeled_jobs}

    titles: List[str] = []
    companies: List[str] = []
    labels: List[int] = []
    is_eval: List[bool] = []
    eval_user_labels: List[Optional[str]] = []

    for j in db_jobs:
        jid = str(j["id"])
        title = (j.get("title") or "").strip()
        comp = (j.get("company_name") or "unknown").strip()
        if not title:
            continue

        if jid in labeled_dict:
            user_lbl, _, _ = labeled_dict[jid]
            if user_lbl in ("good_fit", "maybe"):
                titles.append(title)
                companies.append(comp)
                labels.append(1)
                is_eval.append(True)
                eval_user_labels.append(user_lbl)
            elif user_lbl == "bad_fit":
                is_blocklist = not _check_non_technical(title).passed
                is_non_tech = bool(_NON_TECH_RE.search(title))
                if is_blocklist or is_non_tech:
                    titles.append(title)
                    companies.append(comp)
                    labels.append(0)
                    is_eval.append(True)
                    eval_user_labels.append(user_lbl)
                elif _TECH_RE.search(title):
                    titles.append(title)
                    companies.append(comp)
                    labels.append(1)
                    is_eval.append(True)
                    eval_user_labels.append(user_lbl)
        else:
            if not _check_non_technical(title).passed or _NON_TECH_RE.search(title):
                titles.append(title)
                companies.append(comp)
                labels.append(0)
                is_eval.append(False)
                eval_user_labels.append(None)
            elif _TECH_RE.search(title):
                titles.append(title)
                companies.append(comp)
                labels.append(1)
                is_eval.append(False)
                eval_user_labels.append(None)

    return titles, companies, labels, is_eval, eval_user_labels


def create_pipeline() -> Pipeline:
    """Create char n-gram TF-IDF + LogisticRegression pipeline."""
    return Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)),
        ("clf", LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced", random_state=42)),
    ])


def train_and_save_model(output_path: Path = MODEL_PATH) -> Pipeline:
    """Train title role-type classifier on all available weak + human labeled data."""
    titles, _, labels, _, _ = build_training_dataset()
    logger.info("Training title classifier on %d titles (%d tech, %d non-tech)...",
                len(titles), sum(labels), len(labels) - sum(labels))

    pipe = create_pipeline()
    pipe.fit(titles, labels)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, output_path)
    logger.info("Saved title classifier to %s", output_path)

    global _GLOBAL_MODEL
    _GLOBAL_MODEL = pipe
    return pipe


def get_title_classifier() -> Pipeline:
    """Load cached model or train fresh if not yet saved."""
    global _GLOBAL_MODEL
    if _GLOBAL_MODEL is not None:
        return _GLOBAL_MODEL

    if MODEL_PATH.exists():
        try:
            _GLOBAL_MODEL = joblib.load(MODEL_PATH)
            return _GLOBAL_MODEL
        except Exception as e:
            logger.warning("Could not load cached title model from %s (%s). Retraining...", MODEL_PATH, e)

    return train_and_save_model(MODEL_PATH)


def predict_tech_probability(title: str) -> float:
    """Predict probability in [0.0, 1.0] that title is a technical/engineering role."""
    t = (title or "").strip()
    if not t:
        return 0.5
    pipe = get_title_classifier()
    try:
        prob_tech = float(pipe.predict_proba([t])[0, 1])
        return round(prob_tech, 4)
    except Exception as e:
        logger.error("Error predicting tech probability for %r: %s", title, e)
        return 0.5


def get_title_role_penalty(title: str) -> float:
    """Compute soft score penalty for non-technical titles (design principle: soft signal, not hard reject).

    Returns a penalty between 0.0 and 25.0 points depending on non-tech confidence.
    """
    prob_tech = predict_tech_probability(title)
    # If prob_tech >= 0.50: 0 penalty
    # If prob_tech < 0.50: scales smoothly up to 25.0 pts penalty
    if prob_tech >= 0.50:
        return 0.0
    return round(25.0 * (0.50 - prob_tech) / 0.50, 2)
