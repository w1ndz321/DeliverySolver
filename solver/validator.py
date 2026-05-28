"""Solution legality checks independent of strategy implementation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence, Tuple

from .parser import Problem, Solution, canonical_task_key, normalize_solution


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: list[str]
    covered_tasks: int
    uncovered_tasks: int
    used_couriers: int

    def to_dict(self) -> dict:
        return asdict(self)


def validate_solution(
    solution: Sequence[Tuple[str, Sequence[str]]], problem: Problem
) -> tuple[Solution, ValidationResult]:
    normalized: Solution = []
    errors: list[str] = []
    covered: set[str] = set()
    used_couriers: set[str] = set()
    try:
        normalized = normalize_solution(solution)
    except (TypeError, ValueError) as exc:
        return [], ValidationResult(False, [f"invalid output format: {exc}"], 0, problem.num_tasks, 0)

    for index, (task_str, couriers) in enumerate(normalized):
        task_key = canonical_task_key(task_str)
        if not task_key:
            errors.append(f"item {index}: empty task list")
            continue
        unknown_tasks = set(task_key) - problem.task_ids
        if unknown_tasks:
            errors.append(f"item {index}: unknown task ids {sorted(unknown_tasks)}")
        overlap = set(task_key) & covered
        if overlap:
            errors.append(f"item {index}: overlapping task ids {sorted(overlap)}")
        if not couriers:
            errors.append(f"item {index}: no courier assigned")
        local: set[str] = set()
        for courier_id in couriers:
            if courier_id in local:
                errors.append(f"item {index}: duplicate courier {courier_id}")
            if courier_id in used_couriers:
                errors.append(f"item {index}: reused courier {courier_id}")
            if (task_key, courier_id) not in problem.candidate_map:
                errors.append(f"item {index}: courier {courier_id} cannot serve {','.join(task_key)}")
            local.add(courier_id)
        covered.update(task_key)
        used_couriers.update(local)

    uncovered = problem.task_ids - covered
    return normalized, ValidationResult(
        valid=not errors,
        errors=errors,
        covered_tasks=len(covered & problem.task_ids),
        uncovered_tasks=len(uncovered),
        used_couriers=len(used_couriers),
    )
