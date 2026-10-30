"""Model registry for evaluation harness.

Provides a unified interface to evaluate any scorer:
- title_keyword_rule: Pure rule-based title keyword matcher
- char_ngram_title_clf: Learned char n-gram TF-IDF + LogisticRegression on title
- tfidf_lr: Text TF-IDF (title + snippet) + LogisticRegression
- match_scorer: Full rule-based MatchScorer from src/matching/scorer.py
- laya: Stored/Inference Laya score
- ollama_triage: LLM triage suggestion score
- composite_rule_title: Ensemble of keyword rules + char n-gram classifier
- composite_match_title: Ensemble of MatchScorer + char n-gram classifier
"""
from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional
import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class BaseScorer:
    """Standard evaluation interface for all scoring models."""

    name: str = "base"
    version: str = "1.0"
    is_trainable: bool = False

    def fit(self, train_jobs: List[Dict[str, Any]], y_train: np.ndarray) -> None:
        """Fit model on training fold if trainable."""
        pass

    def score_jobs(self, jobs: List[Dict[str, Any]]) -> np.ndarray:
        """Compute continuous float scores in range [0.0, 1.0]."""
        raise NotImplementedError


# ----------------------------------------------------------------------
# 1. Title Keyword Rule Scorer
# ----------------------------------------------------------------------
class TitleKeywordRuleScorer(BaseScorer):
    """Rule-based title keyword scorer with word-boundary awareness."""

    name = "title_keyword_rule"
    version = "1.0"
    is_trainable = False

    POS_TOKENS = [
        r"\b(?:software|engineer|developer|programmer)\b",
        r"\b(?:full[- ]?stack|backend|front[- ]?end|web)\b",
        r"\b(?:python|django|fastapi|react|next\.?js|node)\b",
        r"\b(?:data\s+engineer|ai|ml|machine\s+learning)\b",
    ]
    NEG_TOKENS = [
        r"\b(?:senior|sr\.?|lead|staff|principal|director|head\s+of|vp|manager)\b",
        r"\b(?:sales|recruiter|recruiting|marketing|account\s+executive)\b",
        r"\b(?:copywriter|nurse|paralegal|receptionist|fitness)\b",
        r"\b(?:intern|internship|unpaid)\b",
    ]

    def __init__(self) -> None:
        self.pos_res = [re.compile(pat, re.IGNORECASE) for pat in self.POS_TOKENS]
        self.neg_res = [re.compile(pat, re.IGNORECASE) for pat in self.NEG_TOKENS]

    def score_jobs(self, jobs: List[Dict[str, Any]]) -> np.ndarray:
        scores = []
        for j in jobs:
            title = j.get("title") or ""
            pos_matches = sum(1 for r in self.pos_res if r.search(title))
            neg_matches = sum(1 for r in self.neg_res if r.search(title))
            raw = 0.5 + (0.25 * pos_matches) - (0.4 * neg_matches)
            score = max(0.0, min(1.0, raw))
            scores.append(score)
        return np.array(scores, dtype=float)


# ----------------------------------------------------------------------
# 2. Char N-gram Title Classifier Scorer
# ----------------------------------------------------------------------
class CharNgramTitleClassifierScorer(BaseScorer):
    """Learned char n-gram title classifier."""

    name = "char_ngram_title_clf"
    version = "1.0"
    is_trainable = True

    def __init__(self, model_path: Optional[Path] = None) -> None:
        self.model_path = model_path or (PROJECT_ROOT / "models" / "title_classifier.joblib")
        self.pipeline: Optional[Any] = None
        if self.model_path.exists():
            try:
                self.pipeline = joblib.load(self.model_path)
            except Exception as exc:
                logger.warning("Could not load title classifier from %s: %s", self.model_path, exc)

    def fit(self, train_jobs: List[Dict[str, Any]], y_train: np.ndarray) -> None:
        """Fit char n-gram model strictly on fold's training set."""
        titles = [j.get("title") or "" for j in train_jobs]
        if len(titles) < 10 or len(np.unique(y_train)) < 2:
            return

        from sklearn.pipeline import Pipeline
        pipe = Pipeline([
            ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2)),
            ("clf", LogisticRegression(C=1.0, max_iter=200, class_weight="balanced")),
        ])
        pipe.fit(titles, y_train)
        self.pipeline = pipe

    def score_jobs(self, jobs: List[Dict[str, Any]]) -> np.ndarray:
        titles = [j.get("title") or "" for j in jobs]
        if self.pipeline is not None:
            try:
                probs = self.pipeline.predict_proba(titles)
                # Class 1 probability
                if probs.shape[1] >= 2:
                    return probs[:, 1]
                return probs[:, 0]
            except Exception as exc:
                logger.warning("Error predicting with title classifier: %s", exc)
        # Fallback to neutral 0.5
        return np.full(len(jobs), 0.5, dtype=float)


