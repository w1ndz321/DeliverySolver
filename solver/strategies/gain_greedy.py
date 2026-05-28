"""Greedy construction ranked by avoided-penalty gain."""

from __future__ import annotations

from solver.parser import Problem, Solution

from .common import construct


def solve(
    problem: Problem, config: dict | None = None, deadline: float | None = None, seed: int = 0
) -> Solution:
    return construct(
        problem,
        lambda candidate: (-candidate.gain, candidate.expected_cost, candidate.courier_id),
        deadline,
    )
