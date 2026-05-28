"""Greedy construction ranked by willingness-adjusted expected cost."""

from __future__ import annotations

from solver.parser import Problem, Solution

from .common import construct


def solve(
    problem: Problem, config: dict | None = None, deadline: float | None = None, seed: int = 0
) -> Solution:
    return construct(
        problem,
        lambda candidate: (candidate.expected_cost, -candidate.task_count, candidate.courier_id),
        deadline,
    )
