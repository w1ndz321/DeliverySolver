"""Expected-cost objective and diagnostic decomposition."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

from .parser import Candidate, Problem, Solution, canonical_task_key


@dataclass(frozen=True)
class BundleScore:
    accepted_cost: float
    rejection_risk_cost: float
    total: float
    reject_probability: float


@dataclass(frozen=True)
class ScoreBreakdown:
    total_score: float
    uncovered_penalty: float
    selected_expected_cost: float
    rejection_risk_cost: float
    high_cost_bundle_count: int
    low_gain_selected_count: int

    def to_dict(self) -> dict:
        return asdict(self)


def expected_bundle_cost(task_key: tuple[str, ...], candidates: Sequence[Candidate]) -> BundleScore:
    """Mirror the local official-style evaluator for one selected task bundle."""
    penalty = 100.0 * len(task_key)
    reject_probability = 1.0
    weighted_score = 0.0
    willingness_sum = 0.0
    for candidate in candidates:
        willingness = min(1.0, max(0.0, candidate.willingness))
        reject_probability *= 1.0 - willingness
        weighted_score += willingness * candidate.total_score
        willingness_sum += willingness
    if willingness_sum <= 0.0:
        return BundleScore(0.0, penalty, penalty, 1.0)
    accept_probability = 1.0 - reject_probability
    accepted_score = weighted_score / willingness_sum
    accepted_cost = accept_probability * accepted_score
    risk_cost = reject_probability * penalty
    return BundleScore(accepted_cost, risk_cost, accepted_cost + risk_cost, reject_probability)


def score_solution(solution: Solution, problem: Problem) -> ScoreBreakdown:
    """Score a legal solution; legality is handled by ``validator``."""
    covered_tasks: set[str] = set()
    selected_expected_cost = 0.0
    rejection_risk_cost = 0.0
    high_cost_bundle_count = 0
    low_gain_selected_count = 0
    for task_str, courier_ids in solution:
        task_key = canonical_task_key(task_str)
        candidates = [problem.candidate_map[(task_key, courier_id)] for courier_id in courier_ids]
        bundle = expected_bundle_cost(task_key, candidates)
        baseline_penalty = 100.0 * len(task_key)
        selected_expected_cost += bundle.accepted_cost
        rejection_risk_cost += bundle.rejection_risk_cost
        if bundle.total >= baseline_penalty:
            high_cost_bundle_count += 1
        if baseline_penalty - bundle.total <= 1e-9:
            low_gain_selected_count += 1
        covered_tasks.update(task_key)
    uncovered_penalty = 100.0 * len(problem.task_ids - covered_tasks)
    total = selected_expected_cost + rejection_risk_cost + uncovered_penalty
    return ScoreBreakdown(
        total_score=total,
        uncovered_penalty=uncovered_penalty,
        selected_expected_cost=selected_expected_cost,
        rejection_risk_cost=rejection_risk_cost,
        high_cost_bundle_count=high_cost_bundle_count,
        low_gain_selected_count=low_gain_selected_count,
    )
