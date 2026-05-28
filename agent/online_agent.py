"""Online loop: profile, plan, solve, evaluate, tune and log."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from analyzer.chart_builder import build_data_analysis
from analyzer.feature_extractor import extract_case_profile
from solver.parser import parse_problem
from solver.portfolio import REGISTRY, run_portfolio

from .iteration_controller import run_iterations
from .llm_client import LLMClient
from .recorded_fallback import recorded_topk_decision, recorded_tuning_decision
from .strategy_planner import DEFAULT_MEMORY_PATH, STATE_ROOT, plan_strategies
from .strategy_synthesizer import (
    diagnose_score,
    strategy_code_payload,
    synthesize_strategy_specs,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _rewrite_strategy_import(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("from . import "):
        return line.replace("from . import ", "from solver.strategies import ", 1)
    if stripped.startswith("from .common import "):
        return line.replace("from .common import ", "from solver.strategies.common import ", 1)
    return line


class OnlineAgent:
    def __init__(
        self,
        log_root: str | Path | None = None,
        output_root: str | Path | None = None,
        memory_path: str | Path | None = None,
        llm_config: dict | None = None,
    ):
        self.log_root = Path(log_root) if log_root else STATE_ROOT / "logs" / "runs"
        self.output_root = Path(output_root) if output_root else STATE_ROOT / "outputs"
        self.memory_path = Path(memory_path) if memory_path else DEFAULT_MEMORY_PATH
        self.llm = LLMClient(llm_config)

    @staticmethod
    def _write_json(path: Path, payload: dict | list) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _ranked_local_scores(local_library: dict) -> list[dict]:
        outcomes = local_library.get("outcomes", []) if isinstance(local_library, dict) else []
        return sorted(
            [
                {
                    "strategy": item.get("strategy"),
                    "score": item.get("score"),
                    "runtime_ms": item.get("runtime_ms"),
                    "status": item.get("status"),
                    "parameters": item.get("parameters", {}),
                }
                for item in outcomes
                if item.get("status") == "ok" and item.get("score") is not None
            ],
            key=lambda item: (item["score"], item.get("strategy") or ""),
        )

    @staticmethod
    def _mock_topk_fallback(profile: dict, plan: dict, top_k: int, local_library: dict) -> dict:
        recorded = recorded_topk_decision(profile, plan, top_k, local_library)
        if recorded:
            return recorded

        ranked = OnlineAgent._ranked_local_scores(local_library)
        chosen: list[str] = []
        if "baseline_greedy" in plan.get("strategies", []):
            chosen.append("baseline_greedy")
        for item in ranked:
            strategy = item["strategy"]
            if strategy in plan.get("strategies", []) and strategy not in chosen:
                chosen.append(strategy)
            if len(chosen) >= top_k:
                break
        for strategy in plan.get("strategies", []):
            if len(chosen) >= top_k:
                break
            if strategy not in chosen:
                chosen.append(strategy)

        score_by_strategy = {item["strategy"]: item for item in ranked}
        pair_ratio = float(profile.get("pair_bundle_ratio") or 0.0)
        willingness = float(profile.get("willingness_distribution", {}).get("mean") or 0.0)
        scarce = len(profile.get("scarce_tasks", []))
        reasons = []
        for strategy in chosen:
            score = score_by_strategy.get(strategy, {}).get("score")
            reason = "作为稳定候选进入 Top-K。"
            if strategy == "baseline_greedy":
                reason = "保留官方风格基线，作为后续策略收益的对照。"
            elif strategy == "scarce_pair" and pair_ratio >= 0.25:
                reason = f"合单候选占比 {pair_ratio:.1%}，需要验证 pair-aware 策略。"
            elif strategy == "expected_cost_greedy" and willingness < 0.5:
                reason = f"平均意愿 {willingness:.3f} 偏低，期望成本排序可降低拒单风险。"
            elif strategy == "coverage_first" and scarce:
                reason = f"存在 {scarce} 个稀缺订单，覆盖优先策略可降低漏单风险。"
            elif score is not None:
                reason = f"本地算法库基准分数 {score:.2f}，在可选策略中表现靠前。"
            reasons.append({"strategy": strategy, "score": score, "reason": reason})

        return {
            "top_k": top_k,
            "selected_strategies": chosen[:top_k],
            "parameter_overrides": {},
            "decision_mode": "mock_agent",
            "reasoning": "未配置 LLM API Key，使用预置 Mock Agent：综合数据画像、本地算法库基准分数和经验规则选择 Top-K。",
            "topk_reasons": reasons[:top_k],
            "analysis_focus": ["courier_task_ratio", "pair_bundle_ratio", "willingness_mean", "conflict_density"],
        }

    def _llm_decide_topk(self, profile: dict, data_analysis: dict, plan: dict, top_k: int, local_library: dict) -> dict:
        fallback = self._mock_topk_fallback(profile, plan, top_k, local_library)
        prompt = {
            "task": "Analyze the data profile and local algorithm benchmark scores, then select the best top-k algorithms and optional parameter overrides for a delivery assignment solver.",
            "constraints": {
                "available_strategies": plan.get("strategies", []),
                "top_k": top_k,
                "time_budget_seconds": plan.get("time_budget"),
                "allowed_parameter_overrides": [
                    "coverage_first.scarcity_weight",
                    "scarce_pair.pair_bonus",
                    "scarce_pair.scarcity_weight",
                    "local_search.local_search_passes",
                    "local_search.local_search_candidates",
                    "destroy_repair.destroy_ratio",
                    "destroy_repair.destroy_attempts",
                    "learned_ranker.expected_weight",
                    "learned_ranker.gain_weight",
                    "learned_ranker.scarcity_weight",
                    "learned_ranker.willingness_weight",
                    "learned_ranker.pair_bonus",
                    "learned_ranker.high_cost_penalty",
                ],
            },
            "data_analysis": data_analysis,
            "local_algorithm_scores": self._ranked_local_scores(local_library),
            "matched_rules": plan.get("matched_rules", []),
            "memory_hits": plan.get("applied_memory", []),
        }
        return self.llm.ask_json(
            "You are the online AutoSolver agent. Return only JSON. Choose strategies that should run now.",
            json.dumps(prompt, ensure_ascii=False),
            fallback,
            timeout=5.0,
        )

    def _llm_tune_after_scores(
        self,
        profile: dict,
        data_analysis: dict,
        portfolio: dict,
        diagnostics: list[dict],
        generated_specs: list[dict],
    ) -> dict:
        fallback = recorded_tuning_decision(profile, generated_specs) or {
            "parameter_trials": [
                {
                    "strategy": spec["strategy"],
                    "parameters": spec.get("parameters", {}),
                    "rationale": spec.get("rationale", ""),
                }
                for spec in generated_specs
            ],
            "diagnosis": "Fallback tuning from score diagnostics.",
            "expected_improvement": "unknown",
        }
        prompt = {
            "task": "Given data analysis and strategy scores, propose bounded parameter trials to improve score within remaining time.",
            "data_analysis": data_analysis,
            "case_type": profile.get("case_type"),
            "portfolio": portfolio,
            "diagnostics": diagnostics,
            "candidate_generated_specs": generated_specs,
            "output_schema": {
                "parameter_trials": [
                    {
                        "strategy": "trial name",
                        "parameters": "dict for learned_ranker or repair strategy",
                        "rationale": "why this should help",
                    }
                ],
                "diagnosis": "brief explanation",
                "expected_improvement": "brief expectation",
            },
        }
        return self.llm.ask_json(
            "You are the online AutoSolver tuning agent. Return only JSON. Do not invent scores.",
            json.dumps(prompt, ensure_ascii=False),
            fallback,
            timeout=5.0,
        )

    @staticmethod
    def _apply_topk_decision(plan: dict, decision: dict, top_k: int) -> dict:
        updated = json.loads(json.dumps(plan, ensure_ascii=False))
        available = list(dict.fromkeys(plan.get("strategies", [])))
        chosen = [
            strategy for strategy in decision.get("selected_strategies", [])
            if strategy in available
        ][:top_k]
        if not chosen:
            chosen = available[:top_k]
        if "baseline_greedy" not in chosen:
            chosen.insert(0, "baseline_greedy")
        updated["strategies"] = list(dict.fromkeys(chosen))[:top_k]
        overrides = decision.get("parameter_overrides", {})
        if isinstance(overrides, dict):
            for strategy, values in overrides.items():
                if isinstance(values, dict):
                    updated.setdefault("strategy_parameters", {}).setdefault(strategy, {}).update(values)
        updated["top_k"] = top_k
        updated["llm_selected_strategies"] = updated["strategies"]
        return updated

    @staticmethod
    def _merge_tuning_trials(generated_specs: list[dict], tuning_decision: dict, case_type: str) -> list[dict]:
        merged = list(generated_specs)
        existing = {item["strategy"] for item in merged}
        for index, trial in enumerate(tuning_decision.get("parameter_trials", [])[:3]):
            if not isinstance(trial, dict):
                continue
            parameters = trial.get("parameters")
            if not isinstance(parameters, dict):
                continue
            name = trial.get("strategy") or f"llm_tuned_ranker_{index + 1}"
            safe_name = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(name)).strip("_").lower()
            if not safe_name:
                safe_name = f"llm_tuned_ranker_{index + 1}"
            if safe_name in existing:
                continue
            from .strategy_synthesizer import render_learned_strategy_code

            spec = {
                "strategy": safe_name,
                "base_strategy": "learned_ranker",
                "source_type": "online_llm_tuned",
                "parameters": parameters,
                "rationale": str(trial.get("rationale") or tuning_decision.get("diagnosis") or "LLM tuning trial."),
                "code": render_learned_strategy_code(
                    safe_name,
                    parameters,
                    str(trial.get("rationale") or "LLM tuning trial."),
                    case_type,
                ),
            }
            existing.add(safe_name)
            merged.append(spec)
        return merged

    @staticmethod
    def _final_submit_code(selected_algorithm: dict, strategy_name: str) -> str:
        code = selected_algorithm.get("code", "")
        source_type = selected_algorithm.get("source_type", "unknown")
        selected_config = selected_algorithm.get("parameters", {})
        if not code or "def solve(" not in code:
            return (
                '"""AutoSolver generated final submit fallback."""\n\n'
                "from __future__ import annotations\n\n"
                "from solver.improved_solver import solve as _solve\n\n\n"
                "def solve(input_text: str) -> list:\n"
                "    return _solve(input_text)\n"
            )
        strategy_code = "\n".join(
            _rewrite_strategy_import(line)
            for line in code.splitlines()
            if not line.strip().startswith("from __future__ import")
        ).replace("def solve(", "def _strategy_solve(", 1)
        return (
            '"""AutoSolver generated final submit file.\n\n'
            f"Selected strategy: {strategy_name}\n"
            f"Source type: {source_type}\n"
            '"""\n\n'
            "from __future__ import annotations\n\n"
            "from solver.parser import parse_problem\n\n"
            f"DEFAULT_SELECTED_CONFIG = {repr(selected_config)}\n\n"
            + strategy_code
            + "\n\n"
            "def solve(input_text: str) -> list:\n"
            "    return _strategy_solve(parse_problem(input_text), config=DEFAULT_SELECTED_CONFIG)\n"
        )

    def solve(
        self,
        input_text: str,
        time_budget: float = 10.0,
        mode: str = "online",
        seed: int = 0,
        persist: bool = True,
        top_k: int = 5,
    ) -> dict:
        run_started = time.perf_counter()
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        problem = parse_problem(input_text)
        profile = extract_case_profile(problem)
        data_analysis = build_data_analysis(profile)
        plan = plan_strategies(profile, time_budget, self.memory_path)
        local_library_plan = json.loads(json.dumps(plan, ensure_ascii=False))
        local_library_plan["strategies"] = list(REGISTRY.keys())
        local_library_budget = max(0.05, time_budget * 0.20)
        local_library = run_portfolio(problem, local_library_plan, local_library_budget, seed)
        local_library_payload = local_library.to_dict(include_solution=False)
        topk_decision = self._llm_decide_topk(profile, data_analysis, plan, top_k, local_library_payload)
        selected_plan = self._apply_topk_decision(plan, topk_decision["decision"], top_k)
        portfolio_budget = max(0.01, time_budget * 0.45)
        portfolio = run_portfolio(problem, selected_plan, portfolio_budget, seed)
        initial_summary = {
            "groups": len(portfolio.best_solution),
            "pair_groups": sum(1 for task_str, _ in portfolio.best_solution if "," in task_str),
            "assigned_couriers": sum(len(couriers) for _, couriers in portfolio.best_solution),
        }
        score_diagnostics = diagnose_score(profile, portfolio.best_evaluation.to_dict(), initial_summary)
        generated_specs = synthesize_strategy_specs(profile, score_diagnostics, max_rounds=3)
        tuning_decision = self._llm_tune_after_scores(
            profile,
            data_analysis,
            portfolio.to_dict(include_solution=False),
            score_diagnostics,
            generated_specs,
        )
        generated_specs = self._merge_tuning_trials(
            generated_specs,
            tuning_decision["decision"],
            profile.get("case_type", "general"),
        )
        iterations = run_iterations(
            problem,
            portfolio,
            max(0.0, time_budget - portfolio_budget),
            seed,
            generated_strategy_specs=generated_specs,
        )
        final_solution = iterations.best_solution
        final_evaluation = iterations.best_evaluation
        if (
            local_library.best_evaluation.valid
            and local_library.best_evaluation.score is not None
            and (
                final_evaluation.score is None
                or local_library.best_evaluation.score + 1e-9 < final_evaluation.score
            )
        ):
            final_solution = local_library.best_solution
            final_evaluation = local_library.best_evaluation
            iterations.best_strategy = local_library.best_strategy
        iteration_payloads = [attempt.to_dict(include_solution=False) for attempt in iterations.attempts]
        selected_code = strategy_code_payload(iterations.best_strategy, selected_plan, generated_specs)
        selected_parameters = {}
        for attempt in iteration_payloads:
            if attempt.get("strategy") == iterations.best_strategy:
                selected_parameters = attempt.get("parameters", {})
                break
        if not selected_parameters:
            for outcome in portfolio.to_dict(include_solution=False).get("outcomes", []):
                if outcome.get("strategy") == iterations.best_strategy:
                    selected_parameters = outcome.get("parameters", {})
                    break
        selected_code["parameters"] = selected_parameters
        final_submit_code = self._final_submit_code(selected_code, iterations.best_strategy)
        output_dir = self.output_root / run_id
        final_submit_path = output_dir / "final_submit.py"
        latest_final_submit_path = self.output_root / "latest_final_submit.py"
        generated_scores = {
            attempt["strategy"]: {
                "status": attempt["status"],
                "score": attempt["score"],
                "runtime_ms": attempt["runtime_ms"],
                "improved_initial_best": (
                    attempt["score"] is not None
                    and portfolio.best_evaluation.score is not None
                    and attempt["score"] + 1e-9 < portfolio.best_evaluation.score
                ),
            }
            for attempt in iteration_payloads
            if attempt["strategy"] in {spec["strategy"] for spec in generated_specs}
        }
        for spec in generated_specs:
            spec["trial_result"] = generated_scores.get(
                spec["strategy"],
                {"status": "not_run", "score": None, "runtime_ms": 0.0, "improved_initial_best": False},
            )
        result = {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "seed": seed,
            "time_budget": time_budget,
            "input_text": input_text,
            "runtime_ms": round((time.perf_counter() - run_started) * 1000.0, 3),
            "case_profile": profile,
            "data_analysis": data_analysis,
            "strategy_plan": selected_plan,
            "candidate_strategy_plan": plan,
            "local_library_evaluation": local_library_payload,
            "online_agent": {
                "topk_decision": topk_decision,
                "tuning_decision": tuning_decision,
                "llm_required": True,
            },
            "portfolio": portfolio.to_dict(include_solution=False),
            "score_diagnostics": score_diagnostics,
            "generated_strategies": generated_specs,
            "iterations": iteration_payloads,
            "selected_strategy": iterations.best_strategy,
            "selected_algorithm": {**selected_code, "final_submit_path": str(final_submit_path)},
            "final_submit": {
                "path": str(final_submit_path),
                "latest_path": str(latest_final_submit_path),
                "code": final_submit_code,
            },
            "final_evaluation": final_evaluation.to_dict(),
            "solution_summary": {
                "groups": len(final_solution),
                "pair_groups": sum(1 for task_str, _ in final_solution if "," in task_str),
                "assigned_couriers": sum(len(couriers) for _, couriers in final_solution),
            },
            "solution": final_solution,
        }
        if persist:
            self._write_json(self.log_root / f"{run_id}.json", result)
            self._write_json(output_dir / "case_profile.json", profile)
            self._write_json(output_dir / "data_analysis.json", data_analysis)
            self._write_json(output_dir / "strategy_plan.json", selected_plan)
            self._write_json(output_dir / "score_diagnostics.json", score_diagnostics)
            self._write_json(output_dir / "generated_strategies.json", generated_specs)
            self._write_json(output_dir / "solution.json", final_solution)
            self._write_text(final_submit_path, final_submit_code)
            self._write_text(latest_final_submit_path, final_submit_code)
            self._write_text(self.output_root / "final_submit.py", final_submit_code)
        return result


def run_online(
    input_text: str,
    time_budget: float = 10.0,
    mode: str = "online",
    seed: int = 0,
    persist: bool = True,
    top_k: int = 5,
    llm_config: dict | None = None,
) -> dict:
    return OnlineAgent(llm_config=llm_config).solve(input_text, time_budget, mode, seed, persist, top_k)


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute the online AutoSolver agent.")
    parser.add_argument("case")
    parser.add_argument("--time-budget", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()
    result = run_online(
        Path(args.case).read_text(encoding="utf-8"),
        args.time_budget,
        "cli",
        args.seed,
        not args.no_persist,
        args.top_k,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
