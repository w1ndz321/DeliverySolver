"""Online diagnostics and offline strategy-code synthesis."""

from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path
from textwrap import dedent


STABLE_STRATEGY_MODULES = {
    "baseline_greedy": "solver.strategies.baseline_greedy",
    "expected_cost_greedy": "solver.strategies.expected_cost_greedy",
    "gain_greedy": "solver.strategies.gain_greedy",
    "coverage_first": "solver.strategies.coverage_first",
    "scarce_pair": "solver.strategies.scarce_pair",
    "learned_ranker": "solver.strategies.learned_ranker",
    "local_search": "solver.strategies.local_search",
    "destroy_repair": "solver.strategies.destroy_repair",
}


def safe_identifier(value: str, default: str = "general") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_").lower()
    if not cleaned:
        cleaned = default
    if cleaned[0].isdigit():
        cleaned = f"case_{cleaned}"
    return cleaned


def stable_strategy_name(strategy: str) -> str:
    if strategy.startswith("local_search"):
        return "local_search"
    if strategy.startswith("destroy_repair"):
        return "destroy_repair"
    return strategy


def important_profile_signals(profile: dict) -> list[dict]:
    """Extract the compact data facts that should drive strategy choice."""
    scarce_ratio = len(profile.get("scarce_tasks", [])) / max(1, profile.get("num_tasks", 0))
    courier_ratio = profile.get("courier_task_ratio", 0.0)
    pair_ratio = profile.get("pair_bundle_ratio", 0.0)
    willingness_mean = profile.get("willingness_distribution", {}).get("mean", 0.0)
    positive_gain_ratio = profile.get("positive_gain_ratio", 0.0)
    conflict_density = profile.get("conflict_density", 0.0)
    signals = [
        {
            "name": "case_type",
            "value": profile.get("case_type", "general"),
            "status": "scene",
            "why_it_matters": "Groups similar inputs so offline memory can learn a strategy preference per scene.",
        },
        {
            "name": "courier_task_ratio",
            "value": courier_ratio,
            "status": "scarce" if courier_ratio <= 1.25 else "comfortable",
            "why_it_matters": (
                "Courier supply is tight; protect coverage and pair bundles before cheap dense tasks consume riders."
                if courier_ratio <= 1.25
                else "Courier supply is not the bottleneck; cost and rejection risk should dominate coverage heuristics."
            ),
        },
        {
            "name": "pair_bundle_ratio",
            "value": pair_ratio,
            "status": "pair_rich" if pair_ratio >= 0.3 else "pair_sparse",
            "why_it_matters": (
                "Pair supply is high enough to justify pair-aware construction or merge repair."
                if pair_ratio >= 0.3
                else "Pair supply is limited; singleton ranking is likely a better default."
            ),
        },
        {
            "name": "willingness_mean",
            "value": willingness_mean,
            "status": "low" if willingness_mean < 0.3 else "normal",
            "why_it_matters": (
                "Low willingness shifts cost from accepted score to rejection risk."
                if willingness_mean < 0.3
                else "Willingness is not unusually low; accepted-score optimization remains useful."
            ),
        },
        {
            "name": "positive_gain_ratio",
            "value": positive_gain_ratio,
            "status": "thin_gain" if positive_gain_ratio < 0.35 else "healthy_gain",
            "why_it_matters": (
                "Few positive-gain candidates mean the solver should avoid low-value assignments."
                if positive_gain_ratio < 0.35
                else "Most candidates improve over leaving tasks unassigned; ranking quality matters more than pruning."
            ),
        },
        {
            "name": "scarce_task_ratio",
            "value": round(scarce_ratio, 6),
            "status": "many_scarce_tasks" if scarce_ratio >= 0.2 else "few_scarce_tasks",
            "why_it_matters": (
                "Many scarce tasks require early reservation before easy tasks consume couriers."
                if scarce_ratio >= 0.2
                else "Few tasks are structurally scarce; coverage-first should not overpower cost ranking."
            ),
        },
        {
            "name": "conflict_density",
            "value": conflict_density,
            "status": "dense" if conflict_density >= 0.12 else "moderate",
            "why_it_matters": (
                "Dense conflicts reduce the useful neighborhood size for local search."
                if conflict_density >= 0.12
                else "Conflict density is moderate; local search can explore a normal neighborhood."
            ),
        },
    ]
    return signals


