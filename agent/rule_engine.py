"""Immutable rules mapping data profiles to stable strategy options."""

from __future__ import annotations


def build_static_plan(case_profile: dict, time_budget: float) -> dict:
    strategies = ["baseline_greedy", "expected_cost_greedy", "gain_greedy", "coverage_first"]
    parameters: dict[str, dict] = {
        "coverage_first": {"scarcity_weight": 1.0},
        "scarce_pair": {"pair_bonus": 12.0, "scarcity_weight": 0.25},
        "local_search": {"local_search_passes": 2, "local_search_candidates": 200},
        "destroy_repair": {"destroy_ratio": 0.2, "destroy_attempts": 4},
    }
    rules: list[dict] = []

    scarce_ratio = len(case_profile.get("scarce_tasks", [])) / max(1, case_profile["num_tasks"])
    if case_profile["courier_task_ratio"] <= 1.25:
        strategies.append("scarce_pair")
        parameters["scarce_pair"]["pair_bonus"] = 20.0
        rules.append({"rule": "courier_supply_tight", "reason": "骑手/订单比低，优先测试合单覆盖。"})
    if case_profile["pair_bundle_ratio"] >= 0.30:
        if "scarce_pair" not in strategies:
            strategies.append("scarce_pair")
        parameters["scarce_pair"]["pair_bonus"] = max(parameters["scarce_pair"]["pair_bonus"], 15.0)
        rules.append({"rule": "pair_rich_input", "reason": "双订单候选占比较高，启用合单策略。"})
    if scarce_ratio >= 0.20:
        parameters["coverage_first"]["scarcity_weight"] = 1.8
        rules.append({"rule": "many_scarce_tasks", "reason": "稀缺订单较多，提高覆盖优先级。"})
    if case_profile["willingness_distribution"]["variance"] >= 0.04:
        parameters["local_search"]["local_search_candidates"] = 300
        rules.append({"rule": "diverse_willingness", "reason": "接单意愿差异大，搜索更优骑手替换。"})
    if case_profile["conflict_density"] >= 0.12:
        parameters["local_search"]["local_search_candidates"] = 120
        rules.append({"rule": "dense_conflicts", "reason": "候选冲突密集，限制局部邻域以控制耗时。"})

    if time_budget >= 0.3:
        strategies.append("local_search")
    if time_budget >= 0.8 and ("scarce_pair" in strategies or case_profile["conflict_density"] >= 0.08):
        strategies.append("destroy_repair")
    return {
        "strategies": list(dict.fromkeys(strategies)),
        "strategy_parameters": parameters,
        "matched_rules": rules,
    }
