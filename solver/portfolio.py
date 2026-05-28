"""Run a controlled strategy portfolio and retain evaluation evidence."""

from __future__ import annotations

import time
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Callable

from evaluator.judge_local import Evaluation, evaluate_solution
from solver.parser import Problem, Solution
from solver.strategies import (
    baseline_greedy,
    coverage_first,
    destroy_repair,
    expected_cost_greedy,
    gain_greedy,
    learned_ranker,
    local_search,
    scarce_pair,
)


REGISTRY: dict[str, Callable] = {
    "baseline_greedy": baseline_greedy.solve,
    "expected_cost_greedy": expected_cost_greedy.solve,
    "gain_greedy": gain_greedy.solve,
    "coverage_first": coverage_first.solve,
    "scarce_pair": scarce_pair.solve,
    "learned_ranker": learned_ranker.solve,
    "local_search": local_search.solve,
    "destroy_repair": destroy_repair.solve,
}
REFINEMENT_STRATEGIES = {"local_search", "destroy_repair"}


@dataclass
class StrategyOutcome:
    strategy: str
    status: str
    runtime_ms: float
    solution: Solution
    evaluation: Evaluation | None
    parameters: dict
    error: str | None = None

    @property
    def score(self) -> float | None:
        return self.evaluation.score if self.evaluation else None

    def to_dict(self, include_solution: bool = False) -> dict:
        payload = {
            "strategy": self.strategy,
            "status": self.status,
            "runtime_ms": round(self.runtime_ms, 3),
            "score": self.score,
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
            "parameters": self.parameters,
            "error": self.error,
        }
        if include_solution:
            payload["solution"] = self.solution
        return payload


@dataclass
class PortfolioResult:
    best_strategy: str
    best_solution: Solution
    best_evaluation: Evaluation
    outcomes: list[StrategyOutcome]
    runtime_ms: float

    def to_dict(self, include_solution: bool = False) -> dict:
        payload = {
            "best_strategy": self.best_strategy,
            "best_evaluation": self.best_evaluation.to_dict(),
            "runtime_ms": round(self.runtime_ms, 3),
            "outcomes": [outcome.to_dict(include_solution=False) for outcome in self.outcomes],
        }
        if include_solution:
            payload["best_solution"] = self.best_solution
        return payload


def _valid_best(outcomes: list[StrategyOutcome]) -> StrategyOutcome | None:
    legal = [
        result for result in outcomes
        if result.status == "ok" and result.evaluation and result.evaluation.valid and result.score is not None
    ]
    # ``min`` is stable: a refinement receiving the same score is not credited as an improvement.
    return min(legal, key=lambda result: result.score) if legal else None


def _load_strategy_from_path(name: str, module_path: str) -> Callable:
    path = Path(module_path)
    if not path.is_file():
        raise FileNotFoundError(module_path)
    spec = spec_from_file_location(f"autosolver_generated_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load strategy module {module_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    solve = getattr(module, "solve", None)
    if not callable(solve):
        raise AttributeError(f"{module_path} does not define solve")
    return solve


def _resolve_strategy(name: str, strategy_plan: dict) -> Callable | None:
    if name in REGISTRY:
        return REGISTRY[name]
    module_spec = strategy_plan.get("strategy_modules", {}).get(name)
    if module_spec:
        return _load_strategy_from_path(name, module_spec["module_path"])
    return None


def run_portfolio(
    problem: Problem,
    strategy_plan: dict,
    time_budget: float = 2.0,
    seed: int = 0,
) -> PortfolioResult:
    started = time.perf_counter()
    deadline = started + max(0.01, time_budget)
    requested = list(strategy_plan.get("strategies", []))
    names = list(dict.fromkeys(["baseline_greedy"] + requested))
    parameters_by_strategy = strategy_plan.get("strategy_parameters", {})
    outcomes: list[StrategyOutcome] = []

    for name in names:
        strategy = _resolve_strategy(name, strategy_plan)
        if strategy is None:
            outcomes.append(StrategyOutcome(name, "skipped", 0.0, [], None, {}, "unknown strategy"))
            continue
        if time.perf_counter() >= deadline and outcomes:
            outcomes.append(StrategyOutcome(name, "skipped", 0.0, [], None, {}, "time budget reached"))
            continue
        parameters = dict(parameters_by_strategy.get(name, {}))
        initial = _valid_best(outcomes)
        call_started = time.perf_counter()
        try:
            if name in REFINEMENT_STRATEGIES:
                solution = strategy(
                    problem,
                    parameters,
                    deadline,
                    seed,
                    initial_solution=initial.solution if initial else None,
                )
            else:
                solution = strategy(problem, parameters, deadline, seed)
            evaluation = evaluate_solution(solution, problem)
            status = "ok" if evaluation.valid else "invalid"
            outcomes.append(
                StrategyOutcome(
                    name,
                    status,
                    (time.perf_counter() - call_started) * 1000.0,
                    solution,
                    evaluation,
                    parameters,
                    "; ".join(evaluation.errors) if not evaluation.valid else None,
                )
            )
        except Exception as exc:
            outcomes.append(
                StrategyOutcome(
                    name,
                    "error",
                    (time.perf_counter() - call_started) * 1000.0,
                    [],
                    None,
                    parameters,
                    f"{type(exc).__name__}: {exc}",
                )
            )

    best = _valid_best(outcomes)
    if best is None:
        solution = baseline_greedy.solve(problem)
        evaluation = evaluate_solution(solution, problem)
        best = StrategyOutcome("baseline_greedy_fallback", "ok", 0.0, solution, evaluation, {})
        outcomes.append(best)
    assert best.evaluation is not None
    return PortfolioResult(
        best_strategy=best.strategy,
        best_solution=best.solution,
        best_evaluation=best.evaluation,
        outcomes=outcomes,
        runtime_ms=(time.perf_counter() - started) * 1000.0,
    )
