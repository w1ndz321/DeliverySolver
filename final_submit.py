"""OJ export entry point.

Serving uses the best validated frozen solver. The agent workflow that selected
and evaluated strategies remains outside this latency-critical submission path.
"""

from __future__ import annotations

from solver.improved_solver import solve as _validated_champion
from solver.parser import parse_problem
from solver.strategies.baseline_greedy import solve as _baseline_greedy


def solve(input_text: str) -> list:
    try:
        return _validated_champion(input_text)
    except Exception:
        return _baseline_greedy(parse_problem(input_text))
