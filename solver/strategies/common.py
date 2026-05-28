"""Shared deterministic construction helpers for stable strategies."""

from __future__ import annotations

import time
from typing import Callable, Iterable, Union

from solver.parser import Candidate, Problem, Solution


CandidateKey = Callable[[Candidate], Union[tuple, float]]


def deadline_reached(deadline: float | None) -> bool:
    return deadline is not None and time.perf_counter() >= deadline


def select_non_overlapping(
    candidates: Iterable[Candidate],
    used_couriers: set[str] | None = None,
    covered_tasks: set[str] | None = None,
    allowed_tasks: set[str] | None = None,
    deadline: float | None = None,
) -> Solution:
    used = set() if used_couriers is None else set(used_couriers)
    covered = set() if covered_tasks is None else set(covered_tasks)
    output: Solution = []
    for candidate in candidates:
        if deadline_reached(deadline):
            break
        tasks = set(candidate.task_key)
        if allowed_tasks is not None and not tasks <= allowed_tasks:
            continue
        if candidate.courier_id in used or tasks & covered:
            continue
        output.append((candidate.task_str, [candidate.courier_id]))
        used.add(candidate.courier_id)
        covered.update(tasks)
    return output


def selected_state(solution: Solution) -> tuple[set[str], set[str]]:
    covered: set[str] = set()
    couriers: set[str] = set()
    for task_str, assigned in solution:
        covered.update(task_str.split(","))
        couriers.update(assigned)
    return covered, couriers


def repair_uncovered(
    problem: Problem,
    solution: Solution,
    rank_key: CandidateKey,
    deadline: float | None = None,
) -> Solution:
    """Cover still free tasks where a non-conflicting candidate remains."""
    output = [(task_str, list(couriers)) for task_str, couriers in solution]
    covered, used = selected_state(output)
    while problem.task_ids - covered and not deadline_reached(deadline):
        remaining = problem.task_ids - covered
        feasible = [
            candidate
            for candidate in problem.candidates
            if candidate.courier_id not in used and set(candidate.task_key) <= remaining
        ]
        if not feasible:
            break
        feasible.sort(key=rank_key)
        chosen = feasible[0]
        output.append((chosen.task_str, [chosen.courier_id]))
        used.add(chosen.courier_id)
        covered.update(chosen.task_key)
    return output


def construct(
    problem: Problem,
    rank_key: CandidateKey,
    deadline: float | None = None,
    repair: bool = True,
) -> Solution:
    ranked = sorted(problem.candidates, key=rank_key)
    solution = select_non_overlapping(ranked, deadline=deadline)
    return repair_uncovered(problem, solution, rank_key, deadline) if repair else solution
