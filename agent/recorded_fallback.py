"""Recorded demo fallback outputs for unstable live LLM calls.

These payloads are based on an actual large_seed301 online/offline run. They are
used only as Agent decision fallbacks when the LLM is not configured or times
out, so the demo can still show a complete closed-loop decision trace.
"""

from __future__ import annotations


RECORDED_FALLBACK_SOURCE = "recorded_large_seed301_closed_loop_2026_05_27"

RECORDED_LARGE_SEED301_METRICS = {
    "orders": 40,
    "couriers": 80,
    "candidates": 33780,
    "courier_task_ratio": 2.0,
    "pair_bundle_ratio": 0.905269,
    "willingness_mean": 0.299973,
    "positive_gain_ratio": 1.0,
    "conflict_density": 0.103204,
    "scarce_task_count": 0,
}

RECORDED_LOCAL_SCORES = {
    "local_search": 749.6339555705864,
    "destroy_repair": 749.6339555705864,
    "expected_cost_greedy": 968.7500265999997,
    "learned_ranker": 968.7500265999997,
    "coverage_first": 973.6952161,
    "scarce_pair": 1007.5828827999999,
    "gain_greedy": 1315.0558861,
    "baseline_greedy": 2097.6575390000007,
}

RECORDED_TOPK_ORDER = [
    "baseline_greedy",
    "destroy_repair",
    "local_search",
    "expected_cost_greedy",
    "coverage_first",
]

RECORDED_TUNING_TRIALS = [
    {
        "strategy": "online_risk_guard_pair_rich",
        "parameters": {
            "expected_weight": 1.0,
            "gain_weight": 0.05,
            "scarcity_weight": 0.25,
            "willingness_weight": 18.0,
            "pair_bonus": 0.0,
            "high_cost_penalty": 1.2,
            "repair": True,
        },
        "rationale": "Reserve high-willingness couriers when rejection dominates.",
    },
    {
        "strategy": "online_pair_guard_pair_rich",
        "parameters": {
            "expected_weight": 1.0,
            "gain_weight": 0.2,
            "scarcity_weight": 0.8,
            "willingness_weight": 4.0,
            "pair_bonus": 18.0,
            "high_cost_penalty": 0.5,
            "repair": True,
        },
        "rationale": "Try pair bundles when the data exposes enough pair supply.",
    },
    {
        "strategy": "online_balanced_ranker_pair_rich",
        "parameters": {
            "expected_weight": 1.0,
            "gain_weight": 0.15,
            "scarcity_weight": 0.25,
            "willingness_weight": 8.0,
            "pair_bonus": 8.0,
            "high_cost_penalty": 0.5,
            "repair": True,
        },
        "rationale": "Balanced fallback generated from score diagnostics.",
    },
]


def is_recorded_large_seed301(profile: dict) -> bool:
    """Return True when the profile matches the recorded large_seed301 instance."""
    if profile.get("num_tasks") != RECORDED_LARGE_SEED301_METRICS["orders"]:
        return False
    if profile.get("num_couriers") != RECORDED_LARGE_SEED301_METRICS["couriers"]:
        return False
    if profile.get("num_candidates") != RECORDED_LARGE_SEED301_METRICS["candidates"]:
        return False
    pair_ratio = float(profile.get("pair_bundle_ratio") or 0.0)
    willingness = float(profile.get("willingness_distribution", {}).get("mean") or 0.0)
    return abs(pair_ratio - RECORDED_LARGE_SEED301_METRICS["pair_bundle_ratio"]) < 1e-6 and abs(
        willingness - RECORDED_LARGE_SEED301_METRICS["willingness_mean"]
    ) < 1e-6


def _ranked_scores(local_library: dict) -> list[dict]:
    outcomes = local_library.get("outcomes", []) if isinstance(local_library, dict) else []
    rows = []
    for item in outcomes:
        if item.get("status") != "ok" or item.get("score") is None:
            continue
        rows.append(
            {
                "strategy": item.get("strategy"),
                "score": item.get("score"),
                "runtime_ms": item.get("runtime_ms"),
                "status": item.get("status"),
            }
        )
    return sorted(rows, key=lambda item: (item["score"], item.get("strategy") or ""))


