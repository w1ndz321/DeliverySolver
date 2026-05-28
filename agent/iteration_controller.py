"""Bounded parameter trials after the initial portfolio result."""

from __future__ import annotations

import time
from dataclasses import dataclass

from evaluator.judge_local import Evaluation, evaluate_solution
from solver.parser import Problem, Solution
from solver.portfolio import PortfolioResult, StrategyOutcome
from solver.strategies import destroy_repair, learned_ranker, local_search


@dataclass
class IterationResult:
    best_strategy: str
    best_solution: Solution
    best_evaluation: Evaluation
    attempts: list[StrategyOutcome]


def run_iterations(
    problem: Problem,
    initial: PortfolioResult,
    time_budget: float,
    seed: int = 0,
    generated_strategy_specs: list[dict] | None = None,
) -> IterationResult:
    started = time.perf_counter()
    deadline = started + max(0.0, time_budget)
    best_strategy = initial.best_strategy
    best_solution = initial.best_solution
    best_evaluation = initial.best_evaluation
    attempts: list[StrategyOutcome] = []
    variants: list[tuple[str, object, dict, bool]] = []
    for spec in generated_strategy_specs or []:
        variants.append((spec["strategy"], learned_ranker.solve, dict(spec.get("parameters", {})), False))
    variants.extend([
        ("local_search_tuned", local_search.solve, {"local_search_passes": 3, "local_search_candidates": 300}, True),
        ("destroy_repair_10pct", destroy_repair.solve, {"destroy_ratio": 0.10, "destroy_attempts": 3}, True),
        ("destroy_repair_30pct", destroy_repair.solve, {"destroy_ratio": 0.30, "destroy_attempts": 3}, True),
    ])
    for name, strategy, parameters, uses_initial_solution in variants:
        if time.perf_counter() >= deadline:
            break
        call_started = time.perf_counter()
        try:
            if uses_initial_solution:
                solution = strategy(
                    problem,
                    parameters,
                    deadline,
                    seed,
                    initial_solution=best_solution,
                )
            else:
                solution = strategy(problem, parameters, deadline, seed)
            evaluation = evaluate_solution(solution, problem)
            outcome = StrategyOutcome(
                name,
                "ok" if evaluation.valid else "invalid",
                (time.perf_counter() - call_started) * 1000.0,
                solution,
                evaluation,
                parameters,
                "; ".join(evaluation.errors) if not evaluation.valid else None,
            )
        except Exception as exc:
            outcome = StrategyOutcome(
                name,
                "error",
                (time.perf_counter() - call_started) * 1000.0,
                [],
                None,
                parameters,
                f"{type(exc).__name__}: {exc}",
            )
        attempts.append(outcome)
        if (
            outcome.evaluation
            and outcome.evaluation.valid
            and outcome.score is not None
            and best_evaluation.score is not None
            and outcome.score + 1e-9 < best_evaluation.score
        ):
            best_strategy = name
            best_solution = outcome.solution
            best_evaluation = outcome.evaluation
    return IterationResult(best_strategy, best_solution, best_evaluation, attempts)
