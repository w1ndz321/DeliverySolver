"""Run every stable strategy on one case for offline comparison."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.strategy_planner import plan_strategies
from analyzer.feature_extractor import extract_case_profile
from solver.parser import parse_problem
from solver.portfolio import REGISTRY, run_portfolio


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case")
    parser.add_argument("--budget", type=float, default=3.0)
    parser.add_argument("--output", default="outputs/ablation_result.json")
    args = parser.parse_args()
    problem = parse_problem(Path(args.case).read_text(encoding="utf-8"))
    profile = extract_case_profile(problem)
    plan = plan_strategies(profile, args.budget)
    plan["strategies"] = list(REGISTRY)
    result = run_portfolio(problem, plan, args.budget).to_dict(include_solution=False)
    payload = {"case_profile": profile, "strategy_plan": plan, "portfolio": result}
    path = ROOT / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
