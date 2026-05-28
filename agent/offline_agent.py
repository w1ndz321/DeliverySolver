"""Offline loop: aggregate online evidence and update strategy memory."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from solver.parser import parse_problem
from solver.portfolio import run_portfolio

from .llm_client import LLMClient
from .strategy_planner import DEFAULT_MEMORY_PATH, STATE_ROOT
from .strategy_synthesizer import (
    render_learned_strategy_code,
    safe_identifier,
    stable_strategy_name,
)


STABLE_ONLINE_STRATEGIES = {
    "baseline_greedy",
    "expected_cost_greedy",
    "gain_greedy",
    "coverage_first",
    "scarce_pair",
    "learned_ranker",
    "local_search",
    "destroy_repair",
}


def _profile_feature_value(profile: dict, name: str):
    if name == "willingness_mean":
        return profile.get("willingness_distribution", {}).get("mean")
    if name == "scarce_task_count":
        return len(profile.get("scarce_tasks", []))
    return profile.get(name)


class OfflineAgent:
    def __init__(
        self,
        log_root: str | Path | None = None,
        report_root: str | Path | None = None,
        memory_path: str | Path | None = None,
        llm_config: dict | None = None,
        max_iterations: int = 5,
        patience: int = 2,
        min_improvement: float = 0.001,
    ):
        self.log_root = Path(log_root) if log_root else STATE_ROOT / "logs" / "runs"
        self.report_root = Path(report_root) if report_root else STATE_ROOT / "reports"
        self.memory_path = Path(memory_path) if memory_path else DEFAULT_MEMORY_PATH
        self.generated_strategy_root = self.memory_path.parent / "generated_strategies"
        self.llm = LLMClient(llm_config)
        self.max_iterations = max(1, int(max_iterations))
        self.patience = max(1, int(patience))
        self.min_improvement = max(0.0, float(min_improvement))

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _load_runs(self) -> list[dict]:
        runs: list[dict] = []
        for path in sorted(self.log_root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("case_profile") and payload.get("final_evaluation"):
                runs.append(payload)
        return runs

    def _strategy_path(self, strategy_name: str) -> Path:
        return self.generated_strategy_root / f"{safe_identifier(strategy_name)}.py"

    def _write_strategy_module(self, case_type: str, payload: dict, strategy_name: str | None = None) -> dict:
        strategy_name = strategy_name or f"offline_learned_{safe_identifier(case_type)}"
        path = self._strategy_path(strategy_name)
        code = render_learned_strategy_code(
            strategy_name,
            payload["parameters"],
            payload["rationale"],
            case_type,
        )
        self._write(path, code)
        return {
            "module_path": str(path),
            "source_type": "offline_generated",
            "base_strategy": "learned_ranker",
            "rationale": payload["rationale"],
            "parameters": payload["parameters"],
        }

    def _llm_plan_ablation(self, case_type: str, case_runs: list[dict], learned_payload: dict) -> dict:
        latest = case_runs[-1]
        compact_runs = [
            {
                "run_id": run.get("run_id"),
                "data_analysis": run.get("data_analysis"),
                "case_profile": {
                    "case_type": run.get("case_profile", {}).get("case_type"),
                    "num_tasks": run.get("case_profile", {}).get("num_tasks"),
                    "num_couriers": run.get("case_profile", {}).get("num_couriers"),
                    "pair_bundle_ratio": run.get("case_profile", {}).get("pair_bundle_ratio"),
                    "willingness_mean": run.get("case_profile", {}).get("willingness_distribution", {}).get("mean"),
                    "conflict_density": run.get("case_profile", {}).get("conflict_density"),
                },
                "selected_strategy": run.get("selected_strategy"),
                "final_score": run.get("final_evaluation", {}).get("score"),
                "portfolio_scores": [
                    {
                        "strategy": item.get("strategy"),
                        "score": item.get("score"),
                        "parameters": item.get("parameters", {}),
                    }
                    for item in run.get("portfolio", {}).get("outcomes", [])
                ],
            }
            for run in case_runs[-4:]
        ]
        fallback = {
            "valuable_features": [
                "courier_task_ratio",
                "pair_bundle_ratio",
                "willingness_mean",
                "conflict_density",
            ],
            "ablation_trials": [
                {
                    "name": f"offline_ablation_{safe_identifier(case_type)}",
                    "parameters": learned_payload["parameters"],
                    "hypothesis": learned_payload["rationale"],
                }
            ],
            "promotion_rule": "promote only if score improves over the best logged strategy",
            "should_create_algorithm": False,
        }
        prompt = {
            "task": "Analyze online logs and propose offline ablation trials for a delivery assignment solver.",
            "case_type": case_type,
            "runs": compact_runs,
            "seed_parameters": learned_payload,
            "latest_raw_input_available": bool(latest.get("input_excerpt") or latest.get("raw_input_available")),
            "output_schema": {
                "valuable_features": ["feature names that explain strategy choice"],
                "ablation_trials": [
                    {"name": "trial name", "parameters": "learned_ranker parameters", "hypothesis": "why it may improve"}
                ],
                "promotion_rule": "when to add algorithm to candidate library",
                "should_create_algorithm": "boolean",
            },
        }
        return self.llm.ask_json(
            "You are the offline AutoSolver research agent. Return only JSON. Propose reusable ablations, not one-off hacks.",
            json.dumps(prompt, ensure_ascii=False),
            fallback,
            timeout=12.0,
        )

    def _run_ablation_trials(self, case_type: str, case_runs: list[dict], ablation_decision: dict) -> dict:
        latest = case_runs[-1]
        raw_input = latest.get("input_text")
        if not raw_input:
            return {
                "status": "skipped",
                "reason": "online log did not persist input_text",
                "trials": [],
                "best_trial": None,
                "improved": False,
            }
        problem = parse_problem(raw_input)
        logged_scores = [
            item.get("score")
            for run in case_runs
            for item in run.get("portfolio", {}).get("outcomes", [])
            if item.get("score") is not None
        ]
        baseline = min(logged_scores + [latest.get("final_evaluation", {}).get("score", float("inf"))])
        trials = []
        strategy_plan = {
            "strategies": [],
            "strategy_parameters": {},
        }
        for index, trial in enumerate(ablation_decision.get("ablation_trials", [])[: self.max_iterations]):
            if not isinstance(trial, dict) or not isinstance(trial.get("parameters"), dict):
                continue
            name = safe_identifier(trial.get("name") or f"offline_ablation_{case_type}_{index}")
            strategy_plan["strategies"].append(name)
            strategy_plan["strategy_parameters"][name] = trial["parameters"]
            strategy_plan.setdefault("strategy_modules", {})
        if not strategy_plan["strategies"]:
            return {"status": "skipped", "reason": "no valid ablation trials", "trials": [], "best_trial": None, "improved": False}
        # Dynamic learned_ranker aliases are handled by rendering temporary modules.
        for name in list(strategy_plan["strategies"]):
            module_path = self._strategy_path(name)
            params = strategy_plan["strategy_parameters"][name]
            self._write(
                module_path,
                render_learned_strategy_code(
                    name,
                    params,
                    f"offline ablation for {case_type}",
                    case_type,
                ),
            )
            strategy_plan.setdefault("strategy_modules", {})[name] = {
                "module_path": str(module_path),
                "source_type": "offline_ablation",
                "base_strategy": "learned_ranker",
            }
        portfolio = run_portfolio(problem, strategy_plan, 3.0, 301)
        best_score = baseline
        stale_rounds = 0
        stop_reason = "max_iterations"
        for outcome in portfolio.outcomes:
            payload = outcome.to_dict(include_solution=False)
            score = payload.get("score")
            if score is not None and payload.get("status") == "ok":
                relative_gain = (best_score - score) / max(abs(best_score), 1.0)
                payload["relative_improvement"] = relative_gain
                if relative_gain >= self.min_improvement:
                    best_score = score
                    stale_rounds = 0
                else:
                    stale_rounds += 1
            else:
                payload["relative_improvement"] = 0.0
                stale_rounds += 1
            trials.append(payload)
            if stale_rounds >= self.patience:
                stop_reason = "patience"
                break
        best = min(
            [item for item in trials if item.get("score") is not None and item.get("status") == "ok"],
            key=lambda item: item["score"],
            default=None,
        )
        required_score = baseline * (1.0 - self.min_improvement)
        improved = bool(best and best["score"] + 1e-9 < required_score)
        return {
            "status": "ok",
            "baseline_score": baseline,
            "trials": trials,
            "best_trial": best,
            "improved": improved,
            "improvement": (baseline - best["score"]) if improved and best else 0.0,
            "stop_reason": stop_reason,
            "stop_policy": {
                "max_iterations": self.max_iterations,
                "patience": self.patience,
                "min_improvement": self.min_improvement,
            },
        }

    @staticmethod
    def _learn_parameters(case_type: str, case_runs: list[dict], diagnostics: Counter) -> dict:
        profiles = [run["case_profile"] for run in case_runs]
        avg_pair_ratio = sum(item.get("pair_bundle_ratio", 0.0) for item in profiles) / len(profiles)
        avg_willingness = sum(item.get("willingness_distribution", {}).get("mean", 0.0) for item in profiles) / len(profiles)
        avg_scarce_ratio = sum(
            len(item.get("scarce_tasks", [])) / max(1, item.get("num_tasks", 0))
            for item in profiles
        ) / len(profiles)
        params = {
            "expected_weight": 1.0,
            "gain_weight": 0.2,
            "scarcity_weight": 0.4,
            "willingness_weight": 5.0,
            "pair_bonus": 0.0,
            "high_cost_penalty": 0.6,
            "repair": True,
        }
        reasons = []
        if avg_scarce_ratio >= 0.15 or "scarce_tasks" in case_type:
            params["scarcity_weight"] = 1.8
            params["high_cost_penalty"] = 1.0
            reasons.append("scarce tasks were common")
        if avg_willingness < 0.3 or "low_willingness" in case_type:
            params["willingness_weight"] = 18.0
            params["gain_weight"] = 0.05
            reasons.append("low willingness made rejection risk important")
        if avg_pair_ratio >= 0.25 or "pair_rich" in case_type:
            params["pair_bonus"] = 16.0
            params["scarcity_weight"] = max(params["scarcity_weight"], 0.8)
            reasons.append("pair bundles were available")
        if diagnostics["high_cost_selected"] > 0:
            params["high_cost_penalty"] = max(params["high_cost_penalty"], 1.2)
            reasons.append("some selected bundles cost at least their unassigned penalty")
        rationale = "; ".join(reasons) if reasons else "balanced ranker from aggregated online evidence"
        return {"parameters": params, "rationale": rationale}

    def analyze(self) -> dict:
        runs = self._load_runs()
        by_case: dict[str, list[dict]] = defaultdict(list)
        diagnostics = Counter()
        diagnostic_by_case: dict[str, Counter] = defaultdict(Counter)
        for run in runs:
            case_type = run["case_profile"].get("case_type", "general")
            by_case[case_type].append(run)
            evaluation = run["final_evaluation"]
            decomposition = evaluation.get("score_decomposition", {})
            if evaluation.get("uncovered_tasks", 0) > 0:
                diagnostics["覆盖不足：存在未覆盖订单，应增强 coverage_first 或合单修复。"] += 1
                diagnostic_by_case[case_type]["coverage_gap"] += 1
            if decomposition.get("uncovered_penalty", 0.0) == 0 and decomposition.get("rejection_risk_cost", 0.0) > decomposition.get("selected_expected_cost", 0.0):
                diagnostics["拒单风险主导成本：应优先保护高 willingness 骑手。"] += 1
                diagnostic_by_case[case_type]["rejection_risk_dominates"] += 1
            if run["case_profile"].get("pair_bundle_ratio", 0.0) > 0.35 and run["solution_summary"].get("pair_groups", 0) == 0:
                diagnostics["合单利用不足：pair-rich 场景未使用双订单分配。"] += 1
                diagnostic_by_case[case_type]["unused_pair_supply"] += 1
            if decomposition.get("high_cost_bundle_count", 0) > 0:
                diagnostic_by_case[case_type]["high_cost_selected"] += 1
            portfolio_scores = {
                item["strategy"]: item.get("score")
                for item in run.get("portfolio", {}).get("outcomes", [])
                if item.get("score") is not None
            }
            initial_scores = [
                score for strategy, score in portfolio_scores.items()
                if strategy not in {"local_search", "destroy_repair"}
            ]
            if (
                "local_search" in portfolio_scores
                and initial_scores
                and portfolio_scores["local_search"] >= min(initial_scores) - 1e-9
            ):
                diagnostics["局部搜索未带来可见收益：需要调整邻域或初始解。"] += 1

        case_memory: dict[str, dict] = {}
        strategy_summary: dict[str, dict] = {}
        learned_code: dict[str, dict] = {}
        valuable_features: dict[str, list[dict]] = {}
        for case_type, case_runs in sorted(by_case.items()):
            wins = Counter(stable_strategy_name(run["selected_strategy"]) for run in case_runs)
            scores: dict[str, list[float]] = defaultdict(list)
            for run in case_runs:
                for outcome in run.get("portfolio", {}).get("outcomes", []):
                    if outcome.get("score") is not None:
                        scores[stable_strategy_name(outcome["strategy"])].append(outcome["score"])
                for outcome in run.get("iterations", []):
                    if outcome.get("score") is not None:
                        scores[stable_strategy_name(outcome["strategy"])].append(outcome["score"])
            average_scores = {
                strategy: round(sum(values) / len(values), 6)
                for strategy, values in scores.items()
            }
            preferred = [
                strategy for strategy, _ in wins.most_common(2)
                if strategy in STABLE_ONLINE_STRATEGIES
            ]
            if not preferred and average_scores:
                preferred = [min(average_scores, key=average_scores.get)]
            learned_payload = self._learn_parameters(case_type, case_runs, diagnostic_by_case[case_type])
            ablation_decision = self._llm_plan_ablation(case_type, case_runs, learned_payload)
            ablation_result = self._run_ablation_trials(case_type, case_runs, ablation_decision["decision"])
            module_strategy = f"offline_learned_{safe_identifier(case_type)}"
            should_promote = bool(ablation_result.get("improved"))
            module_info = None
            if should_promote:
                if ablation_result.get("improved") and ablation_result.get("best_trial"):
                    module_strategy = ablation_result["best_trial"]["strategy"]
                    learned_payload = {
                        "parameters": ablation_result["best_trial"].get("parameters", learned_payload["parameters"]),
                        "rationale": (
                            f"offline ablation improved score by {ablation_result.get('improvement', 0.0):.6f}; "
                            f"{ablation_decision['decision'].get('promotion_rule', '')}"
                        ),
                    }
                module_info = self._write_strategy_module(case_type, learned_payload, module_strategy)
                learned_code[case_type] = {"strategy": module_strategy, **module_info}
                if module_strategy not in preferred:
                    preferred.append(module_strategy)
            latest_metrics = case_runs[-1].get("data_analysis", {}).get("metrics", {})
            latest_profile = case_runs[-1].get("case_profile", {})
            valuable_features[case_type] = [
                {
                    "name": name,
                    "value": latest_metrics.get(name, _profile_feature_value(latest_profile, name)),
                    "source": "offline_llm",
                }
                for name in ablation_decision["decision"].get("valuable_features", [])[:8]
            ]
            strategy_modules = {module_strategy: module_info} if module_info else {}
            case_memory[case_type] = {
                "evidence_runs": len(case_runs),
                "preferred_strategies": preferred,
                "average_scores": average_scores,
                "strategy_parameters": {module_strategy: learned_payload["parameters"]} if module_info else {},
                "strategy_modules": strategy_modules,
                "valuable_features": valuable_features[case_type],
                "diagnostics": dict(diagnostic_by_case[case_type]),
                "offline_agent": {
                    "llm_required": True,
                    "ablation_decision": ablation_decision,
                    "ablation_result": ablation_result,
                    "promoted": bool(module_info),
                },
            }
            strategy_summary[case_type] = {
                "runs": len(case_runs),
                "wins": dict(wins),
                "average_scores": average_scores,
                "learned_strategy": module_strategy if module_info else None,
                "ablation_improved": ablation_result.get("improved", False),
            }

        memory = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "evidence_runs": len(runs),
            "case_types": case_memory,
        }
        self._write_json(self.memory_path, memory)
        self._write_json(self.report_root / "updated_rule_memory.json", memory)
        failure_lines = ["# Failure Analysis Report", "", f"Analyzed online runs: {len(runs)}", "", "## Diagnoses"]
        if diagnostics:
            failure_lines.extend(f"- {message} ({count} runs)" for message, count in diagnostics.most_common())
        else:
            failure_lines.append("- No failure pattern can be concluded from current evidence.")
        failure_lines.extend(["", "## Case Strategy Evidence", ""])
        for case_type, summary in strategy_summary.items():
            failure_lines.append(f"- `{case_type}`: {summary['runs']} runs; wins={summary['wins']}; averages={summary['average_scores']}")
        failure_lines.extend(["", "## Valuable Data Features", ""])
        for case_type, features in valuable_features.items():
            names = ", ".join(item["name"] for item in features)
            failure_lines.append(f"- `{case_type}`: {names}")
        suggestions = [
            "# Strategy Improvement Suggestions",
            "",
            "- Online runs do not modify code; offline learning writes generated strategy modules and records them in rule memory.",
        ]
        if diagnostics["覆盖不足：存在未覆盖订单，应增强 coverage_first 或合单修复。"]:
            suggestions.append("- Replay scarce-courier cases with larger `scarcity_weight` before promoting that parameter.")
        if diagnostics["拒单风险主导成本：应优先保护高 willingness 骑手。"]:
            suggestions.append("- Evaluate an explicit high-willingness reservation parameter in offline ablation.")
        if len(runs) < 3:
            suggestions.append("- Accumulate at least three representative runs per case type before treating learned preference as robust.")
        for case_type, item in learned_code.items():
            suggestions.append(f"- Generated `{item['strategy']}` for `{case_type}` at `{item['module_path']}`.")
        self._write(self.report_root / "failure_analysis_report.md", "\n".join(failure_lines) + "\n")
        self._write(self.report_root / "strategy_improvement_suggestions.md", "\n".join(suggestions) + "\n")
        return {
            "runs": len(runs),
            "stop_policy": {
                "max_iterations": self.max_iterations,
                "patience": self.patience,
                "min_improvement": self.min_improvement,
            },
            "memory": memory,
            "diagnostics": dict(diagnostics),
            "strategy_summary": strategy_summary,
            "learned_code": learned_code,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze stored online AutoSolver runs.")
    parser.add_argument("--logs", default=None)
    parser.add_argument("--reports", default=None)
    parser.add_argument("--memory", default=None)
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--patience", type=int, default=2)
    parser.add_argument("--min-improvement", type=float, default=0.001)
    args = parser.parse_args()
    output = OfflineAgent(
        args.logs,
        args.reports,
        args.memory,
        max_iterations=args.max_iterations,
        patience=args.patience,
        min_improvement=args.min_improvement,
    ).analyze()
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
