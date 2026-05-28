"""Local evaluator used by portfolio selection, experiments and reports."""

from __future__ import annotations

import argparse
import json
import runpy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from solver.parser import Problem, parse_problem
from solver.scoring import score_solution
from solver.validator import validate_solution


@dataclass(frozen=True)
class Evaluation:
    valid: bool
    score: float | None
    covered_tasks: int
    uncovered_tasks: int
    used_couriers: int
    errors: list[str]
    score_decomposition: dict

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_solution(solution: Sequence[tuple[str, Sequence[str]]], problem: Problem) -> Evaluation:
    normalized, validation = validate_solution(solution, problem)
    if not validation.valid:
        return Evaluation(
            valid=False,
            score=None,
            covered_tasks=validation.covered_tasks,
            uncovered_tasks=validation.uncovered_tasks,
            used_couriers=validation.used_couriers,
            errors=validation.errors,
            score_decomposition={},
        )
    breakdown = score_solution(normalized, problem)
    return Evaluation(
        valid=True,
        score=breakdown.total_score,
        covered_tasks=validation.covered_tasks,
        uncovered_tasks=validation.uncovered_tasks,
        used_couriers=validation.used_couriers,
        errors=[],
        score_decomposition=breakdown.to_dict(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate one exported solver.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--solver", required=True)
    args = parser.parse_args()
    input_text = Path(args.case).read_text()
    solve = runpy.run_path(args.solver)["solve"]
    result = evaluate_solution(solve(input_text), parse_problem(input_text))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