# ----------------------------------------------------------------------
# 3. TF-IDF + Logistic Regression (Title + Snippet)
# ----------------------------------------------------------------------
class TfidfLRScorer(BaseScorer):
    """TF-IDF word n-gram + Logistic Regression on title and description snippet."""

    name = "tfidf_lr"
    version = "1.0"
    is_trainable = True

    def __init__(self) -> None:
        self.pipeline: Optional[Any] = None

    def fit(self, train_jobs: List[Dict[str, Any]], y_train: np.ndarray) -> None:
        texts = [f"{j.get('title', '')} {j.get('description_snippet', '')}" for j in train_jobs]
        if len(texts) < 10 or len(np.unique(y_train)) < 2:
            return

        from sklearn.pipeline import Pipeline
        pipe = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, stop_words="english", max_features=1000)),
            ("clf", LogisticRegression(C=0.8, max_iter=200, class_weight="balanced")),
        ])
        pipe.fit(texts, y_train)
        self.pipeline = pipe

    def score_jobs(self, jobs: List[Dict[str, Any]]) -> np.ndarray:
        texts = [f"{j.get('title', '')} {j.get('description_snippet', '')}" for j in jobs]
        if self.pipeline is not None:
            try:
                probs = self.pipeline.predict_proba(texts)
                if probs.shape[1] >= 2:
                    return probs[:, 1]
                return probs[:, 0]
            except Exception:
                pass
        return np.full(len(jobs), 0.5, dtype=float)


# ----------------------------------------------------------------------
# 4. MatchScorer Wrapper
# ----------------------------------------------------------------------
class MatchScorerWrapper(BaseScorer):
    """Full CV MatchScorer from src/matching/scorer.py."""

    name = "match_scorer"
    version = "1.0"
    is_trainable = False

    def __init__(self) -> None:
        from src.matching.scorer import MatchScorer
        self.scorer = MatchScorer()

    def score_jobs(self, jobs: List[Dict[str, Any]]) -> np.ndarray:
        scores = []
        for j in jobs:
            job_dict = {
                "title": j.get("title") or "",
                "company_name": j.get("company") or "",
                "description_text": j.get("description_snippet") or "",
                "is_remote": True,
                "location_raw": "Worldwide",
                "remote_restriction": "",
            }
            try:
                res = self.scorer.score_job(job_dict)
                final_score = res[0] if isinstance(res, tuple) else float(res)
                norm = max(0.0, min(1.0, final_score / 100.0))
                scores.append(norm)
            except Exception as exc:
                logger.debug("MatchScorer error on job %s: %s", j.get("job_id"), exc)
                scores.append(0.3)
        return np.array(scores, dtype=float)


# ----------------------------------------------------------------------
# 5. Laya Scorer
# ----------------------------------------------------------------------
class LayaScorer(BaseScorer):
    """Laya confidence scorer using stored scores or inference."""

    name = "laya"
    version = "1.0"
    is_trainable = False

    def score_jobs(self, jobs: List[Dict[str, Any]]) -> np.ndarray:
        # Check if jobs dict contains precomputed laya score
        scores = []
        for j in jobs:
            val = j.get("laya_score")
            if val is not None:
                try:
                    scores.append(float(val) / 100.0 if float(val) > 1.0 else float(val))
                    continue
                except ValueError:
                    pass
            # Default neutral score
            scores.append(0.5)
        return np.array(scores, dtype=float)


