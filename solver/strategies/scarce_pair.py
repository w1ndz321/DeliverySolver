"""Pair-aware strategy for constrained courier supply or bundle-rich inputs."""

from __future__ import annotations

from solver.parser import Problem, Solution

from .common import construct


def solve(
    problem: Problem, config: dict | None = None, deadline: float | None = None, seed: int = 0
) -> Solution:
    config = config or {}
    pair_bonus = float(config.get("pair_bonus", 12.0))
    scarcity_weight = float(config.get("scarcity_weight", 0.25))

    def priority(candidate):
        scarcity = sum(len(problem.candidates_by_task[task]) for task in candidate.task_key)
        scarcity /= max(1, candidate.task_count)
        adjusted_cost = candidate.expected_cost - pair_bonus * max(0, candidate.task_count - 1)
        return (adjusted_cost / candidate.task_count + scarcity_weight * scarcity, -candidate.task_count, candidate.courier_id)

    return construct(problem, priority, deadline)
