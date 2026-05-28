"""Offline/online generated strategy for case type: pair_rich+low_willingness.

Rationale: offline ablation for pair_rich+low_willingness
"""

from __future__ import annotations

from solver.parser import Candidate, Problem, Solution
from solver.strategies.common import construct


DEFAULT_CONFIG = {'expected_weight': 1.0, 'gain_weight': 0.05, 'high_cost_penalty': 0.6, 'pair_bonus': 16.0, 'repair': True, 'scarcity_weight': 0.8, 'willingness_weight': 18.0}


def _task_scarcity(problem: Problem, candidate: Candidate) -> float:
    return sum(len(problem.candidates_by_task[task]) for task in candidate.task_key) / max(
        1, candidate.task_count
    )


def solve(
    problem: Problem, config: dict | None = None, deadline: float | None = None, seed: int = 0
) -> Solution:
    config = dict(DEFAULT_CONFIG, **(config or {}))
    expected_weight = float(config.get("expected_weight", 1.0))
    gain_weight = float(config.get("gain_weight", 0.0))
    scarcity_weight = float(config.get("scarcity_weight", 0.0))
    willingness_weight = float(config.get("willingness_weight", 0.0))
    pair_bonus = float(config.get("pair_bonus", 0.0))
    high_cost_penalty = float(config.get("high_cost_penalty", 0.0))
    repair = bool(config.get("repair", True))

    def priority(candidate: Candidate) -> tuple:
        task_count = max(1, candidate.task_count)
        expected = candidate.expected_cost / task_count
        scarcity = _task_scarcity(problem, candidate)
        high_cost = max(0.0, candidate.expected_cost - 100.0 * task_count) / task_count
        score = (
            expected_weight * expected
            - gain_weight * (candidate.gain / task_count)
            + scarcity_weight * scarcity
            - willingness_weight * candidate.willingness
            - pair_bonus * max(0, candidate.task_count - 1)
            + high_cost_penalty * high_cost
        )
        return (score, expected, -candidate.task_count, candidate.task_str, candidate.courier_id)

    return construct(problem, priority, deadline, repair=repair)
