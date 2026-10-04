"""Laya Decision Model Scoring Module (Task 7.4).

Executes typed questions against a truncated JD state using Convai Innovations' Laya model.
Loads all question schemas, weights, penalties, and reason codes from config/laya_questions.yaml.
"""
from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

import laya
from src.matching.jd_extractor import JDSections, extract_sections
from src.matching.jd_truncator import build_truncated_laya_state

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "laya_questions.yaml"


@dataclass
class LayaQuestionResult:
    question_type: str
    raw_value: Any
    normalized_value: float
    confidence: float
    answer_confidence: float
    probabilities: Dict[str, float] = field(default_factory=dict)


@dataclass
class LayaScoreResult:
    job_id: Optional[str]
    title: str
    company: str
    final_score: float
    is_passed: bool
    disqualification_reason: Optional[str]
    needs_review: bool
    role_type: str
    gate_warnings: List[str] = field(default_factory=list)
    questions: Dict[str, LayaQuestionResult] = field(default_factory=dict)
    tokens_used: int = 0


class LayaScorer:
    """Evaluates jobs using typed Laya questions from YAML configuration."""

    def __init__(self, config_path: Optional[Path] = None, device: str = "cpu"):
        self.config_path = config_path or CONFIG_PATH
        self.device = device
        self.config = self._load_config()
        self.confidence_threshold = self.config.get("confidence_threshold", 0.65)
        self.gates_warn_only = self.config.get("gates_warn_only", True)
        self.gate_disqualify_threshold = self.config.get("gate_disqualify_threshold", 0.90)
        # gate_warn_threshold: only surface a gate_warning when p_bad >= this value.
        # Raised from the old 0.50 floor so noisy zero-shot probabilities don't pollute
        # summaries before calibration. Raw probabilities are always stored.
        self.gate_warn_threshold = self.config.get("gate_warn_threshold", 0.85)
        # Task 7.5: flag is always COMPUTED but never used to filter/rank unless True.
        self.use_confidence_flag = self.config.get("use_confidence_flag", False)

        # Load Laya model
        logger.info("Loading Laya model on %s...", device)
        self.agent = laya.load("convaiinnovations/laya", device=device)
        self.formatted_questions = self._build_laya_questions()


    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Laya questions config not found at: {self.config_path}")
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _build_laya_questions(self) -> Dict[str, Any]:
        """Convert YAML configuration into Laya's internal question schema."""
        questions: Dict[str, Any] = {}

        # 1. Score questions (type: 'score')
        for q_id, q_cfg in self.config.get("score_questions", {}).items():
            questions[q_id] = {
                "type": "score",
                "instructions": q_cfg["instructions"],
                "criteria": q_cfg.get("criteria", [])
            }

        # 2. Gate questions (type: 'noul' / boolean)
        for q_id, q_cfg in self.config.get("gate_questions", {}).items():
            questions[q_id] = {
                "type": "noul",
                "instructions": q_cfg["instructions"]
            }

        # 3. Penalty questions (type: 'noul' / boolean)
        for q_id, q_cfg in self.config.get("penalty_questions", {}).items():
            questions[q_id] = {
                "type": "noul",
                "instructions": q_cfg["instructions"]
            }

        # 4. Choice questions (type: 'choice')
        for q_id, q_cfg in self.config.get("choice_questions", {}).items():
            questions[q_id] = {
                "type": "choice",
                "instructions": q_cfg["instructions"],
                "criteria": q_cfg.get("criteria", {})
            }

        return questions

    def _get_question_subsets(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Split questions into job-only (gates, penalties, role_type) and match questions.
        
        Job questions must be evaluated on pure job state without candidate summary
        to prevent candidate skills from biasing job classification.
        """
        score_keys = set(self.config.get("score_questions", {}).keys())
        match_questions = {k: v for k, v in self.formatted_questions.items() if k in score_keys}
        job_questions = {k: v for k, v in self.formatted_questions.items() if k not in score_keys}
        return job_questions, match_questions

    def score_job(
        self,
        job_dict: Dict[str, Any],
        cv_summary: Optional[str] = None
    ) -> LayaScoreResult:
        """Score a single job dictionary using Laya model."""
        title = job_dict.get("title", "")
        company = job_dict.get("company_name", "")
        location = job_dict.get("location_raw", "")
        desc = job_dict.get("description_text", "")
        job_id = str(job_dict.get("id", ""))

        # 1. Extract sections and truncate to budget
        sections = extract_sections(
            description_text=desc,
            title=title,
            company=company,
            location=location
        )
        state_match = build_truncated_laya_state(
            sections=sections,
            tokenizer=self.agent.tok,
            cv_summary=cv_summary
        )

        # 2. Run Laya inference
        job_questions, match_questions = self._get_question_subsets()
        if job_questions and match_questions:
            # Pure job state without candidate summary for role_type and gate questions
            state_job = {k: v for k, v in state_match.items() if k != "candidate_summary"}
            res_job = laya.decide(self.agent, state_job, questions=job_questions, return_details=True)
            res_match = laya.decide(self.agent, state_match, questions=match_questions, return_details=True)

            # Merge results into combined structure
            combined_values = {**getattr(res_job, "values", {}), **getattr(res_match, "values", {})}
            combined_confidence = {**getattr(res_job, "confidence", {}), **getattr(res_match, "confidence", {})}
            combined_probabilities = {**getattr(res_job, "probabilities", {}), **getattr(res_match, "probabilities", {})}
            combined_tokens = (getattr(res_job, "usage", {}).get("input_tokens", 0) or 0) + (getattr(res_match, "usage", {}).get("input_tokens", 0) or 0)

            class CombinedDecision:
                def __init__(self, values, confidence, probabilities, tokens):
                    self.values = values
                    self.confidence = confidence
                    self.probabilities = probabilities
                    self.usage = {"input_tokens": tokens}

            raw_result = CombinedDecision(combined_values, combined_confidence, combined_probabilities, combined_tokens)
        else:
            raw_result = laya.decide(
                self.agent,
                state_match,
                questions=self.formatted_questions,
                return_details=True
            )

        return self._evaluate_decision(job_id, title, company, raw_result)


    def _evaluate_decision(
        self,
        job_id: str,
        title: str,
        company: str,
        raw_result: Any
    ) -> LayaScoreResult:
        """Combine raw Laya typed answers into final score, gate status, and flags."""
        values = getattr(raw_result, "values", {})
        confidences = getattr(raw_result, "confidence", {})
        probabilities = getattr(raw_result, "probabilities", {})
        usage = getattr(raw_result, "usage", {})
        input_tokens = usage.get("input_tokens", 0)

        question_results: Dict[str, LayaQuestionResult] = {}
        needs_review = False

        # --- A. Gate Questions ---
        is_passed = True
        disqualification_reason = None
        gate_warnings: List[str] = []

        gate_configs = self.config.get("gate_questions", {})
        for q_id, q_cfg in gate_configs.items():
            ans = values.get(q_id, {})
            # noul is probability of 'true'
            noul_prob = ans.get("noul", 0.5) if isinstance(ans, dict) else 0.5
            conf = confidences.get(q_id, 0.0)
            answer_conf = ans.get("answer_confidence", conf) if isinstance(ans, dict) else conf
            probs = probabilities.get(q_id, {})

            if conf < self.confidence_threshold:
                needs_review = True

            # Determine boolean answer: true if noul_prob >= 0.5 else false
            bool_answer = (noul_prob >= 0.5)
            bad_answer = q_cfg.get("bad_answer", False)
            reason_code = q_cfg.get("reason_code", "DISQUALIFIED")

            # Probability of the bad condition:
            # If bad_answer is True: statement being True is bad -> p_bad = noul_prob
            # If bad_answer is False: statement being False is bad -> p_bad = 1.0 - noul_prob
            p_bad = float(noul_prob) if bad_answer else float(1.0 - noul_prob)

            # Warning threshold: only surface a warning when model is reasonably confident
            # the bad condition holds. Raw probability is always stored in question_results.
            if p_bad >= self.gate_warn_threshold:
                gate_warnings.append(f"{reason_code}:{q_id}(p_bad={p_bad:.2f})")

                # Disqualification threshold:
                # 1. Gates must not be in warn-only mode (gates_warn_only=False)
                # 2. Probability of bad must reach or exceed gate_disqualify_threshold (default 0.90)
                if not self.gates_warn_only and p_bad >= self.gate_disqualify_threshold:
                    is_passed = False
                    if not disqualification_reason:
                        disqualification_reason = reason_code


            question_results[q_id] = LayaQuestionResult(
                question_type="noul",
                raw_value=bool_answer,
                normalized_value=float(noul_prob),
                confidence=float(conf),
                answer_confidence=float(answer_conf),
                probabilities=probs
            )

        # --- B. Score Questions ---
        score_configs = self.config.get("score_questions", {})
        weighted_score_sum = 0.0
        total_weight = 0.0

        for q_id, q_cfg in score_configs.items():
            weight = q_cfg.get("weight", 0.25)
            ans = values.get(q_id, {})
            raw_score = ans.get("score", 0.0) if isinstance(ans, dict) else 0.0
            conf = confidences.get(q_id, 0.0)
            answer_conf = ans.get("answer_confidence", conf) if isinstance(ans, dict) else conf
            probs = probabilities.get(q_id, {})

            if conf < self.confidence_threshold:
                needs_review = True

            # Criteria length: 5 items (0 to 4) -> normalize to 0-100
            criteria_len = len(q_cfg.get("criteria", []))
            max_scale = max(1.0, float(criteria_len - 1))
            normalized_val = (float(raw_score) / max_scale) * 100.0

            weighted_score_sum += normalized_val * weight
            total_weight += weight

            question_results[q_id] = LayaQuestionResult(
                question_type="score",
                raw_value=float(raw_score),
                normalized_value=float(normalized_val),
                confidence=float(conf),
                answer_confidence=float(answer_conf),
                probabilities=probs
            )

        base_score = (weighted_score_sum / total_weight) if total_weight > 0 else 0.0

        # --- C. Penalty Questions ---
        total_penalties = 0.0
        penalty_configs = self.config.get("penalty_questions", {})
        for q_id, q_cfg in penalty_configs.items():
            ans = values.get(q_id, {})
            noul_prob = ans.get("noul", 0.0) if isinstance(ans, dict) else 0.0
            conf = confidences.get(q_id, 0.0)
            answer_conf = ans.get("answer_confidence", conf) if isinstance(ans, dict) else conf
            probs = probabilities.get(q_id, {})

            # If question indicates positive presence of penalty condition (e.g. fixed overlap hours)
            penalty_val = q_cfg.get("penalty", 0.0)
            if noul_prob > 0.5:
                total_penalties += abs(penalty_val)

            question_results[q_id] = LayaQuestionResult(
                question_type="noul",
                raw_value=(noul_prob >= 0.5),
                normalized_value=float(noul_prob),
                confidence=float(conf),
                answer_confidence=float(answer_conf),
                probabilities=probs
            )

        # --- D. Choice Questions (Role Type & Bonus) ---
        role_type = "other"
        role_bonus = 0.0
        choice_configs = self.config.get("choice_questions", {})
        for q_id, q_cfg in choice_configs.items():
            ans = values.get(q_id, {})
            chosen = ans.get("choice", "other") if isinstance(ans, dict) else "other"
            conf = confidences.get(q_id, 0.0)
            answer_conf = ans.get("answer_confidence", conf) if isinstance(ans, dict) else conf
            probs = probabilities.get(q_id, {})

            if q_id == "role_type":
                role_type = chosen
                bonuses = q_cfg.get("bonus", {})
                role_bonus = float(bonuses.get(chosen, 0.0))

            question_results[q_id] = LayaQuestionResult(
                question_type="choice",
                raw_value=chosen,
                normalized_value=role_bonus,
                confidence=float(conf),
                answer_confidence=float(answer_conf),
                probabilities=probs
            )

        # --- E. Final Calculation ---
        if not is_passed:
            final_score = 0.0
        else:
            final_score = max(0.0, min(100.0, base_score - total_penalties + role_bonus))

        return LayaScoreResult(
            job_id=job_id,
            title=title,
            company=company,
            final_score=round(final_score, 2),
            is_passed=is_passed,
            disqualification_reason=disqualification_reason,
            needs_review=needs_review,
            role_type=role_type,
            gate_warnings=gate_warnings,
            questions=question_results,
            tokens_used=input_tokens
        )
