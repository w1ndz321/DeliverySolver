"""Generate post-run Markdown and optional charts without blocking serving."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def generate_run_report(run: dict, output_dir: str | Path) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    profile = run["case_profile"]
    evaluation = run["final_evaluation"]
    plan = run["strategy_plan"]
    lines = [
        f"# AutoSolver Run Report: {run['run_id']}",
        "",
        "## Case Profile",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Tasks | {profile['num_tasks']} |",
        f"| Couriers | {profile['num_couriers']} |",
        f"| Candidates | {profile['num_candidates']} |",
        f"| Courier / task ratio | {profile['courier_task_ratio']:.3f} |",
        f"| Pair bundle ratio | {profile['pair_bundle_ratio']:.3f} |",
        f"| Positive gain ratio | {profile['positive_gain_ratio']:.3f} |",
        f"| Conflict density | {profile['conflict_density']:.3f} |",
        "",
        f"Case type: `{profile['case_type']}`",
        "",
        "## Strategy Plan",
        "",
        "Matched rules:",
    ]
    if plan["matched_rules"]:
        lines.extend(f"- `{rule['rule']}`: {rule['reason']}" for rule in plan["matched_rules"])
    else:
        lines.append("- General-case default portfolio.")
    lines.extend(
        [
            "",
            "## Portfolio Results",
            "",
            "| Strategy | Status | Score | Runtime (ms) |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for outcome in run["portfolio"]["outcomes"] + run.get("iterations", []):
        score = "-" if outcome.get("score") is None else f"{outcome['score']:.4f}"
        lines.append(f"| {outcome['strategy']} | {outcome['status']} | {score} | {outcome['runtime_ms']:.2f} |")
    decomposition = evaluation["score_decomposition"]
    lines.extend(
        [
            "",
            "## Selected Result",
            "",
            f"- Strategy: `{run['selected_strategy']}`",
            f"- Score: `{evaluation['score']:.6f}`",
            f"- Covered tasks: `{evaluation['covered_tasks']}/{profile['num_tasks']}`",
            f"- Used couriers: `{evaluation['used_couriers']}`",
            f"- Uncovered penalty: `{decomposition['uncovered_penalty']:.6f}`",
            f"- Rejection risk cost: `{decomposition['rejection_risk_cost']:.6f}`",
            "",
        ]
    )
    report_path = output / "run_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    _generate_charts(profile, output / "charts")
    return report_path


def _generate_charts(profile: dict, charts_dir: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    charts_dir.mkdir(parents=True, exist_ok=True)
    for key, title in [
        ("willingness_distribution", "Willingness distribution quantiles"),
        ("total_score_distribution", "Total score distribution quantiles"),
        ("expected_cost_distribution", "Expected cost distribution quantiles"),
        ("gain_distribution", "Gain distribution quantiles"),
    ]:
        values = profile[key]
        labels = ["p10", "p25", "p50", "p75", "p90"]
        fig, ax = plt.subplots(figsize=(6, 3.3))
        ax.bar(labels, [values[label] for label in labels], color="#24645c")
        ax.set_title(title)
        fig.tight_layout()
        fig.savefig(charts_dir / f"{key}.png", dpi=140)
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a post-run report from one online log.")
    parser.add_argument("run_log")
    parser.add_argument("--output", default="reports/latest_run")
    args = parser.parse_args()
    run = json.loads(Path(args.run_log).read_text(encoding="utf-8"))
    print(generate_run_report(run, args.output))


if __name__ == "__main__":
    main()