def diagnose_score(profile: dict, evaluation: dict, solution_summary: dict | None = None) -> list[dict]:
    """Convert score decomposition into actionable strategy issues."""
    solution_summary = solution_summary or {}
    decomposition = evaluation.get("score_decomposition", {})
    diagnostics: list[dict] = []
    if evaluation.get("uncovered_tasks", 0) > 0:
        diagnostics.append(
            {
                "code": "coverage_gap",
                "severity": "high",
                "message": "The solution leaves tasks uncovered, so coverage-first repair should dominate cost ranking.",
            }
        )
    if decomposition.get("rejection_risk_cost", 0.0) > decomposition.get("selected_expected_cost", 0.0):
        diagnostics.append(
            {
                "code": "rejection_risk_dominates",
                "severity": "medium",
                "message": "Rejection risk is larger than accepted-score cost; prefer high-willingness candidates.",
            }
        )
    if (
        profile.get("pair_bundle_ratio", 0.0) >= 0.3
        and solution_summary.get("pair_groups", 0) == 0
    ):
        diagnostics.append(
            {
                "code": "unused_pair_supply",
                "severity": "medium",
                "message": "The input has many pair bundles but the current solution used none.",
            }
        )
    if decomposition.get("high_cost_bundle_count", 0) > 0:
        diagnostics.append(
            {
                "code": "high_cost_selected",
                "severity": "low",
                "message": "Some selected bundles cost at least their unassigned penalty.",
            }
        )
    if not diagnostics:
        diagnostics.append(
            {
                "code": "no_major_score_pathology",
                "severity": "info",
                "message": "No dominant score pathology was detected; try small weighted-ranker variants only.",
            }
        )
    return diagnostics


def synthesize_strategy_specs(profile: dict, diagnostics: list[dict], max_rounds: int = 3) -> list[dict]:
    """Create bounded online strategy variants without writing files."""
    codes = {item["code"] for item in diagnostics}
    case_type = profile.get("case_type", "general")
    scarce_ratio = len(profile.get("scarce_tasks", [])) / max(1, profile.get("num_tasks", 0))
    base = {
        "expected_weight": 1.0,
        "gain_weight": 0.15,
        "scarcity_weight": 0.25,
        "willingness_weight": 4.0,
        "pair_bonus": 0.0,
        "high_cost_penalty": 0.5,
        "repair": True,
    }
    specs: list[dict] = []

    if "coverage_gap" in codes or scarce_ratio >= 0.15:
        params = dict(base, scarcity_weight=2.0, gain_weight=0.25, high_cost_penalty=1.0)
        specs.append(_spec("online_coverage_guard", case_type, params, "Protect scarce tasks before cheap dense tasks."))
    if "rejection_risk_dominates" in codes or profile.get("willingness_distribution", {}).get("mean", 1.0) < 0.3:
        params = dict(base, willingness_weight=18.0, high_cost_penalty=1.2, gain_weight=0.05)
        specs.append(_spec("online_risk_guard", case_type, params, "Reserve high-willingness couriers when rejection dominates."))
    if "unused_pair_supply" in codes or profile.get("pair_bundle_ratio", 0.0) >= 0.3:
        params = dict(base, pair_bonus=18.0, scarcity_weight=0.8, gain_weight=0.2)
        specs.append(_spec("online_pair_guard", case_type, params, "Try pair bundles when the data exposes enough pair supply."))

    params = dict(
        base,
        willingness_weight=8.0,
        pair_bonus=8.0 if profile.get("pair_bundle_ratio", 0.0) >= 0.2 else 0.0,
        scarcity_weight=1.0 if scarce_ratio >= 0.1 else 0.25,
    )
    specs.append(_spec("online_balanced_ranker", case_type, params, "Balanced fallback generated from score diagnostics."))

    unique: list[dict] = []
    seen: set[str] = set()
    for spec in specs:
        if spec["strategy"] in seen:
            continue
        seen.add(spec["strategy"])
        unique.append(spec)
        if len(unique) >= max_rounds:
            break
    return unique


