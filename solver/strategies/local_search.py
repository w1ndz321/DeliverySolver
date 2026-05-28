"""Bounded replace/add/split/merge improvement over a valid initial solution."""

from __future__ import annotations

from evaluator.judge_local import evaluate_solution
from solver.parser import Problem, Solution, canonical_task_key

from . import expected_cost_greedy
from .common import deadline_reached, selected_state


def _score(solution: Solution, problem: Problem) -> float:
    evaluation = evaluate_solution(solution, problem)
    return evaluation.score if evaluation.valid and evaluation.score is not None else float("inf")


def solve(
    problem: Problem,
    config: dict | None = None,
    deadline: float | None = None,
    seed: int = 0,
    initial_solution: Solution | None = None,
) -> Solution:
    config = config or {}
    max_passes = int(config.get("local_search_passes", 2))
    max_candidates = int(config.get("local_search_candidates", 200))
    best: Solution = [
        (task_str, list(couriers))
        for task_str, couriers in (initial_solution or expected_cost_greedy.solve(problem, deadline=deadline))
    ]
    best_score = _score(best, problem)
    ranked = sorted(problem.candidates, key=lambda row: (row.expected_cost, -row.task_count))[:max_candidates]

    for _ in range(max_passes):
        improved = False
        if deadline_reached(deadline):
            break
        for index, (task_str, couriers) in enumerate(list(best)):
            task_key = canonical_task_key(task_str)
            _, all_used = selected_state(best)
            released = all_used - set(couriers)
            alternatives = sorted(
                problem.candidates_by_bundle.get(task_key, []),
                key=lambda row: (row.expected_cost, row.courier_id),
            )
            for candidate in alternatives[:20]:
                if candidate.courier_id in released:
                    continue
                proposal = [(tasks, list(assigned)) for tasks, assigned in best]
                proposal[index] = (candidate.task_str, [candidate.courier_id])
                proposal_score = _score(proposal, problem)
                if proposal_score + 1e-9 < best_score:
                    best, best_score, improved = proposal, proposal_score, True
                    break
            if deadline_reached(deadline):
                break
            if len(couriers) == 1:
                _, used = selected_state(best)
                for candidate in alternatives[:20]:
                    if candidate.courier_id in used:
                        continue
                    proposal = [(tasks, list(assigned)) for tasks, assigned in best]
                    proposal[index] = (task_str, list(couriers) + [candidate.courier_id])
                    proposal_score = _score(proposal, problem)
                    if proposal_score + 1e-9 < best_score:
                        best, best_score, improved = proposal, proposal_score, True
                        break

        # Merge existing groups when one courier can serve their exact union.
        for candidate in ranked:
            if deadline_reached(deadline):
                break
            overlaps = [
                index
                for index, (task_str, _) in enumerate(best)
                if set(canonical_task_key(task_str)) & set(candidate.task_key)
            ]
            if len(overlaps) < 2:
                continue
            union = {task for index in overlaps for task in canonical_task_key(best[index][0])}
            if union != set(candidate.task_key):
                continue
            outside = [group for index, group in enumerate(best) if index not in overlaps]
            _, used_outside = selected_state(outside)
            if candidate.courier_id in used_outside:
                continue
            proposal = outside + [(candidate.task_str, [candidate.courier_id])]
            proposal_score = _score(proposal, problem)
            if proposal_score + 1e-9 < best_score:
                best, best_score, improved = proposal, proposal_score, True
                break

        # Split a pair/multi bundle into singletons if independent couriers are cheaper.
        for index, (task_str, assigned) in enumerate(list(best)):
            task_key = canonical_task_key(task_str)
            if len(task_key) <= 1 or deadline_reached(deadline):
                continue
            remaining = [group for group_index, group in enumerate(best) if group_index != index]
            _, used = selected_state(remaining)
            split: Solution = []
            for task_id in task_key:
                available = [
                    row for row in problem.candidates_by_bundle.get((task_id,), [])
                    if row.courier_id not in used
                ]
                if not available:
                    split = []
                    break
                chosen = min(available, key=lambda row: (row.expected_cost, row.courier_id))
                split.append((chosen.task_str, [chosen.courier_id]))
                used.add(chosen.courier_id)
            if split:
                proposal = remaining + split
                proposal_score = _score(proposal, problem)
                if proposal_score + 1e-9 < best_score:
                    best, best_score, improved = proposal, proposal_score, True
                    break
        if not improved:
            break
    return best
