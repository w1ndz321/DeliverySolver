"""Fast case profiling for strategy selection."""

from __future__ import annotations

from collections import Counter
from math import comb
from statistics import fmean, pvariance

from solver.parser import Problem, parse_problem


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(values: list[float]) -> dict:
    if not values:
        return {"mean": 0.0, "variance": 0.0, "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
    return {
        "mean": round(fmean(values), 6),
        "variance": round(pvariance(values), 6),
        "p10": round(_quantile(values, 0.10), 6),
        "p25": round(_quantile(values, 0.25), 6),
        "p50": round(_quantile(values, 0.50), 6),
        "p75": round(_quantile(values, 0.75), 6),
        "p90": round(_quantile(values, 0.90), 6),
    }


def _count_summary(counts: dict[str, int]) -> dict:
    values = [float(value) for value in counts.values()]
    distribution = _distribution(values)
    return {
        "min": min(counts.values(), default=0),
        "max": max(counts.values(), default=0),
        "mean": distribution["mean"],
        "p25": distribution["p25"],
        "p50": distribution["p50"],
        "p75": distribution["p75"],
    }


def case_label_rules(profile: dict) -> list[dict]:
    scarce_task_threshold = max(1, profile["num_tasks"] // 5)
    rules = [
        {
            "label": "scarce_couriers",
            "metric": "courier_task_ratio",
            "value": profile["courier_task_ratio"],
            "operator": "<=",
            "threshold": 1.1,
            "matched": profile["courier_task_ratio"] <= 1.1,
            "reason": "骑手/订单比例偏低，供给紧张。",
        },
        {
            "label": "pair_rich",
            "metric": "pair_bundle_ratio",
            "value": profile["pair_bundle_ratio"],
            "operator": ">=",
            "threshold": 0.35,
            "matched": profile["pair_bundle_ratio"] >= 0.35,
            "reason": "合单候选占比高，合并搜索可能有效。",
        },
        {
            "label": "low_willingness",
            "metric": "willingness_mean",
            "value": profile["willingness_distribution"]["mean"],
            "operator": "<",
            "threshold": 0.2,
            "matched": profile["willingness_distribution"]["mean"] < 0.2,
            "reason": "平均接单意愿低，拒单风险会影响总分。",
        },
        {
            "label": "low_gain",
            "metric": "positive_gain_ratio",
            "value": profile["positive_gain_ratio"],
            "operator": "<",
            "threshold": 0.35,
            "matched": profile["positive_gain_ratio"] < 0.35,
            "reason": "正收益候选比例低，应避免低价值指派。",
        },
        {
            "label": "scarce_tasks",
            "metric": "scarce_task_count",
            "value": len(profile["scarce_tasks"]),
            "operator": ">=",
            "threshold": scarce_task_threshold,
            "matched": len(profile["scarce_tasks"]) >= scarce_task_threshold,
            "reason": "稀缺订单较多，需要保护可用骑手。",
        },
    ]
    return rules


def _case_labels(profile: dict) -> list[str]:
    labels = [rule["label"] for rule in case_label_rules(profile) if rule["matched"]]
    return labels or ["general"]


def extract_case_profile(source: str | Problem) -> dict:
    """Produce a JSON-safe case profile used by agents and reports."""
    problem = parse_problem(source) if isinstance(source, str) else source
    candidates = problem.candidates
    sizes = [candidate.task_count for candidate in candidates]
    size_counts = Counter(sizes)
    expected_costs = [candidate.expected_cost for candidate in candidates]
    gains = [candidate.gain for candidate in candidates]
    willingness = [candidate.willingness for candidate in candidates]
    total_scores = [candidate.total_score for candidate in candidates]
    per_task = {task: len(problem.candidates_by_task.get(task, [])) for task in sorted(problem.task_ids)}
    per_courier = {
        courier: len(problem.candidates_by_courier.get(courier, []))
        for courier in sorted(problem.courier_ids)
    }
    candidate_counts = [float(value) for value in per_task.values()]
    scarcity_cutoff = _quantile(candidate_counts, 0.25)
    median_count = _quantile(candidate_counts, 0.50)
    scarce_tasks = [
        {"task_id": task, "candidate_count": count}
        for task, count in sorted(per_task.items(), key=lambda item: (item[1], item[0]))
        if count <= scarcity_cutoff and count < median_count * 0.75
    ]

    courier_value: list[dict] = []
    for courier, records in problem.candidates_by_courier.items():
        courier_value.append(
            {
                "courier_id": courier,
                "candidate_count": len(records),
                "avg_willingness": round(fmean(row.willingness for row in records), 6),
                "best_gain": round(max(row.gain for row in records), 6),
            }
        )
    courier_value.sort(key=lambda row: (-row["best_gain"], -row["avg_willingness"], row["courier_id"]))

    total_candidate_pairs = comb(len(candidates), 2) if len(candidates) >= 2 else 0
    shared_task_conflicts = sum(comb(count, 2) for count in per_task.values() if count >= 2)
    shared_courier_conflicts = sum(comb(count, 2) for count in per_courier.values() if count >= 2)
    approximate_conflicts = min(total_candidate_pairs, shared_task_conflicts + shared_courier_conflicts)
    profile = {
        "schema_version": 1,
        "num_tasks": problem.num_tasks,
        "num_couriers": problem.num_couriers,
        "num_candidates": len(candidates),
        "courier_task_ratio": round(problem.num_couriers / problem.num_tasks, 6) if problem.num_tasks else 0.0,
        "num_task_lists": len(problem.task_lists),
        "single_bundle_ratio": round(size_counts.get(1, 0) / len(candidates), 6) if candidates else 0.0,
        "pair_bundle_ratio": round(size_counts.get(2, 0) / len(candidates), 6) if candidates else 0.0,
        "avg_bundle_size": round(fmean(sizes), 6) if sizes else 0.0,
        "candidate_count_per_task": per_task,
        "candidate_count_per_task_summary": _count_summary(per_task),
        "candidate_count_per_courier": per_courier,
        "candidate_count_per_courier_summary": _count_summary(per_courier),
        "scarce_tasks": scarce_tasks,
        "high_value_couriers": courier_value[: min(10, len(courier_value))],
        "willingness_distribution": _distribution(willingness),
        "total_score_distribution": _distribution(total_scores),
        "expected_cost_distribution": _distribution(expected_costs),
        "gain_distribution": _distribution(gains),
        "positive_gain_ratio": round(
            sum(1 for gain in gains if gain > 0.0) / len(gains), 6
        ) if gains else 0.0,
        "conflict_density": round(approximate_conflicts / total_candidate_pairs, 6)
        if total_candidate_pairs
        else 0.0,
        "skipped_input_rows": problem.skipped_rows,
        "formulas": {
            "expected_cost": "willingness * total_score + (1 - willingness) * 100 * task_count",
            "gain": "100 * task_count - expected_cost",
            "conflict_density": "upper-bounded candidate-pair conflicts estimated from shared task/courier degrees",
        },
    }
    profile["case_labels"] = _case_labels(profile)
    profile["case_type"] = "+".join(profile["case_labels"])
    profile["case_label_rules"] = case_label_rules(profile)
    return profile