# ----------------------------------------------------------------------
# 6. Ollama Triage Scorer
# ----------------------------------------------------------------------
class OllamaTriageScorer(BaseScorer):
    """Ollama qwen2.5:3b triage suggestion scorer."""

    name = "ollama_triage"
    version = "1.0"
    is_trainable = False

    def score_jobs(self, jobs: List[Dict[str, Any]]) -> np.ndarray:
        # Check if pre-computed triage suggestion or label exists in job dict
        scores = []
        for j in jobs:
            triage_val = j.get("triage_label") or j.get("ollama_suggestion")
            if triage_val == "good_fit":
                scores.append(0.9)
            elif triage_val == "maybe":
                scores.append(0.5)
            elif triage_val == "bad_fit":
                scores.append(0.1)
            else:
                scores.append(0.5)
        return np.array(scores, dtype=float)


# ----------------------------------------------------------------------
# 7. Composite Ensembles
# ----------------------------------------------------------------------
class CompositeRuleTitleScorer(BaseScorer):
    """Ensemble: 0.5 * title_keyword_rule + 0.5 * char_ngram_title_clf."""

    name = "composite_rule_title"
    version = "1.0"
    is_trainable = True

    def __init__(self) -> None:
        self.rule_scorer = TitleKeywordRuleScorer()
        self.clf_scorer = CharNgramTitleClassifierScorer()

    def fit(self, train_jobs: List[Dict[str, Any]], y_train: np.ndarray) -> None:
        self.clf_scorer.fit(train_jobs, y_train)

    def score_jobs(self, jobs: List[Dict[str, Any]]) -> np.ndarray:
        s_rule = self.rule_scorer.score_jobs(jobs)
        s_clf = self.clf_scorer.score_jobs(jobs)
        return 0.5 * s_rule + 0.5 * s_clf


class CompositeMatchTitleScorer(BaseScorer):
    """Ensemble: 0.6 * match_scorer + 0.4 * char_ngram_title_clf."""

    name = "composite_match_title"
    version = "1.0"
    is_trainable = True

    def __init__(self) -> None:
        self.match_scorer = MatchScorerWrapper()
        self.clf_scorer = CharNgramTitleClassifierScorer()

    def fit(self, train_jobs: List[Dict[str, Any]], y_train: np.ndarray) -> None:
        self.clf_scorer.fit(train_jobs, y_train)

    def score_jobs(self, jobs: List[Dict[str, Any]]) -> np.ndarray:
        s_match = self.match_scorer.score_jobs(jobs)
        s_clf = self.clf_scorer.score_jobs(jobs)
        return 0.6 * s_match + 0.4 * s_clf


# ----------------------------------------------------------------------
# Model Registry Container
# ----------------------------------------------------------------------
MODEL_REGISTRY: Dict[str, Callable[[], BaseScorer]] = {
    "title_keyword_rule": TitleKeywordRuleScorer,
    "char_ngram_title_clf": CharNgramTitleClassifierScorer,
    "tfidf_lr": TfidfLRScorer,
    "match_scorer": MatchScorerWrapper,
    "laya": LayaScorer,
    "ollama_triage": OllamaTriageScorer,
    "composite_rule_title": CompositeRuleTitleScorer,
    "composite_match_title": CompositeMatchTitleScorer,
}


def get_model(name: str) -> BaseScorer:
    """Instantiate a registered model by name."""
    if name not in MODEL_REGISTRY:
        raise ValueError(f"Unknown model '{name}'. Available models: {list(MODEL_REGISTRY.keys())}")
    return MODEL_REGISTRY[name]()


def list_registered_models() -> List[str]:
    """List names of all registered evaluation models."""
    return sorted(list(MODEL_REGISTRY.keys()))
