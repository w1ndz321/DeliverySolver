"""Construction that protects orders with few candidate opportunities."""

from __future__ import annotations

from solver.parser import Problem, Solution

from .common import construct


def solve(
    problem: Problem, config: dict | None = None, deadline: float | None = None, seed: int = 0
) -> Solution:
    config = config or {}
    scarcity_weight = float(config.get("scarcity_weight", 1.0))

    def priority(candidate):
        scarcity = sum(len(problem.candidates_by_task[task]) for task in candidate.task_key)
        scarcity /= max(1, candidate.task_count)
        normalized_cost = candidate.expected_cost / max(1, candidate.task_count)
        return (scarcity * scarcity_weight, normalized_cost, -candidate.task_count, candidate.courier_id)

    return construct(problem, priority, deadline)
