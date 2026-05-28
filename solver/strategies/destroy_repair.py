"""Deterministic ruin-and-recreate search accepting improvements only."""

from __future__ import annotations

from evaluator.judge_local import evaluate_solution
from solver.parser import Problem, Solution, canonical_task_key
from solver.scoring import expected_bundle_cost

from . import expected_cost_greedy
from .common import deadline_reached, select_non_overlapping, selected_state


def _score(solution: Solution, problem: Problem) -> float:
    result = evaluate_solution(solution, problem)
    return result.score if result.valid and result.score is not None else float("inf")


def solve(
    problem: Problem,
    config: dict | None = None,
    deadline: float | None = None,
    seed: int = 0,
    initial_solution: Solution | None = None,
) -> Solution:
    config = config or {}
    best = [
        (task_str, list(couriers))
        for task_str, couriers in (initial_solution or expected_cost_greedy.solve(problem, deadline=deadline))
    ]
    best_score = _score(best, problem)
    if not best:
        return best
    destroy_ratio = min(0.5, max(0.05, float(config.get("destroy_ratio", 0.2))))
    attempts = int(config.get("destroy_attempts", 4))

    def group_cost(group: tuple[str, list[str]]) -> float:
        task_key = canonical_task_key(group[0])
        rows = [problem.candidate_map[(task_key, courier)] for courier in group[1]]
        return expected_bundle_cost(task_key, rows).total / len(task_key)

    for attempt in range(attempts):
        if deadline_reached(deadline):
            break
        remove_count = max(1, int(len(best) * destroy_ratio))
        ranked_indexes = sorted(range(len(best)), key=lambda index: group_cost(best[index]), reverse=True)
        offset = attempt % len(best)
        remove = {ranked_indexes[(offset + index) % len(best)] for index in range(remove_count)}
        kept = [group for index, group in enumerate(best) if index not in remove]
        missing = {task for index in remove for task in canonical_task_key(best[index][0])}
        covered, used = selected_state(kept)
        repair_rows = sorted(
            [
                row for row in problem.candidates
                if set(row.task_key) <= missing and row.courier_id not in used
            ],
            key=lambda row: (row.expected_cost / row.task_count, -row.task_count, row.courier_id),
        )
        repaired = select_non_overlapping(
            repair_rows, used_couriers=used, covered_tasks=covered, allowed_tasks=missing, deadline=deadline
        )
        proposal = kept + repaired
        proposal_score = _score(proposal, problem)
        if proposal_score + 1e-9 < best_score:
            best, best_score = proposal, proposal_score
    return best