def _spec(prefix: str, case_type: str, parameters: dict, rationale: str) -> dict:
    strategy = f"{prefix}_{safe_identifier(case_type)}"
    return {
        "strategy": strategy,
        "base_strategy": "learned_ranker",
        "source_type": "online_generated",
        "parameters": parameters,
        "rationale": rationale,
        "code": render_learned_strategy_code(strategy, parameters, rationale, case_type),
    }


def render_learned_strategy_code(
    strategy_name: str,
    parameters: dict,
    rationale: str,
    case_type: str,
) -> str:
    """Render a standalone strategy module that offline learning can persist."""
    literal_parameters = repr(_ordered_parameters(parameters))
    return dedent(
        f'''
        """Offline/online generated strategy for case type: {case_type}.

        Rationale: {rationale}
        """

        from __future__ import annotations

        from solver.parser import Candidate, Problem, Solution
        from solver.strategies.common import construct


        DEFAULT_CONFIG = {literal_parameters}


        def _task_scarcity(problem: Problem, candidate: Candidate) -> float:
            return sum(len(problem.candidates_by_task[task]) for task in candidate.task_key) / max(
                1, candidate.task_count
            )


        def solve(
            problem: Problem, config: dict | None = None, deadline: float | None = None, seed: int = 0
        ) -> Solution:
            config = dict(DEFAULT_CONFIG, **(config or {{}}))
            expected_weight = float(config.get("expected_weight", 1.0))
            gain_weight = float(config.get("gain_weight", 0.0))
            scarcity_weight = float(config.get("scarcity_weight", 0.0))
            willingness_weight = float(config.get("willingness_weight", 0.0))
            pair_bonus = float(config.get("pair_bonus", 0.0))
            high_cost_penalty = float(config.get("high_cost_penalty", 0.0))
            repair = bool(config.get("repair", True))

            def priority(candidate: Candidate) -> tuple:
                task_count = max(1, candidate.task_count)
                expected = candidate.expected_cost / task_count
                scarcity = _task_scarcity(problem, candidate)
                high_cost = max(0.0, candidate.expected_cost - 100.0 * task_count) / task_count
                score = (
                    expected_weight * expected
                    - gain_weight * (candidate.gain / task_count)
                    + scarcity_weight * scarcity
                    - willingness_weight * candidate.willingness
                    - pair_bonus * max(0, candidate.task_count - 1)
                    + high_cost_penalty * high_cost
                )
                return (score, expected, -candidate.task_count, candidate.task_str, candidate.courier_id)

            return construct(problem, priority, deadline, repair=repair)
        '''
    ).lstrip()


def _ordered_parameters(parameters: dict) -> dict:
    return {key: parameters[key] for key in sorted(parameters)}


def strategy_code_payload(strategy: str, plan: dict, generated_specs: list[dict]) -> dict:
    """Return code metadata for the selected strategy."""
    generated_by_name = {item["strategy"]: item for item in generated_specs}
    if strategy in generated_by_name:
        spec = generated_by_name[strategy]
        return {
            "source_type": spec.get("source_type", "online_generated"),
            "code": spec["code"],
            "code_path": None,
            "base_strategy": spec.get("base_strategy"),
        }

    modules = plan.get("strategy_modules", {})
    if strategy in modules:
        module_spec = modules[strategy]
        path = Path(module_spec.get("module_path", ""))
        code = path.read_text(encoding="utf-8") if path.is_file() else ""
        return {
            "source_type": module_spec.get("source_type", "offline_generated"),
            "code": code,
            "code_path": str(path) if path else None,
            "base_strategy": module_spec.get("base_strategy", "learned_ranker"),
        }

    stable = stable_strategy_name(strategy)
    module_name = STABLE_STRATEGY_MODULES.get(stable)
    if module_name is None:
        return {"source_type": "unknown", "code": "", "code_path": None, "base_strategy": None}
    module = importlib.import_module(module_name)
    path = Path(inspect.getsourcefile(module) or "")
    return {
        "source_type": "stable",
        "code": inspect.getsource(module),
        "code_path": str(path) if path else None,
        "base_strategy": stable,
    }
