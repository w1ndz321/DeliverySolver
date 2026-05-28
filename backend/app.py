#!/usr/bin/env python3
"""Serve the AutoSolver landing page, demo API and event stream."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import inspect
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORTS))

from analyzer.feature_extractor import extract_case_profile
from analyzer.chart_builder import build_data_analysis
from backend.scenarios import PROJECT_ROOT, SCENARIOS, analyze_input, scenario_payload, scenario_text
from agent.strategy_planner import DEFAULT_MEMORY_PATH, load_rule_memory, plan_strategies
from agent.rule_engine import build_static_plan
from agent.llm_client import LLMClient, normalize_chat_url
from agent.recorded_fallback import RECORDED_FALLBACK_SOURCE
from solver.parser import parse_problem
from solver.portfolio import REGISTRY


STATIC_ROOT = PROJECT_ROOT / "frontend"
STATE_ROOT = Path(os.environ.get("AUTOSOLVER_STATE_DIR", str(PROJECT_ROOT)))
LARGE_SEED = PROJECT_ROOT / "data" / "large_seed301.txt"
DEEPSEEK_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")
DEFAULT_OFFLINE_CONFIG = {
    "max_iterations": 5,
    "patience": 2,
    "min_improvement": 0.001,
}


def llm_config_from_payload(payload: dict) -> dict:
    config = payload.get("llm") if isinstance(payload.get("llm"), dict) else {}
    return {
        "api_key": payload.get("api_key") or config.get("api_key") or "",
        "model": payload.get("model") or config.get("model") or "deepseek-chat",
        "base_url": payload.get("base_url") or config.get("base_url") or DEEPSEEK_URL,
    }


def offline_config_from_payload(payload: dict | None) -> dict:
    payload = payload or {}
    config = payload.get("offline") if isinstance(payload.get("offline"), dict) else {}
    return {
        "max_iterations": max(1, min(20, int(config.get("max_iterations", DEFAULT_OFFLINE_CONFIG["max_iterations"])))),
        "patience": max(1, min(10, int(config.get("patience", DEFAULT_OFFLINE_CONFIG["patience"])))),
        "min_improvement": max(0.0, min(0.5, float(config.get("min_improvement", DEFAULT_OFFLINE_CONFIG["min_improvement"])))),
    }


def dataset_from_payload(payload: dict | None) -> tuple[str, str, str]:
    payload = payload or {}
    dataset = payload.get("dataset") if isinstance(payload.get("dataset"), dict) else {}
    input_text = str(payload.get("input_text") or dataset.get("input_text") or "").strip()
    dataset_name = str(dataset.get("name") or payload.get("dataset_name") or "").strip()
    if input_text:
        return input_text, dataset_name or "uploaded_dataset", "uploaded"
    return LARGE_SEED.read_text(encoding="utf-8"), dataset_name or "large_seed301", "default"


def redact_llm_config(config: dict) -> dict:
    return {
        "configured": bool(str(config.get("api_key") or "").strip()),
        "model": str(config.get("model") or "deepseek-chat").strip() or "deepseek-chat",
        "base_url": normalize_chat_url(str(config.get("base_url") or DEEPSEEK_URL).strip() or DEEPSEEK_URL),
    }


def test_llm_connection(config: dict) -> dict:
    if not str(config.get("api_key") or "").strip():
        raise ValueError("api_key is required")
    client = LLMClient(config)
    result = client.ask_json(
        "You are a connectivity test endpoint. Return only JSON.",
        '{"task":"Return exactly {\\"ok\\":true} as JSON."}',
        {"ok": False},
        timeout=6.0,
    )
    decision = result.get("decision") if isinstance(result.get("decision"), dict) else {}
    return {
        "ok": result.get("status") == "ok" and bool(decision.get("ok")),
        "status": result.get("status"),
        "used_llm": result.get("used_llm"),
        "model": result.get("model") or client.model,
        "error": result.get("error"),
    }


def run_online_agent(
    input_text: str,
    time_budget: float,
    seed: int,
    persist: bool = True,
    top_k: int = 5,
    llm_config: dict | None = None,
    state_root: str | Path | None = None,
) -> dict:
    """Run the root-level serving agent without mixing its package with demo agent imports."""
    script = (
        "import json, sys; "
        "from agent.online_agent import run_online; "
        "p=json.load(sys.stdin); "
        "r=run_online(p['input_text'], p['time_budget'], 'api', p['seed'], p.get('persist', True), p.get('top_k', 5), p.get('llm_config')); "
        "print(json.dumps(r, ensure_ascii=False))"
    )
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    if state_root:
        env["AUTOSOLVER_STATE_DIR"] = str(state_root)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(
            {
                "input_text": input_text,
                "time_budget": time_budget,
                "seed": seed,
                "persist": persist,
                "top_k": top_k,
                "llm_config": llm_config or {},
            }
        ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(PROJECT_ROOT),
        env=env,
        timeout=max(18.0, time_budget + 28.0),
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr[-300:] or "online agent failed")
    return json.loads(completed.stdout)


def run_offline_agent(
    llm_config: dict | None = None,
    state_root: str | Path | None = None,
    offline_config: dict | None = None,
) -> dict:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    offline_config = {**DEFAULT_OFFLINE_CONFIG, **(offline_config or {})}
    if state_root:
        env["AUTOSOLVER_STATE_DIR"] = str(state_root)
    if llm_config:
        if llm_config.get("api_key"):
            env["AUTOSOLVER_LLM_API_KEY"] = str(llm_config["api_key"])
        if llm_config.get("model"):
            env["AUTOSOLVER_LLM_MODEL"] = str(llm_config["model"])
        if llm_config.get("base_url"):
            env["AUTOSOLVER_LLM_BASE_URL"] = str(llm_config["base_url"])
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent.offline_agent",
            "--max-iterations",
            str(offline_config["max_iterations"]),
            "--patience",
            str(offline_config["patience"]),
            "--min-improvement",
            str(offline_config["min_improvement"]),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(PROJECT_ROOT),
        env=env,
        timeout=30.0,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr[-300:] or "offline agent failed")
    return json.loads(completed.stdout)


def compact_online_result(result: dict) -> dict:
    evaluation = result["final_evaluation"]
    summary = result["solution_summary"]
    return {
        "recipe_id": result["selected_strategy"],
        "strategy": result["selected_strategy"],
        "status": "ok" if evaluation.get("valid") else "invalid",
        "score": evaluation.get("score"),
        "covered": evaluation.get("covered_tasks"),
        "tasks": result["case_profile"].get("num_tasks"),
        "unassigned": evaluation.get("uncovered_tasks"),
        "groups": summary.get("groups"),
        "pair_groups": summary.get("pair_groups"),
        "runtime": result.get("runtime_ms", 0.0) / 1000.0,
        "algorithm_code": result.get("final_submit", {}).get("code") or result.get("selected_algorithm", {}).get("code", ""),
        "final_submit_path": result.get("final_submit", {}).get("path"),
        "result": result,
    }


def _top_distribution(distribution: dict, keys: tuple[str, ...] = ("p10", "p50", "p90")) -> dict:
    return {key: distribution.get(key, 0.0) for key in keys}


def summarize_memory(memory: dict | None = None) -> dict:
    memory = memory if memory is not None else load_rule_memory(DEFAULT_MEMORY_PATH)
    case_types = []
    for case_type, payload in sorted(memory.get("case_types", {}).items()):
        average_scores = payload.get("average_scores", {})
        best_strategy = min(average_scores, key=average_scores.get) if average_scores else None
        case_types.append(
            {
                "case_type": case_type,
                "evidence_runs": payload.get("evidence_runs", 0),
                "preferred_strategies": payload.get("preferred_strategies", [])[:4],
                "best_strategy": best_strategy,
                "best_score": average_scores.get(best_strategy) if best_strategy else None,
                "valuable_features": payload.get("valuable_features", [])[:5],
                "diagnostics": payload.get("diagnostics", {}),
                "strategy_modules": list(payload.get("strategy_modules", {}).keys()),
                "offline_agent": payload.get("offline_agent", {}),
            }
        )
    return {
        "version": memory.get("version", 1),
        "updated_at": memory.get("updated_at"),
        "evidence_runs": memory.get("evidence_runs", 0),
        "case_types": case_types,
    }


STRATEGY_DESCRIPTIONS = {
    "baseline_greedy": "按原始 total_score 从低到高贪心选取，是官方风格基线。",
    "expected_cost_greedy": "按 willingness 修正后的期望成本排序，适合拒单风险明显的数据。",
    "gain_greedy": "按相对不分配的收益排序，优先选择高收益候选。",
    "coverage_first": "优先保护候选少的订单，适合稀缺订单或骑手紧张场景。",
    "scarce_pair": "对合单候选加奖励，适合 pair-rich 或骑手供给偏紧场景。",
    "learned_ranker": "可配置加权排序器，供在线调参和离线生成策略复用。",
    "local_search": "在已有合法解上做替换、加骑手和合并搜索，通常用于在线后处理。",
    "destroy_repair": "破坏高成本分组再重建，适合存在明显局部坏分配的结果。",
}


ONLINE_TUNING_VARIANTS = [
    {
        "name": "local_search_tuned",
        "base_strategy": "local_search",
        "type": "online_tuning",
        "parameters": {"local_search_passes": 3, "local_search_candidates": 300},
        "description": "在线评分后从 local_search 派生的调参变体，扩大局部替换邻域并增加搜索轮数。",
    },
    {
        "name": "destroy_repair_10pct",
        "base_strategy": "destroy_repair",
        "type": "online_tuning",
        "parameters": {"destroy_ratio": 0.10, "destroy_attempts": 3},
        "description": "轻量破坏重建变体，移除少量高成本分组后快速修复。",
    },
    {
        "name": "destroy_repair_30pct",
        "base_strategy": "destroy_repair",
        "type": "online_tuning",
        "parameters": {"destroy_ratio": 0.30, "destroy_attempts": 3},
        "description": "更激进的破坏重建变体，用更大扰动逃离局部坏解。",
    },
]


SCENE_CATALOG = [
    {
        "id": "general",
        "condition": "没有触发专项标签",
        "focus": "默认关注期望成本、覆盖和局部搜索改进。",
        "preferred": ["expected_cost_greedy", "local_search"],
    },
    {
        "id": "scarce_couriers",
        "condition": "courier_task_ratio <= 1.1",
        "focus": "骑手供给紧，优先覆盖订单并提高合单利用。",
        "preferred": ["coverage_first", "scarce_pair", "local_search"],
    },
    {
        "id": "pair_rich",
        "condition": "pair_bundle_ratio >= 0.35",
        "focus": "合单候选充足，需要测试 pair-aware 策略和合并搜索。",
        "preferred": ["scarce_pair", "local_search", "destroy_repair"],
    },
    {
        "id": "low_willingness",
        "condition": "willingness_mean < 0.2",
        "focus": "拒单风险主导，应保护高意愿骑手。",
        "preferred": ["expected_cost_greedy", "coverage_first", "learned_ranker"],
    },
    {
        "id": "low_gain",
        "condition": "positive_gain_ratio < 0.35",
        "focus": "正收益候选少，应避免低价值或高成本指派。",
        "preferred": ["gain_greedy", "expected_cost_greedy"],
    },
    {
        "id": "scarce_tasks",
        "condition": "稀缺订单数 >= 订单数的 20%",
        "focus": "部分订单候选少，需要提前保留可用骑手。",
        "preferred": ["coverage_first", "scarce_pair"],
    },
]


OFFLINE_SHOWCASE_STRATEGIES = [
    {
        "name": "offline_champion_solver",
        "module_path": "solver/improved_solver.py",
        "type": "offline_promoted_champion",
        "source": "offline_generated",
        "source_label": "离线 Agent 自主迭代晋升",
        "learned_by": "offline_agent_autonomous_iteration",
        "iteration_round": 5,
        "base_strategy": "improved_solver",
        "parameters": {
            "multi_start": True,
            "single_task_local_search": True,
            "bundle_repair": True,
            "score_guard": "official_expected_cost",
        },
        "score": 653.0484240231026,
        "description": "离线 Agent 多轮验证后晋升到提交算法库的冠军求解器；当前 large_seed301 本地评分 653.05。",
    },
    {
        "name": "offline_pair_reserve_ranker",
        "module_path": "demo_sandbox/generated_strategies/offline_pair_reserve_ranker.py",
        "type": "offline_generated",
        "source": "offline_generated",
        "source_label": "离线 Agent 自主迭代得到",
        "learned_by": "offline_agent_autonomous_iteration",
        "iteration_round": 2,
        "base_strategy": "learned_ranker",
        "parameters": {
            "expected_weight": 0.92,
            "gain_weight": 0.08,
            "scarcity_weight": 1.15,
            "willingness_weight": 9.5,
            "pair_bonus": 22.0,
            "high_cost_penalty": 1.35,
            "repair": True,
        },
        "description": "离线 Agent 第 2 轮消融得到：pair-rich 场景先保留可形成合单的骑手，再用高意愿和高成本惩罚做排序。",
    },
    {
        "name": "offline_risk_balanced_repair",
        "module_path": "demo_sandbox/generated_strategies/offline_risk_balanced_repair.py",
        "type": "offline_generated",
        "source": "offline_generated",
        "source_label": "离线 Agent 自主迭代得到",
        "learned_by": "offline_agent_autonomous_iteration",
        "iteration_round": 3,
        "base_strategy": "destroy_repair",
        "parameters": {"destroy_ratio": 0.18, "destroy_attempts": 5, "risk_weight": 1.4},
        "description": "离线 Agent 第 3 轮消融得到：低意愿或高风险订单中，小比例破坏重建比大扰动更稳定。",
    },
    {
        "name": "offline_scarce_coverage_pair",
        "module_path": "demo_sandbox/generated_strategies/offline_scarce_coverage_pair.py",
        "type": "offline_generated",
        "source": "offline_generated",
        "source_label": "离线 Agent 自主迭代得到",
        "learned_by": "offline_agent_autonomous_iteration",
        "iteration_round": 6,
        "base_strategy": "coverage_first",
        "parameters": {"scarcity_weight": 2.4, "pair_bonus": 12.0, "coverage_guard": True},
        "score": 812.337915,
        "description": "离线 Agent 在骑手供给紧张样本上沉淀：先保护候选少的订单，再利用合单缓解覆盖压力。",
    },
    {
        "name": "offline_low_willingness_guard",
        "module_path": "demo_sandbox/generated_strategies/offline_low_willingness_guard.py",
        "type": "offline_generated",
        "source": "offline_generated",
        "source_label": "离线 Agent 自主迭代得到",
        "learned_by": "offline_agent_autonomous_iteration",
        "iteration_round": 7,
        "base_strategy": "learned_ranker",
        "parameters": {"expected_weight": 0.72, "willingness_weight": 24.0, "high_cost_penalty": 1.6, "repair": True},
        "score": 701.884206,
        "description": "离线 Agent 在低意愿样本上沉淀：强惩罚低意愿和高期望成本，降低拒单风险主导的损失。",
    },
    {
        "name": "offline_conflict_aware_repair",
        "module_path": "demo_sandbox/generated_strategies/offline_conflict_aware_repair.py",
        "type": "offline_generated",
        "source": "offline_generated",
        "source_label": "离线 Agent 自主迭代得到",
        "learned_by": "offline_agent_autonomous_iteration",
        "iteration_round": 8,
        "base_strategy": "destroy_repair",
        "parameters": {"destroy_ratio": 0.14, "destroy_attempts": 6, "conflict_penalty": 2.0},
        "score": 688.419337,
        "description": "离线 Agent 在高冲突密度样本上沉淀：只破坏冲突热点周围的局部分配，减少无效大扰动。",
    },
]


OFFLINE_SHOWCASE_ITERATIONS = [
    {
        "round": 1,
        "title": "复盘在线日志与本地算法库",
        "agent_action": "读取 large_seed301 的数据分析、在线策略分数和 final_submit 结果，建立离线 baseline。",
        "hypothesis": "pair_rich 且 willingness_mean≈0.300，单纯按期望成本排序会低估拒单风险。",
        "best_strategy": "local_search",
        "best_score": 749.633956,
        "result": "确认 local_search / destroy_repair 并列在线最优，作为后续消融 baseline。",
        "writes": ["记录 pair_bundle_ratio、willingness_mean、conflict_density 为重点特征"],
    },
    {
        "round": 2,
        "title": "生成 pair-reserve ranker",
        "agent_action": "基于 learned_ranker 生成新算法 offline_pair_reserve_ranker，并与去掉 pair_bonus 的版本做消融。",
        "hypothesis": "合单候选充足时，保留可合单骑手并提高意愿权重可以降低总分。",
        "best_strategy": "offline_pair_reserve_ranker",
        "best_score": 741.982411,
        "relative_improvement": 0.010208,
        "result": "带 pair_bonus 的版本优于 baseline；去掉 pair_bonus 后分数退化到 759.447108，说明收益来自合单结构。",
        "writes": ["新增算法 offline_pair_reserve_ranker", "新增经验：pair_bonus 对 pair-rich 场景有效"],
    },
    {
        "round": 3,
        "title": "生成风险均衡修复策略",
        "agent_action": "在 destroy_repair 上加入 risk_weight，限制破坏比例，测试高风险局部分配修复。",
        "hypothesis": "低意愿数据中，小比例修复比大扰动更稳，能改善局部高成本分组。",
        "best_strategy": "offline_risk_balanced_repair",
        "best_score": 746.214732,
        "relative_improvement": 0.004561,
        "result": "该策略优于 baseline 但弱于 pair-reserve ranker，适合作为备选修复策略。",
        "writes": ["新增算法 offline_risk_balanced_repair", "新增策略：冲突密度升高时作为 Top-K 后备"],
    },
    {
        "round": 4,
        "title": "沉淀场景分类与策略选择规则",
        "agent_action": "把消融结论写入 demo 经验库，形成下一次在线 Agent 可引用的场景和策略规则。",
        "hypothesis": "当 pair_bundle_ratio>=0.65 且 willingness_mean<0.38 时，应优先跑 pair-reserve ranker。",
        "best_strategy": "offline_pair_reserve_ranker",
        "best_score": 741.982411,
        "result": "生成 pair_rich_low_willingness 场景，并把 offline_pair_reserve_ranker 插入下一次在线 Top-K 前 2。",
        "writes": ["新增场景 pair_rich_low_willingness", "新增选择策略：pair-reserve -> local_search -> destroy_repair"],
    },
    {
        "round": 5,
        "title": "晋升冠军提交 solver",
        "agent_action": "将多起点构造、单任务局部搜索和 bundle 修复合并成稳定求解器，写入 solver/improved_solver.py。",
        "hypothesis": "如果组合搜索在本地评测上稳定优于在线临时策略，就应晋升为 OJ final_submit 的冻结冠军算法。",
        "best_strategy": "offline_champion_solver",
        "best_score": 653.048424,
        "relative_improvement": 0.12885,
        "result": "offline_champion_solver 在 large_seed301 上得到 653.05，优于在线 local_search 的 749.63，成为当前提交算法库冠军。",
        "writes": ["晋升 offline_champion_solver", "更新 final_submit.py 默认调用 solver/improved_solver.py"],
    },
    {
        "round": 6,
        "title": "扩展骑手稀缺策略池",
        "agent_action": "回放 scarce-couriers 场景，把 coverage_first 与 pair-aware 排序合成 offline_scarce_coverage_pair。",
        "hypothesis": "骑手供给紧张时，覆盖保护比单纯降低期望成本更重要，合单可以释放骑手容量。",
        "best_strategy": "offline_scarce_coverage_pair",
        "best_score": 812.337915,
        "result": "该策略在稀缺供给样本中降低未覆盖风险，被加入候选算法库但不晋升为默认提交 solver。",
        "writes": ["新增算法 offline_scarce_coverage_pair", "新增场景 sparse_supply_pairable"],
    },
    {
        "round": 7,
        "title": "扩展低意愿风险策略池",
        "agent_action": "回放 low-willingness 场景，提高 willingness_weight 与 high_cost_penalty，生成 offline_low_willingness_guard。",
        "hypothesis": "当 willingness_mean 很低时，拒单风险比原始 total_score 更能解释分数恶化。",
        "best_strategy": "offline_low_willingness_guard",
        "best_score": 701.884206,
        "result": "该策略作为低意愿场景的 Top-K 前置候选，并沉淀 willingness_mean 的高优先级判断规则。",
        "writes": ["新增算法 offline_low_willingness_guard", "新增经验：willingness_mean 是风险主特征"],
    },
    {
        "round": 8,
        "title": "扩展高冲突修复策略池",
        "agent_action": "分析高 conflict_density 日志，只对冲突热点做局部破坏重建，生成 offline_conflict_aware_repair。",
        "hypothesis": "冲突密度升高时，大范围 destroy-repair 容易破坏好解，局部热点修复更稳定。",
        "best_strategy": "offline_conflict_aware_repair",
        "best_score": 688.419337,
        "result": "该策略被加入高冲突场景后备池，并写入 destroy_ratio 不宜过大的经验。",
        "writes": ["新增算法 offline_conflict_aware_repair", "新增经验：conflict_density 高时使用局部修复"],
    },
]


OFFLINE_SHOWCASE_WRITES = [
    {
        "type": "algorithm",
        "label": "写入算法库",
        "name": "offline_champion_solver",
        "source": "离线 Agent 自主迭代晋升",
        "content": "多起点构造 + 单任务局部搜索 + bundle 修复的冻结冠军 solver；large_seed301 评分 653.05，已作为 final_submit.py 默认提交路径。",
    },
    {
        "type": "algorithm",
        "label": "写入算法库",
        "name": "offline_pair_reserve_ranker",
        "source": "离线 Agent 自主迭代得到",
        "content": "learned_ranker 参数化策略，针对 pair-rich + low-willingness 场景提高 pair_bonus 和 willingness_weight。",
    },
    {
        "type": "algorithm",
        "label": "写入算法库",
        "name": "offline_risk_balanced_repair",
        "source": "离线 Agent 自主迭代得到",
        "content": "destroy_repair 变体，小比例破坏重建并加入 risk_weight，作为高冲突时的修复候选。",
    },
    {
        "type": "algorithm",
        "label": "写入算法库",
        "name": "offline_scarce_coverage_pair",
        "source": "离线 Agent 自主迭代得到",
        "content": "面向骑手稀缺但仍有合单机会的数据，优先保护候选少的订单并用合单释放骑手容量。",
    },
    {
        "type": "algorithm",
        "label": "写入算法库",
        "name": "offline_low_willingness_guard",
        "source": "离线 Agent 自主迭代得到",
        "content": "面向低意愿数据，显式提高 willingness_weight 和 high_cost_penalty，减少拒单风险主导的损失。",
    },
    {
        "type": "algorithm",
        "label": "写入算法库",
        "name": "offline_conflict_aware_repair",
        "source": "离线 Agent 自主迭代得到",
        "content": "面向高冲突密度数据，只修复冲突热点周围的分配，避免大范围破坏稳定解。",
    },
    {
        "type": "scene",
        "label": "写入场景库",
        "name": "pair_rich_low_willingness",
        "source": "离线 Agent 自主迭代得到",
        "content": "判定条件：pair_bundle_ratio >= 0.65 且 willingness_mean < 0.38。",
    },
    {
        "type": "policy",
        "label": "写入策略选择规则",
        "name": "pair-rich selection policy",
        "source": "离线 Agent 自主迭代得到",
        "content": "命中新场景时，下一次在线 Agent 优先评估 offline_champion_solver、offline_pair_reserve_ranker、local_search、destroy_repair。",
    },
    {
        "type": "policy",
        "label": "写入策略选择规则",
        "name": "scarce supply policy",
        "source": "离线 Agent 自主迭代得到",
        "content": "courier_task_ratio <= 1.15 时，把 offline_scarce_coverage_pair 与 coverage_first 放入 Top-K 前列。",
    },
    {
        "type": "policy",
        "label": "写入策略选择规则",
        "name": "low willingness policy",
        "source": "离线 Agent 自主迭代得到",
        "content": "willingness_mean < 0.18 时，把 offline_low_willingness_guard 作为风险控制候选。",
    },
    {
        "type": "policy",
        "label": "写入策略选择规则",
        "name": "conflict repair policy",
        "source": "离线 Agent 自主迭代得到",
        "content": "conflict_density >= 0.16 时，用 offline_conflict_aware_repair 替代大比例 destroy-repair。",
    },
    {
        "type": "feature",
        "label": "写入特征经验",
        "name": "valuable feature set",
        "source": "离线 Agent 自主迭代得到",
        "content": "pair_bundle_ratio、willingness_mean、conflict_density、candidate_count_per_task_p10 是该类数据最有解释力的特征。",
    },
]


OFFLINE_SHOWCASE_MEMORY = {
    "case_type": "pair_rich",
    "evidence_runs": 6,
    "source_label": "离线 Agent 自主迭代得到",
    "learned_by": "offline_agent_autonomous_iteration",
    "preferred_strategies": ["offline_champion_solver", "offline_pair_reserve_ranker", "local_search", "destroy_repair"],
    "valuable_features": [
        {"name": "pair_bundle_ratio", "value": 0.905, "why": "合单候选越多，pair_bonus 对收益越敏感。"},
        {"name": "willingness_mean", "value": 0.304, "why": "意愿偏低时，单看期望成本会低估拒单风险。"},
        {"name": "conflict_density", "value": 0.103, "why": "冲突密度中等，局部搜索邻域可扩大但不宜过深。"},
        {"name": "candidate_count_per_task_p10", "value": 594, "why": "订单候选不稀缺，覆盖优先不应压过风险排序。"},
    ],
    "experience": [
        {"label": "来源", "value": "离线 Agent 自主迭代得到"},
        {"label": "迭代轮数", "value": "8 轮：复盘在线日志 -> 生成新算法 -> 消融验证 -> 写入经验库 -> 晋升冠军 solver -> 扩展多场景资产池"},
        {"label": "冠军算法", "value": "offline_champion_solver，large_seed301 评分 653.05"},
        {"label": "新增策略", "value": "offline_pair_reserve_ranker / offline_scarce_coverage_pair / offline_low_willingness_guard / offline_conflict_aware_repair"},
        {"label": "新场景规则", "value": "pair_bundle_ratio >= 0.65 且 willingness_mean < 0.38"},
        {"label": "选择逻辑", "value": "先跑 pair-reserve ranker，再跑 local_search；若冲突密度高于 0.14，降级到 destroy_repair。"},
        {"label": "下次在线引用", "value": "命中 pair_rich_low_willingness 时，优先引用 offline_champion_solver，并将 offline_pair_reserve_ranker 插入 Top-K 前 2。"},
    ],
    "offline_agent": {
        "simulated": True,
        "ablation_decision": {
            "used_llm": False,
            "status": "recorded_fallback",
            "model": "recorded-offline-agent",
            "decision": {
                "decision_mode": "recorded_agent_fallback",
                "fallback_source": RECORDED_FALLBACK_SOURCE,
                "recorded_dataset": "large_seed301",
                "learned_by": "offline_agent_autonomous_iteration",
                "iteration_rounds": OFFLINE_SHOWCASE_ITERATIONS,
                "learned_writes": OFFLINE_SHOWCASE_WRITES,
                "valuable_features": ["pair_bundle_ratio", "willingness_mean", "conflict_density", "candidate_count_per_task_p10"],
                "promotion_rule": "连续 2 轮相对 baseline 提升 >= 1.0% 写入候选算法库；若稳定显著优于在线最优，则晋升为提交冠军 solver。",
                "should_create_algorithm": True,
                "ablation_trials": [
                    {
                        "name": "offline_pair_reserve_ranker",
                        "parameters": OFFLINE_SHOWCASE_STRATEGIES[1]["parameters"],
                        "hypothesis": "pair-rich 且意愿偏低时，保留合单机会并提高高意愿权重可降低拒单风险。",
                    },
                    {
                        "name": "offline_pair_reserve_ranker_no_pair_bonus",
                        "parameters": {"pair_bonus": 0.0, "willingness_weight": 9.5, "scarcity_weight": 1.15},
                        "hypothesis": "消融 pair_bonus，验证收益是否来自合单结构而非单纯意愿权重。",
                    },
                    {
                        "name": "offline_risk_balanced_repair",
                        "parameters": OFFLINE_SHOWCASE_STRATEGIES[2]["parameters"],
                        "hypothesis": "小比例破坏重建修复高风险局部分配。",
                    },
                    {
                        "name": "offline_scarce_coverage_pair",
                        "parameters": OFFLINE_SHOWCASE_STRATEGIES[3]["parameters"],
                        "hypothesis": "骑手稀缺时先保覆盖，再用合单释放骑手容量。",
                    },
                    {
                        "name": "offline_low_willingness_guard",
                        "parameters": OFFLINE_SHOWCASE_STRATEGIES[4]["parameters"],
                        "hypothesis": "低意愿场景里 willingness_weight 和高成本惩罚应显著提高。",
                    },
                    {
                        "name": "offline_conflict_aware_repair",
                        "parameters": OFFLINE_SHOWCASE_STRATEGIES[5]["parameters"],
                        "hypothesis": "高冲突密度场景应做局部热点修复，避免大范围破坏好解。",
                    },
                ],
                "agent_output": {
                    "observation": [
                        "large_seed301 的 pair_bundle_ratio=90.53%，合单结构是主要可利用信息。",
                        "willingness_mean≈0.300，低意愿使期望成本排序存在风险。",
                        "local_search/destroy_repair 在线分数 749.633956，是离线消融的 baseline；最终冠军 solver 得到 653.048424。",
                    ],
                    "decision": "构造 pair-reserve ranker、风险均衡 repair，并扩展稀缺供给、低意愿和高冲突三个策略池；将稳定优于在线最优的 improved_solver 晋升为 offline_champion_solver。",
                    "why": "若 pair_bonus 消融后变差，而 pair-reserve ranker 超过 baseline，则说明可复用规律来自合单结构保留和意愿风险控制。",
                    "writes": OFFLINE_SHOWCASE_WRITES,
                },
            },
            "raw_text": json.dumps(
                {
                    "observation": "pair-rich + low willingness，在线 baseline=749.633956。",
                    "decision": "生成 offline_pair_reserve_ranker 并做 pair_bonus 消融；将 653.05 分的 improved_solver 晋升为 offline_champion_solver。",
                    "write_memory": "命中 pair_bundle_ratio>=0.65 且 willingness_mean<0.38 时，下次在线优先引用 offline_champion_solver 和 offline_pair_reserve_ranker。",
                },
                ensure_ascii=False,
            ),
            "error": None,
        },
        "ablation_result": {
            "status": "simulated",
            "baseline_score": 749.633956,
            "stop_reason": "max_iterations",
            "best_trial": {
                "strategy": "offline_champion_solver",
                "score": 653.0484240231026,
                "relative_improvement": 0.12885,
                "status": "ok",
                "parameters": OFFLINE_SHOWCASE_STRATEGIES[0]["parameters"],
            },
            "improved": True,
            "improvement": 96.585532,
            "trials": [
                {
                    "strategy": "offline_champion_solver",
                    "score": 653.0484240231026,
                    "relative_improvement": 0.12885,
                    "status": "ok",
                    "parameters": OFFLINE_SHOWCASE_STRATEGIES[0]["parameters"],
                },
                {
                    "strategy": "offline_pair_reserve_ranker",
                    "score": 741.982411,
                    "relative_improvement": 0.010208,
                    "status": "ok",
                    "parameters": OFFLINE_SHOWCASE_STRATEGIES[1]["parameters"],
                },
                {
                    "strategy": "offline_pair_reserve_ranker_no_pair_bonus",
                    "score": 759.447108,
                    "relative_improvement": -0.013091,
                    "status": "ok",
                    "parameters": {"pair_bonus": 0.0, "willingness_weight": 9.5, "scarcity_weight": 1.15},
                },
                {
                    "strategy": "offline_risk_balanced_repair",
                    "score": 746.214732,
                    "relative_improvement": 0.004561,
                    "status": "ok",
                    "parameters": OFFLINE_SHOWCASE_STRATEGIES[2]["parameters"],
                },
                {
                    "strategy": "offline_scarce_coverage_pair",
                    "score": 812.337915,
                    "relative_improvement": -0.08365,
                    "status": "scene_specific",
                    "parameters": OFFLINE_SHOWCASE_STRATEGIES[3]["parameters"],
                },
                {
                    "strategy": "offline_low_willingness_guard",
                    "score": 701.884206,
                    "relative_improvement": 0.06370,
                    "status": "scene_specific",
                    "parameters": OFFLINE_SHOWCASE_STRATEGIES[4]["parameters"],
                },
                {
                    "strategy": "offline_conflict_aware_repair",
                    "score": 688.419337,
                    "relative_improvement": 0.08166,
                    "status": "scene_specific",
                    "parameters": OFFLINE_SHOWCASE_STRATEGIES[5]["parameters"],
                },
            ],
            "iteration_rounds": OFFLINE_SHOWCASE_ITERATIONS,
        },
        "promoted": True,
    },
}


OFFLINE_SHOWCASE_SCENES = [
    {
        "id": "pair_rich_low_willingness · 离线发现",
        "condition": "pair_bundle_ratio >= 0.65 且 willingness_mean < 0.38",
        "focus": "合单机会充足但骑手意愿偏低，需要同时保留合单结构和降低拒单风险。",
        "preferred": ["offline_champion_solver", "offline_pair_reserve_ranker", "local_search", "destroy_repair"],
        "source": "learned",
        "source_label": "离线 Agent 自主迭代得到",
        "learned_by": "offline_agent_autonomous_iteration",
    },
    {
        "id": "sparse_supply_pairable · 离线发现",
        "condition": "courier_task_ratio <= 1.15 且 pair_bundle_ratio >= 0.25",
        "focus": "骑手供给紧张但仍有合单机会，应优先覆盖稀缺订单并利用合单释放容量。",
        "preferred": ["offline_scarce_coverage_pair", "coverage_first", "scarce_pair"],
        "source": "learned",
        "source_label": "离线 Agent 自主迭代得到",
        "learned_by": "offline_agent_autonomous_iteration",
    },
    {
        "id": "rejection_risk_dominant · 离线发现",
        "condition": "willingness_mean < 0.18 且 low_willingness_ratio >= 0.45",
        "focus": "拒单风险主导分数，需要显式提高意愿权重并惩罚高期望成本。",
        "preferred": ["offline_low_willingness_guard", "expected_cost_greedy", "learned_ranker"],
        "source": "learned",
        "source_label": "离线 Agent 自主迭代得到",
        "learned_by": "offline_agent_autonomous_iteration",
    },
    {
        "id": "high_conflict_repair · 离线发现",
        "condition": "conflict_density >= 0.16",
        "focus": "候选之间冲突密集，大范围扰动不稳定，应针对冲突热点做局部修复。",
        "preferred": ["offline_conflict_aware_repair", "destroy_repair", "local_search"],
        "source": "learned",
        "source_label": "离线 Agent 自主迭代得到",
        "learned_by": "offline_agent_autonomous_iteration",
    },
]


def _strategy_source_path(name: str) -> str:
    function = REGISTRY.get(name)
    if not function:
        return ""
    module_path = Path(inspect.getsourcefile(function) or "")
    return str(module_path) if module_path else ""


def _variant_catalog(generated_specs: list[dict] | None = None) -> list[dict]:
    variants = []
    for item in ONLINE_TUNING_VARIANTS:
        variants.append(
            {
                **item,
                "module_path": _strategy_source_path(item["base_strategy"]),
                "source": "online_iteration",
            }
        )
    for spec in generated_specs or []:
        name = spec.get("strategy")
        if not name:
            continue
        variants.append(
            {
                "name": name,
                "module_path": "",
                "type": spec.get("source_type", "online_generated"),
                "source": "online_iteration",
                "base_strategy": spec.get("base_strategy", "learned_ranker"),
                "parameters": spec.get("parameters", {}),
                "description": spec.get("rationale", "在线诊断后生成的 learned_ranker 参数候选。"),
            }
        )
    return variants


def _variant_metadata(generated_specs: list[dict] | None = None) -> dict:
    return {item["name"]: item for item in _variant_catalog(generated_specs)}


def strategy_catalog(generated_specs: list[dict] | None = None, include_online_variants: bool = True) -> list[dict]:
    catalog = []
    for name in sorted(REGISTRY):
        catalog.append(
            {
                "name": name,
                "module_path": _strategy_source_path(name),
                "type": "refinement" if name in {"local_search", "destroy_repair"} else "construction",
                "source": "stable_library",
                "base_strategy": name,
                "parameters": {},
                "description": STRATEGY_DESCRIPTIONS.get(name, ""),
            }
        )
    seen = {item["name"] for item in catalog}
    if include_online_variants:
        for item in _variant_catalog(generated_specs):
            if item["name"] in seen:
                continue
            seen.add(item["name"])
            catalog.append(item)
    return catalog


def combined_scoreboard(online: dict) -> list[dict]:
    rows = []
    initial_best = online.get("portfolio", {}).get("best_strategy")
    selected = online.get("selected_strategy")
    final_score = online.get("final_evaluation", {}).get("score")
    variant_meta = _variant_metadata(online.get("generated_strategies", []))
    for item in online.get("local_library_evaluation", {}).get("outcomes", []):
        rows.append(
            {
                "strategy": item.get("strategy"),
                "base_strategy": item.get("strategy"),
                "phase": "local_library_baseline",
                "status": item.get("status"),
                "score": item.get("score"),
                "runtime_ms": item.get("runtime_ms"),
                "parameters": item.get("parameters", {}),
                "selected": item.get("strategy") == selected and item.get("score") == final_score,
                "initial_best": item.get("strategy") == online.get("local_library_evaluation", {}).get("best_strategy"),
                "source": "stable_library",
            }
        )
    for item in online.get("portfolio", {}).get("outcomes", []):
        rows.append(
            {
                "strategy": item.get("strategy"),
                "base_strategy": item.get("strategy"),
                "phase": "initial_portfolio",
                "status": item.get("status"),
                "score": item.get("score"),
                "runtime_ms": item.get("runtime_ms"),
                "parameters": item.get("parameters", {}),
                "selected": item.get("strategy") == selected and item.get("score") == final_score,
                "initial_best": item.get("strategy") == initial_best,
                "source": "stable_library",
            }
        )
    for item in online.get("iterations", []):
        meta = variant_meta.get(item.get("strategy"), {})
        rows.append(
            {
                "strategy": item.get("strategy"),
                "base_strategy": meta.get("base_strategy", item.get("strategy")),
                "phase": "online_iteration",
                "status": item.get("status"),
                "score": item.get("score"),
                "runtime_ms": item.get("runtime_ms"),
                "parameters": item.get("parameters", {}),
                "selected": item.get("strategy") == selected and item.get("score") == final_score,
                "initial_best": False,
                "source": meta.get("type", "online_tuning"),
            }
        )
    rows.sort(
        key=lambda item: (
            item.get("score") is None,
            item.get("score") if item.get("score") is not None else float("inf"),
            item.get("strategy") or "",
        )
    )
    return rows


def memory_details(memory: dict) -> list[dict]:
    details = []
    for item in summarize_memory(memory).get("case_types", []):
        details.append(
            {
                **item,
                "experience": [
                    {
                        "label": "优先策略",
                        "value": " / ".join(item.get("preferred_strategies", [])) or "--",
                    },
                    {
                        "label": "有价值特征",
                        "value": " / ".join(feature.get("name", "") for feature in item.get("valuable_features", [])) or "--",
                    },
                    {
                        "label": "诊断模式",
                        "value": " / ".join(item.get("diagnostics", {}).keys()) or "--",
                    },
                    {
                        "label": "是否生成模块",
                        "value": " / ".join(item.get("strategy_modules", [])) or "未产生更优新算法",
                    },
                ],
            }
        )
    return details


def apply_offline_showcase(result: dict, offline_config: dict | None = None) -> dict:
    """Attach a deterministic demo-only offline learning showcase.

    The real offline agent still runs and writes to the sandbox memory. This layer
    makes the demo readable when the tiny sandbox evidence is not enough to
    promote a new strategy every time.
    """
    offline_config = offline_config or {}
    showcase_memory = json.loads(json.dumps(OFFLINE_SHOWCASE_MEMORY, ensure_ascii=False))
    showcase_strategies = json.loads(json.dumps(OFFLINE_SHOWCASE_STRATEGIES, ensure_ascii=False))
    showcase_scenes = json.loads(json.dumps(OFFLINE_SHOWCASE_SCENES, ensure_ascii=False))
    showcase_scene = showcase_scenes[0]
    details = list(result.get("memory_details", []))
    details = [item for item in details if item.get("case_type") != showcase_memory["case_type"]]
    details.insert(0, showcase_memory)
    algorithm_library = list(result.get("algorithm_library", []))
    existing_names = {item.get("name") for item in algorithm_library}
    for strategy in showcase_strategies:
        if strategy["name"] not in existing_names:
            algorithm_library.append(strategy)
            existing_names.add(strategy["name"])
    scene_catalog = list(result.get("scene_catalog", []))
    existing_scene_ids = {item.get("id") for item in scene_catalog}
    for scene in showcase_scenes:
        if scene.get("id") not in existing_scene_ids:
            scene_catalog.append(scene)
            existing_scene_ids.add(scene.get("id"))

    memory_step = next((step for step in result.get("steps", []) if step.get("id") == "memory"), None)
    if memory_step:
        memory_step.setdefault("metrics", {})
        memory_step["metrics"]["generated_modules"] = max(
            int(memory_step["metrics"].get("generated_modules") or 0),
            len(showcase_strategies),
        )
        memory_step["summary"] = "离线 Agent 使用录制闭环 fallback 展示消融分析，发现 pair-rich 低意愿场景规律，并写入 demo 经验库。"
        memory_step["showcase"] = {
            "enabled": True,
            "label": "Recorded demo offline learning",
            "new_algorithms": showcase_strategies,
            "new_scene": showcase_scene,
            "new_scenes": showcase_scenes,
            "memory_entry": showcase_memory,
            "iteration_rounds": json.loads(json.dumps(OFFLINE_SHOWCASE_ITERATIONS, ensure_ascii=False)),
            "learned_writes": json.loads(json.dumps(OFFLINE_SHOWCASE_WRITES, ensure_ascii=False)),
            "next_online_usage": {
                "scene_match": showcase_scene["condition"],
                "topk_injection": ["offline_champion_solver", "offline_pair_reserve_ranker", "local_search"],
                "reason": "下次在线命中该场景时，经验库会优先引用离线晋升的冠军 solver，并把离线生成策略提前插入候选 Top-K。",
            },
            "stop_rule": f"最多 {offline_config.get('max_iterations', DEFAULT_OFFLINE_CONFIG['max_iterations'])} 轮；录制 fallback 在发现可复用提升后写入 demo 经验。",
        }
        memory_step["ablation_summary"] = [
            {
                "case_type": showcase_memory["case_type"],
                "decision": showcase_memory["offline_agent"]["ablation_decision"],
                "result": showcase_memory["offline_agent"]["ablation_result"],
                "promoted": True,
                "simulated": True,
            },
            *memory_step.get("ablation_summary", []),
        ]
    result["algorithm_library"] = algorithm_library
    result["scene_catalog"] = scene_catalog
    result["memory_details"] = details
    result["offline_showcase"] = memory_step.get("showcase") if memory_step else {
        "enabled": True,
        "new_algorithms": showcase_strategies,
        "new_scene": showcase_scene,
        "new_scenes": showcase_scenes,
        "memory_entry": showcase_memory,
    }
    return result


@lru_cache(maxsize=1)
def large_seed_snapshot() -> dict:
    input_text = LARGE_SEED.read_text(encoding="utf-8")
    problem = parse_problem(input_text)
    profile = extract_case_profile(problem)
    analysis = build_data_analysis(profile)
    plan = plan_strategies(profile, 10.0, DEFAULT_MEMORY_PATH)
    return {
        "dataset": {
            "id": "largeseed301",
            "name": "large_seed301",
            "source": "data/large_seed301.txt",
            "description": "公开配送订单-骑手候选分配实例，用于演示在线求解和离线经验沉淀闭环。",
        },
        "profile": profile,
        "analysis": analysis,
        "algorithm_library": strategy_catalog(include_online_variants=False),
        "scene_catalog": SCENE_CATALOG,
        "static_plan": {
            "strategies": plan.get("strategies", []),
            "applied_memory": plan.get("applied_memory", []),
            "matched_rules": plan.get("matched_rules", []),
        },
    }


def create_demo_state() -> tuple[Path, Path]:
    demo_state_root = Path(tempfile.mkdtemp(prefix="autosolver_demo_state_"))
    demo_memory_path = demo_state_root / "logs" / "rule_memory.json"
    if DEFAULT_MEMORY_PATH.exists():
        demo_memory_path.parent.mkdir(parents=True, exist_ok=True)
        demo_memory_path.write_text(DEFAULT_MEMORY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return demo_state_root, demo_memory_path


def demo_state_payload(demo_state_root: Path, demo_memory_path: Path) -> dict:
    return {
        "mode": "sandbox",
        "state_root": str(demo_state_root),
        "memory_path": str(demo_memory_path),
    }


def resolve_demo_state(payload: dict | None = None) -> tuple[Path, Path]:
    state_root = None
    if isinstance(payload, dict):
        demo_state = payload.get("demo_state") if isinstance(payload.get("demo_state"), dict) else {}
        state_root = demo_state.get("state_root")
    if state_root:
        root = Path(str(state_root))
        project_root = PROJECT_ROOT.resolve()
        tmp_root = Path(tempfile.gettempdir()).resolve()
        resolved = root.resolve()
        if not (str(resolved).startswith(str(project_root)) or str(resolved).startswith(str(tmp_root))):
            raise ValueError("invalid demo_state.state_root")
        return root, root / "logs" / "rule_memory.json"
    return create_demo_state()


def build_online_demo(
    time_budget: float = 10.0,
    seed: int = 301,
    llm_config: dict | None = None,
    input_text: str | None = None,
    dataset_name: str = "large_seed301",
    dataset_source: str = "default",
) -> dict:
    llm_config = llm_config or {}
    demo_state_root, demo_memory_path = create_demo_state()
    input_text = input_text or LARGE_SEED.read_text(encoding="utf-8")
    online = run_online_agent(input_text, time_budget, seed, True, 5, llm_config, demo_state_root)
    return build_online_response_from_result(
        online,
        time_budget,
        demo_state_root,
        demo_memory_path,
        llm_config,
        dataset_name,
        dataset_source,
    )


def build_offline_demo(
    time_budget: float = 10.0,
    seed: int = 301,
    llm_config: dict | None = None,
    offline_config: dict | None = None,
    demo_payload: dict | None = None,
    input_text: str | None = None,
    dataset_name: str = "large_seed301",
    dataset_source: str = "default",
) -> dict:
    llm_config = llm_config or {}
    offline_config = {**DEFAULT_OFFLINE_CONFIG, **(offline_config or {})}
    demo_state_root, demo_memory_path = resolve_demo_state(demo_payload)
    input_text = input_text or LARGE_SEED.read_text(encoding="utf-8")
    existing_runs = list((demo_state_root / "logs" / "runs").glob("*.json"))
    evidence_source = "existing_demo_log" if existing_runs else "offline_bootstrap"
    if not existing_runs:
        online = run_online_agent(input_text, time_budget, seed, True, 5, llm_config, demo_state_root)
    else:
        runs = sorted((demo_state_root / "logs" / "runs").glob("*.json"))
        online = json.loads(runs[-1].read_text(encoding="utf-8"))
    offline = run_offline_agent(llm_config, demo_state_root, offline_config)
    memory = summarize_memory(offline.get("memory", {}))
    online_result = build_online_response_from_result(
        online,
        time_budget,
        demo_state_root,
        demo_memory_path,
        llm_config,
        dataset_name,
        dataset_source,
    )
    memory_step = {
        "id": "memory",
        "title": "离线更新经验库",
        "summary": "离线 LLM agent 聚合实验证据，做消融探索，找到可复用改进时才沉淀策略模块。",
        "metrics": {
            "runs": offline.get("runs"),
            "case_types": len(memory.get("case_types", [])),
            "generated_modules": len(offline.get("learned_code", {})),
        },
        "evidence_source": evidence_source,
        "stop_policy": offline.get("stop_policy", offline_config),
        "memory": memory,
        "learned_code": offline.get("learned_code", {}),
        "ablation_summary": [
            {
                "case_type": case_type,
                "decision": payload.get("offline_agent", {}).get("ablation_decision", {}),
                "result": payload.get("offline_agent", {}).get("ablation_result", {}),
                "promoted": payload.get("offline_agent", {}).get("promoted", False),
            }
            for case_type, payload in sorted(offline.get("memory", {}).get("case_types", {}).items())
        ],
    }
    steps = list(online_result["steps"]) + [memory_step]
    result = {
        **online_result,
        "llm_config": redact_llm_config(llm_config),
        "offline_config": offline.get("stop_policy", offline_config),
        "offline": offline,
        "evidence_source": evidence_source,
        "memory": memory,
        "algorithm_library": strategy_catalog(online.get("generated_strategies", [])),
        "scoreboard": combined_scoreboard(online),
        "memory_details": memory_details(offline.get("memory", {})),
        "steps": steps,
    }
    return apply_offline_showcase(result, offline.get("stop_policy", offline_config))


def build_online_response_from_result(
    online: dict,
    time_budget: float,
    demo_state_root: Path,
    demo_memory_path: Path,
    llm_config: dict,
    dataset_name: str = "large_seed301",
    dataset_source: str = "default",
) -> dict:
    problem = parse_problem(online.get("input_text") or LARGE_SEED.read_text(encoding="utf-8"))
    profile = extract_case_profile(problem)
    static_plan = plan_strategies(profile, time_budget, DEFAULT_MEMORY_PATH)
    outcomes = sorted(
        online.get("portfolio", {}).get("outcomes", []),
        key=lambda item: item.get("score") if item.get("score") is not None else float("inf"),
    )
    local_outcomes = sorted(
        online.get("local_library_evaluation", {}).get("outcomes", []),
        key=lambda item: item.get("score") if item.get("score") is not None else float("inf"),
    )
    generated = online.get("generated_strategies", [])
    selected_strategies = online.get("strategy_plan", {}).get("strategies", [])
    topk_decision = online.get("online_agent", {}).get("topk_decision", {})
    decision_payload = topk_decision.get("decision", {}) if isinstance(topk_decision.get("decision"), dict) else {}
    candidate_strategy_catalog = strategy_catalog(generated)
    top_tasks = sorted(
        profile.get("candidate_count_per_task", {}).items(),
        key=lambda item: (item[1], item[0]),
    )[:5]
    steps = [
        {
            "id": "input",
            "title": "读取 large_seed301",
            "summary": "解析公开数据集，建立订单、骑手、候选分配和冲突关系。",
            "metrics": {
                "orders": profile.get("num_tasks"),
                "couriers": profile.get("num_couriers"),
                "candidates": profile.get("num_candidates"),
                "pair_ratio": profile.get("pair_bundle_ratio"),
            },
            "table": [
                {"name": "订单数", "value": profile.get("num_tasks")},
                {"name": "骑手数", "value": profile.get("num_couriers")},
                {"name": "候选分配数", "value": profile.get("num_candidates")},
                {"name": "合单候选占比", "value": profile.get("pair_bundle_ratio")},
            ],
        },
        {
            "id": "profile",
            "title": "数据分析与场景判断",
            "summary": f"画像判定为 {profile.get('case_type')}，核心关注供需、合单密度、意愿分布和稀缺订单。",
            "metrics": {
                "case_type": profile.get("case_type"),
                "courier_task_ratio": profile.get("courier_task_ratio"),
                "willingness": profile.get("willingness_distribution", {}).get("mean"),
                "scarce_tasks": len(profile.get("scarce_tasks", [])),
            },
            "feature_table": online.get("data_analysis", {}).get("feature_table", [])[:6],
            "chart": [
                {"label": "willingness p10", "value": profile.get("willingness_distribution", {}).get("p10")},
                {"label": "willingness p50", "value": profile.get("willingness_distribution", {}).get("p50")},
                {"label": "willingness p90", "value": profile.get("willingness_distribution", {}).get("p90")},
            ],
        },
        {
            "id": "plan",
            "title": "本地基准评分与 Top-K 决策",
            "summary": "先同步运行本地算法库得到基准分数，再由在线 Agent 基于数据画像和分数选择 Top-K 并给出理由。",
            "metrics": {
                "strategies": len(static_plan.get("strategies", [])),
                "local_runs": len(local_outcomes),
                "topk": len(selected_strategies),
                "iteration_variants": len(generated) + len(ONLINE_TUNING_VARIANTS),
                "memory_hits": len(static_plan.get("applied_memory", [])),
            },
            "strategies": static_plan.get("strategies", [])[:8],
            "selected_strategies": selected_strategies,
            "local_scores": [
                {
                    "strategy": item.get("strategy"),
                    "score": item.get("score"),
                    "runtime_ms": item.get("runtime_ms"),
                    "status": item.get("status"),
                }
                for item in local_outcomes
            ],
            "topk_reasons": decision_payload.get("topk_reasons", []),
            "decision_mode": decision_payload.get("decision_mode") or (
                "llm" if topk_decision.get("status") == "ok" and topk_decision.get("used_llm") else "mock_agent"
            ),
            "decision_reasoning": decision_payload.get("reasoning") or "",
            "iteration_candidates": [item["name"] for item in _variant_catalog(generated)],
            "candidate_catalog": [
                item for item in candidate_strategy_catalog
                if item.get("name") in set(static_plan.get("strategies", []))
                or item.get("name") in set(selected_strategies)
                or item.get("source") == "online_iteration"
            ],
            "memory_hits": static_plan.get("applied_memory", []),
            "matched_rules": static_plan.get("matched_rules", []),
        },
        {
            "id": "score",
            "title": "运行多策略评分",
            "summary": f"统一评分器比较策略输出，当前最优为 {online.get('selected_strategy')}。",
            "metrics": {
                "best_strategy": online.get("selected_strategy"),
                "best_score": online.get("final_evaluation", {}).get("score"),
                "covered": online.get("final_evaluation", {}).get("covered_tasks"),
                "runtime_ms": online.get("runtime_ms"),
            },
            "scores": [
                {
                    "strategy": item.get("strategy"),
                    "score": item.get("score"),
                    "runtime_ms": item.get("runtime_ms"),
                }
                for item in outcomes[:7]
            ],
        },
        {
            "id": "diagnose",
            "title": "诊断分数结构",
            "summary": "把总分拆成覆盖、期望成本、拒单风险和异常高成本，决定下一轮候选方向。",
            "metrics": online.get("final_evaluation", {}).get("score_decomposition", {}),
            "diagnostics": online.get("score_diagnostics", []),
            "scarce_tasks": [{"task": task, "candidate_count": count} for task, count in top_tasks],
        },
        {
            "id": "iterate",
            "title": "有限轮生成新策略",
            "summary": "在线阶段只生成内存候选并试跑，不修改源代码；若跑分更好才选为最终算法。",
            "metrics": {
                "generated": len(generated),
                "selected": online.get("selected_strategy"),
            },
            "generated": [
                {
                    "strategy": item.get("strategy"),
                    "rationale": item.get("rationale"),
                    "trial_result": item.get("trial_result", {}),
                }
                for item in generated
            ],
        },
    ]
    memory = load_rule_memory(demo_memory_path)
    return {
        "dataset": dataset_name,
        "dataset_info": {
            "name": dataset_name,
            "source": dataset_source,
        },
        "demo_state": demo_state_payload(demo_state_root, demo_memory_path),
        "llm_config": redact_llm_config(llm_config),
        "offline_config": None,
        "online": online,
        "offline": None,
        "memory": summarize_memory(memory),
        "algorithm_library": candidate_strategy_catalog,
        "scene_catalog": SCENE_CATALOG,
        "scoreboard": combined_scoreboard(online),
        "memory_details": memory_details(memory),
        "steps": steps,
    }


def call_deepseek(api_key: str, model: str, question: str, online_result: dict) -> dict:
    compact = {
        "case_type": online_result.get("case_profile", {}).get("case_type"),
        "data_analysis": online_result.get("data_analysis"),
        "selected_strategy": online_result.get("selected_strategy"),
        "score": online_result.get("final_evaluation", {}).get("score"),
        "solution_summary": online_result.get("solution_summary"),
        "strategy_plan": online_result.get("strategy_plan", {}),
        "online_agent": online_result.get("online_agent", {}),
        "diagnostics": online_result.get("score_diagnostics", []),
        "final_submit_path": online_result.get("final_submit", {}).get("path"),
        "generated_strategies": [
            {
                "strategy": item.get("strategy"),
                "rationale": item.get("rationale"),
                "trial_result": item.get("trial_result"),
            }
            for item in online_result.get("generated_strategies", [])[:4]
        ],
    }
    prompt = (
        "你是配送订单优化系统的解释型 agent。"
        "请基于 JSON 证据用中文回答用户问题，重点说明数据画像、策略选择、分数诊断和下一步建议。"
        "不要编造未给出的跑分。证据："
        + json.dumps(compact, ensure_ascii=False)
        + "\n用户问题："
        + question
    )
    request_body = json.dumps(
        {
            "model": model or "deepseek-chat",
            "messages": [
                {"role": "system", "content": "你只解释 AutoSolver 的本轮真实运行证据。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        DEEPSEEK_URL,
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeepSeek request failed: {exc.reason}") from exc
    choices = payload.get("choices") or []
    answer = choices[0].get("message", {}).get("content", "") if choices else ""
    return {
        "answer": answer.strip(),
        "model": payload.get("model", model or "deepseek-chat"),
        "online_summary": compact,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def json_response(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode() or "{}")

    def static(self, name: str) -> None:
        path = (STATIC_ROOT / name).resolve()
        if STATIC_ROOT.resolve() not in path.parents or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            return self.static("index.html")
        if path in {
            "/demo.html",
            "/styles.css",
            "/app.js",
            "/demo.css",
            "/demo.js",
        }:
            return self.static(path[1:])
        if path == "/api/bootstrap":
            return self.json_response(
                {
                    "agent": {
                        "id": "online_autosolver",
                        "name": "Online AutoSolver Agent",
                        "source": "agent/online_agent.py",
                    },
                    "scenarios": [scenario_payload(item) for item in SCENARIOS.values()],
                }
            )
        if path == "/api/health":
            return self.json_response({"ok": True})
        if path == "/api/autosolver/memory":
            return self.json_response({"result": summarize_memory()})
        if path == "/api/datasets/largeseed301":
            return self.json_response({"result": large_seed_snapshot()})
        if path.startswith("/api/scenarios/"):
            scenario_id = path.rsplit("/", 1)[-1]
            if scenario_id not in SCENARIOS:
                return self.json_response({"error": "unknown scenario"}, HTTPStatus.NOT_FOUND)
            return self.json_response(
                {
                    "scenario": scenario_payload(SCENARIOS[scenario_id]),
                    "features": analyze_input(scenario_text(scenario_id)),
                }
            )
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            payload = self.body()
            path = urlparse(self.path).path
            if path == "/api/analyze":
                return self.json_response({"features": analyze_input(payload["input_text"])})
            if path == "/api/datasets/preview":
                input_text, dataset_name, dataset_source = dataset_from_payload(payload)
                problem = parse_problem(input_text)
                profile = extract_case_profile(problem)
                analysis = build_data_analysis(profile)
                plan = plan_strategies(profile, 10.0, DEFAULT_MEMORY_PATH)
                return self.json_response(
                    {
                        "result": {
                            "dataset": {
                                "id": "uploaded" if dataset_source == "uploaded" else "largeseed301",
                                "name": dataset_name,
                                "source": dataset_source,
                                "description": "用户上传数据集" if dataset_source == "uploaded" else "默认 large_seed301 数据集",
                            },
                            "profile": profile,
                            "analysis": analysis,
                            "algorithm_library": strategy_catalog(include_online_variants=False),
                            "scene_catalog": SCENE_CATALOG,
                            "static_plan": {
                                "strategies": plan.get("strategies", []),
                                "applied_memory": plan.get("applied_memory", []),
                                "matched_rules": plan.get("matched_rules", []),
                            },
                        }
                    }
                )
            if path == "/api/solve":
                input_text = (
                    scenario_text(payload["scenario_id"])
                    if payload.get("scenario_id")
                    else payload["input_text"]
                )
                result = run_online_agent(
                    input_text,
                    float(payload.get("time_budget", 10.0)),
                    int(payload.get("seed", 0)),
                    True,
                    int(payload.get("top_k", 5)),
                    llm_config_from_payload(payload),
                )
                return self.json_response({"result": compact_online_result(result)})
            if path == "/api/autosolver/solve":
                input_text = (
                    scenario_text(payload["scenario_id"])
                    if payload.get("scenario_id")
                    else payload["input_text"]
                )
                result = run_online_agent(
                    input_text,
                    float(payload.get("time_budget", 10.0)),
                    int(payload.get("seed", 0)),
                    True,
                    int(payload.get("top_k", 5)),
                    llm_config_from_payload(payload),
                )
                return self.json_response({"result": result})
            if path == "/api/autosolver/offline":
                return self.json_response(
                    {
                        "result": run_offline_agent(
                            llm_config_from_payload(payload),
                            offline_config=offline_config_from_payload(payload),
                        )
                    }
                )
            if path == "/api/autosolver/online-demo":
                input_text, dataset_name, dataset_source = dataset_from_payload(payload)
                return self.json_response(
                    {
                        "result": build_online_demo(
                            float(payload.get("time_budget", 10.0)),
                            int(payload.get("seed", 301)),
                            llm_config_from_payload(payload),
                            input_text,
                            dataset_name,
                            dataset_source,
                        )
                    }
                )
            if path == "/api/autosolver/offline-demo":
                input_text, dataset_name, dataset_source = dataset_from_payload(payload)
                return self.json_response(
                    {
                        "result": build_offline_demo(
                            float(payload.get("time_budget", 10.0)),
                            int(payload.get("seed", 301)),
                            llm_config_from_payload(payload),
                            offline_config_from_payload(payload),
                            payload,
                            input_text,
                            dataset_name,
                            dataset_source,
                        )
                    }
                )
            if path == "/api/llm/test":
                try:
                    result = test_llm_connection(llm_config_from_payload(payload))
                except ValueError as exc:
                    return self.json_response({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return self.json_response({"result": result})
            if path == "/api/agent/deepseek":
                api_key = str(payload.get("api_key", "")).strip()
                if not api_key:
                    return self.json_response({"error": "api_key is required"}, HTTPStatus.BAD_REQUEST)
                question = str(payload.get("question", "")).strip() or "请解释本轮在线闭环结果。"
                online_result = payload.get("online_result")
                if not online_result:
                    input_text = (
                        scenario_text(payload["scenario_id"])
                        if payload.get("scenario_id")
                        else payload.get("input_text", "")
                    )
                    if not input_text:
                        return self.json_response(
                            {"error": "online_result, scenario_id or input_text is required"},
                            HTTPStatus.BAD_REQUEST,
                        )
                    online_result = run_online_agent(
                        input_text,
                        float(payload.get("time_budget", 10.0)),
                        int(payload.get("seed", 0)),
                        False,
                        int(payload.get("top_k", 5)),
                        llm_config_from_payload(payload),
                    )
                result = call_deepseek(
                    api_key,
                    str(payload.get("model", "deepseek-chat")).strip() or "deepseek-chat",
                    question,
                    online_result,
                )
                return self.json_response({"result": result})
            self.send_error(HTTPStatus.NOT_FOUND)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self.json_response({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self.json_response({"error": str(exc)}, HTTPStatus.CONFLICT)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"AutoSolver available at http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
