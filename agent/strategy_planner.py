"""Combine static rules with validated offline rule memory."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .rule_engine import build_static_plan


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = Path(os.environ.get("AUTOSOLVER_STATE_DIR", str(PROJECT_ROOT)))
DEFAULT_MEMORY_PATH = STATE_ROOT / "logs" / "rule_memory.json"


def load_rule_memory(path: str | Path | None = None) -> dict:
    memory_path = Path(path) if path else DEFAULT_MEMORY_PATH
    if not memory_path.exists():
        return {"version": 1, "case_types": {}}
    try:
        return json.loads(memory_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "case_types": {}}


def _existing_strategy_modules(modules: dict) -> dict:
    existing = {}
    for name, module in modules.items():
        path = Path(module.get("module_path", ""))
        if path.is_file():
            existing[name] = module
    return existing


def plan_strategies(
    case_profile: dict,
    time_budget: float,
    memory_path: str | Path | None = None,
) -> dict:
    plan = build_static_plan(case_profile, time_budget)
    memory = load_rule_memory(memory_path)
    learned = memory.get("case_types", {}).get(case_profile["case_type"], {})
    learned_strategies = learned.get("preferred_strategies", [])
    applied_memory: list[dict] = []
    for strategy in learned_strategies:
        if strategy not in plan["strategies"]:
            plan["strategies"].append(strategy)
        applied_memory.append({"strategy": strategy, "evidence": learned.get("evidence_runs", 0)})
    for strategy, updates in learned.get("strategy_parameters", {}).items():
        plan["strategy_parameters"].setdefault(strategy, {}).update(updates)
    strategy_modules = _existing_strategy_modules(learned.get("strategy_modules", {}))
    if strategy_modules:
        plan["strategy_modules"] = strategy_modules
        for strategy in strategy_modules:
            if strategy not in plan["strategies"]:
                plan["strategies"].append(strategy)
            applied_memory.append({"strategy": strategy, "evidence": learned.get("evidence_runs", 0)})
    plan.update(
        {
            "case_type": case_profile["case_type"],
            "time_budget": time_budget,
            "memory_version": memory.get("version", 1),
            "applied_memory": applied_memory,
        }
    )
    return plan