def recorded_topk_decision(profile: dict, plan: dict, top_k: int, local_library: dict) -> dict | None:
    if not is_recorded_large_seed301(profile):
        return None

    available = list(dict.fromkeys(plan.get("strategies", [])))
    chosen = [strategy for strategy in RECORDED_TOPK_ORDER if strategy in available]
    for strategy in available:
        if len(chosen) >= top_k:
            break
        if strategy not in chosen:
            chosen.append(strategy)
    chosen = chosen[:top_k]

    live_scores = {item["strategy"]: item for item in _ranked_scores(local_library)}
    reason_text = {
        "baseline_greedy": "保留官方风格基线，作为后续策略收益的对照。",
        "destroy_repair": "真实录制闭环中该策略与 local_search 并列最优，适合修复局部高成本分配。",
        "local_search": "真实录制闭环中本地基准分数最低，作为在线阶段主候选。",
        "expected_cost_greedy": "平均意愿约 0.300，期望成本排序可降低拒单风险。",
        "coverage_first": "作为覆盖保护候选，防止调参策略牺牲订单覆盖。",
    }
    topk_reasons = []
    for strategy in chosen:
        score = live_scores.get(strategy, {}).get("score", RECORDED_LOCAL_SCORES.get(strategy))
        topk_reasons.append(
            {
                "strategy": strategy,
                "score": score,
                "reason": reason_text.get(strategy, "录制闭环 fallback 中保留的稳定候选策略。"),
            }
        )

    agent_output = {
        "observation": [
            "orders=40、couriers=80，骑手供给不紧张。",
            "pair_bundle_ratio=90.53%，合单候选非常充足。",
            "willingness_mean=0.300，意愿偏低，需要关注拒单风险。",
            "local_search/destroy_repair 在本地算法库基准中并列最优，分数 749.6339555705864。",
        ],
        "decision": f"选择 Top-{len(chosen)}：{' / '.join(chosen)}。",
        "why": "先保留 baseline 做对照，再优先选择本地分数最好的修复/局部搜索策略，同时加入期望成本和覆盖保护策略做风险对冲。",
    }
    return {
        "top_k": top_k,
        "selected_strategies": chosen,
        "parameter_overrides": {},
        "decision_mode": "recorded_agent_fallback",
        "fallback_source": RECORDED_FALLBACK_SOURCE,
        "recorded_dataset": "large_seed301",
        "reasoning": "DeepSeek 未配置或调用超时，展示一次真实跑通 large_seed301 后记录的在线 Agent 决策。",
        "topk_reasons": topk_reasons,
        "analysis_focus": ["courier_task_ratio", "pair_bundle_ratio", "willingness_mean", "conflict_density"],
        "recorded_metrics": RECORDED_LARGE_SEED301_METRICS,
        "recorded_local_scores": RECORDED_LOCAL_SCORES,
        "agent_output": agent_output,
    }


def recorded_tuning_decision(profile: dict, generated_specs: list[dict]) -> dict | None:
    if not is_recorded_large_seed301(profile):
        return None
    generated_names = {item.get("strategy") for item in generated_specs}
    trials = []
    for trial in RECORDED_TUNING_TRIALS:
        # Keep the recorded names even if the synthesizer already produced them;
        # the merger will avoid duplicate generated modules.
        trials.append(dict(trial))
    agent_output = {
        "observation": [
            "当前最优已经来自 local_search，在线调参不应破坏稳定解。",
            "pair-rich 但意愿偏低，因此试验 high willingness guard、pair guard 和 balanced ranker 三类参数。",
            f"合成器已给出 {len(generated_names)} 个候选，调参 Agent 只补充有边界的参数试验。",
        ],
        "decision": "生成 3 个 learned_ranker 参数试验；若 10 秒预算内没有超过 local_search，则保留 local_search。",
        "why": "在线闭环目标是快速返回当前最优代码，调参只做有限探索，不修改源代码库。",
    }
    return {
        "parameter_trials": trials,
        "decision_mode": "recorded_agent_fallback",
        "fallback_source": RECORDED_FALLBACK_SOURCE,
        "recorded_dataset": "large_seed301",
        "diagnosis": "录制闭环显示 local_search 已达到 749.6339555705864；调参方向聚焦意愿风险、合单结构和均衡排序。",
        "expected_improvement": "bounded; final result keeps local_search unless a trial beats 749.6339555705864",
        "agent_output": agent_output,
    }
