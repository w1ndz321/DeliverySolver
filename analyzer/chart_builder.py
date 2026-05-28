"""Convert case profiles into chart-ready frontend data."""

from __future__ import annotations


def build_data_analysis(profile: dict) -> dict:
    """Return compact analysis facts and chart series for the UI and LLM prompts."""
    willingness = profile.get("willingness_distribution", {})
    expected_cost = profile.get("expected_cost_distribution", {})
    gain = profile.get("gain_distribution", {})
    per_task = profile.get("candidate_count_per_task_summary", {})
    per_courier = profile.get("candidate_count_per_courier_summary", {})
    scarce_tasks = profile.get("scarce_tasks", [])
    metrics = {
        "orders": profile.get("num_tasks", 0),
        "couriers": profile.get("num_couriers", 0),
        "candidates": profile.get("num_candidates", 0),
        "courier_task_ratio": profile.get("courier_task_ratio", 0.0),
        "pair_bundle_ratio": profile.get("pair_bundle_ratio", 0.0),
        "single_bundle_ratio": profile.get("single_bundle_ratio", 0.0),
        "avg_bundle_size": profile.get("avg_bundle_size", 0.0),
        "willingness_mean": willingness.get("mean", 0.0),
        "positive_gain_ratio": profile.get("positive_gain_ratio", 0.0),
        "conflict_density": profile.get("conflict_density", 0.0),
        "scarce_task_count": len(scarce_tasks),
    }
    charts = [
        {
            "id": "bundle_mix",
            "title": "订单组合结构",
            "type": "bar",
            "unit": "ratio",
            "series": [
                {"label": "单单候选", "value": profile.get("single_bundle_ratio", 0.0)},
                {"label": "合单候选", "value": profile.get("pair_bundle_ratio", 0.0)},
            ],
        },
        {
            "id": "willingness_distribution",
            "title": "接单意愿分布",
            "type": "bar",
            "unit": "value",
            "series": _quantile_series(willingness),
        },
        {
            "id": "cost_gain_distribution",
            "title": "成本与收益分布",
            "type": "bar",
            "unit": "score",
            "series": [
                {"label": "期望成本 p50", "value": expected_cost.get("p50", 0.0)},
                {"label": "期望成本 p90", "value": expected_cost.get("p90", 0.0)},
                {"label": "收益 p50", "value": gain.get("p50", 0.0)},
                {"label": "收益 p90", "value": gain.get("p90", 0.0)},
            ],
        },
        {
            "id": "candidate_degree",
            "title": "候选覆盖度",
            "type": "bar",
            "unit": "count",
            "series": [
                {"label": "订单候选 p25", "value": per_task.get("p25", 0.0)},
                {"label": "订单候选 p50", "value": per_task.get("p50", 0.0)},
                {"label": "订单候选 p75", "value": per_task.get("p75", 0.0)},
                {"label": "骑手候选 p50", "value": per_courier.get("p50", 0.0)},
            ],
        },
    ]
    if scarce_tasks:
        charts.append(
            {
                "id": "scarce_tasks",
                "title": "最稀缺订单",
                "type": "bar",
                "unit": "count",
                "series": [
                    {"label": item["task_id"], "value": item["candidate_count"]}
                    for item in scarce_tasks[:8]
                ],
            }
        )
    return {
        "scene": {
            "case_type": profile.get("case_type", "general"),
            "labels": profile.get("case_labels", []),
            "summary": _scene_summary(profile),
            "rules": profile.get("case_label_rules", []),
        },
        "metrics": metrics,
        "charts": charts,
        "feature_table": [
            {"name": key, "value": value, "role": _feature_role(key)}
            for key, value in metrics.items()
        ],
    }


def _quantile_series(distribution: dict) -> list[dict]:
    return [
        {"label": "p10", "value": distribution.get("p10", 0.0)},
        {"label": "p25", "value": distribution.get("p25", 0.0)},
        {"label": "p50", "value": distribution.get("p50", 0.0)},
        {"label": "p75", "value": distribution.get("p75", 0.0)},
        {"label": "p90", "value": distribution.get("p90", 0.0)},
    ]


def _scene_summary(profile: dict) -> str:
    labels = profile.get("case_labels", [])
    if not labels or labels == ["general"]:
        return "供需、合单和意愿分布未触发明显专项规则，默认按通用排序策略和局部改进组合处理。"
    mapping = {
        "scarce_couriers": "骑手供给偏紧，需要优先保障覆盖与稀缺订单。",
        "pair_rich": "合单候选充足，需要测试 pair-aware 策略。",
        "low_willingness": "接单意愿偏低，拒单风险会明显影响总分。",
        "low_gain": "正收益候选不足，策略应避免低价值指派。",
        "scarce_tasks": "部分订单候选稀缺，需要提前保留可用骑手。",
    }
    return " ".join(mapping.get(label, label) for label in labels)


def _feature_role(name: str) -> str:
    roles = {
        "orders": "scale",
        "couriers": "supply",
        "candidates": "search_space",
        "courier_task_ratio": "supply",
        "pair_bundle_ratio": "bundle",
        "single_bundle_ratio": "bundle",
        "avg_bundle_size": "bundle",
        "willingness_mean": "risk",
        "positive_gain_ratio": "value",
        "conflict_density": "search",
        "scarce_task_count": "coverage",
    }
    return roles.get(name, "feature")
