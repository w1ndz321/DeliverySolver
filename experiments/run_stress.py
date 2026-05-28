"""Replay multiple cases through the online agent without mutating memory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.online_agent import OnlineAgent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="+")
    parser.add_argument("--budget", type=float, default=2.0)
    parser.add_argument("--output", default="outputs/stress_result.json")
    args = parser.parse_args()
    agent = OnlineAgent()
    results = []
    for case in args.cases:
        run = agent.solve(Path(case).read_text(encoding="utf-8"), args.budget, mode="stress", persist=False)
        results.append(
            {
                "case": case,
                "case_type": run["case_profile"]["case_type"],
                "selected_strategy": run["selected_strategy"],
                "score": run["final_evaluation"]["score"],
                "covered_tasks": run["final_evaluation"]["covered_tasks"],
            }
        )
    path = ROOT / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
