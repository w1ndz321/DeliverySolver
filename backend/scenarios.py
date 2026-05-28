"""Deterministic demo scenarios and lightweight input diagnosis."""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from statistics import fmean


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_CASE = PROJECT_ROOT / "data" / "large_seed301.txt"


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    narrative: str
    tags: tuple[str, ...]


SCENARIOS = {
    "low-willingness": Scenario(
        "low-willingness",
        "低意愿压力",
        "从公开样例确定性缩放接单意愿并稀疏化合单候选，验证拒单风险下的改进。",
        ("LOW WILLINGNESS", "PAIR SEARCH", "DERIVED PUBLIC CASE"),
    ),
    "scarce-couriers": Scenario(
        "scarce-couriers",
        "骑手稀缺",
        "从公开样例保留前 25% 骑手，验证供给收紧时的覆盖与期望损失。",
        ("SCARCE COURIERS", "COVERAGE", "DERIVED PUBLIC CASE"),
    ),
    "constrained-medium": Scenario(
        "constrained-medium",
        "中型约束实例",
        "从公开样例固定抽取 30 个订单与 30 名骑手，检查专项改进是否可泛化。",
        ("CONSTRAINED", "GENERALIZATION", "DERIVED PUBLIC CASE"),
    ),
}


def scenario_payload(scenario: Scenario) -> dict:
    return {
        "id": scenario.id,
        "name": scenario.name,
        "narrative": scenario.narrative,
        "tags": list(scenario.tags),
    }


def _task_key(task_str: str) -> tuple[str, ...]:
    return tuple(sorted(item.strip() for item in task_str.split(",") if item.strip()))


def _parse_rows(input_text: str) -> tuple[str, list[list[str]]]:
    lines = input_text.strip().splitlines()
    rows = [line.split("\t")[:4] for line in lines[1:] if len(line.split("\t")) >= 4]
    return lines[0], rows


def _render(header: str, rows: list[list[str]]) -> str:
    return header + "\n" + "\n".join("\t".join(row) for row in rows)


def _couriers(rows: list[list[str]]) -> list[str]:
    return list(dict.fromkeys(row[1].strip() for row in rows))


def _tasks(rows: list[list[str]]) -> list[str]:
    return sorted({task for row in rows for task in _task_key(row[0])})


def _keep_tasks(rows: list[list[str]], count: int, seed: int) -> list[list[str]]:
    keep = set(random.Random(seed).sample(_tasks(rows), count))
    return [row[:] for row in rows if all(task in keep for task in _task_key(row[0]))]


def _keep_couriers(rows: list[list[str]], courier_order: list[str], count: int) -> list[list[str]]:
    keep = set(courier_order[:count])
    return [row[:] for row in rows if row[1].strip() in keep]


def _drop_pair_edges(rows: list[list[str]], probability: float, seed: int) -> list[list[str]]:
    rng = random.Random(seed)
    return [
        row[:] for row in rows
        if len(_task_key(row[0])) == 1 or rng.random() <= probability
    ]


def _scale_willingness(rows: list[list[str]], factor: float) -> list[list[str]]:
    output = []
    for source in rows:
        row = source[:]
        row[3] = f"{max(0.01, min(0.99, float(row[3]) * factor)):.6f}"
        output.append(row)
    return output


@lru_cache(maxsize=None)
def scenario_text(scenario_id: str) -> str:
    """Build demo input in memory from the only public seed case."""
    if scenario_id not in SCENARIOS:
        raise ValueError("unknown scenario")
    header, rows = _parse_rows(SOURCE_CASE.read_text())
    courier_order = _couriers(rows)
    if scenario_id == "low-willingness":
        rows = _keep_tasks(rows, 30, 501)
        rows = _keep_couriers(rows, courier_order, 60)
        rows = _drop_pair_edges(rows, 0.25, 1501)
        rows = _scale_willingness(rows, 0.25)
    elif scenario_id == "scarce-couriers":
        rows = _keep_couriers(rows, courier_order, int(len(courier_order) * 0.25))
    elif scenario_id == "constrained-medium":
        rows = _keep_tasks(rows, 30, 201)
        rows = _keep_couriers(rows, courier_order, 30)
    return _render(header, rows)


def analyze_input(input_text: str) -> dict:
    _, rows = _parse_rows(input_text)
    tasks = _tasks(rows)
    couriers = _couriers(rows)
    bundle_sizes = Counter(len(_task_key(row[0])) for row in rows)
    pair_keys = {_task_key(row[0]) for row in rows if len(_task_key(row[0])) == 2}
    possible_pairs = len(tasks) * (len(tasks) - 1) / 2
    willingness = fmean(float(row[3]) for row in rows) if rows else 0.0
    tags = []
    if willingness < 0.18:
        tags.append("LOW WILLINGNESS")
    ratio = len(couriers) / len(tasks) if tasks else 0.0
    tags.append("SCARCE COURIERS" if ratio <= 1.0 else "AVAILABLE SUPPLY")
    if bundle_sizes[2] > bundle_sizes[1]:
        tags.append("PAIR-RICH")
    return {
        "tasks": len(tasks),
        "couriers": len(couriers),
        "candidates": len(rows),
        "avg_willingness": round(willingness, 4),
        "courier_ratio": round(ratio, 2),
        "pair_density": round(len(pair_keys) / possible_pairs, 3) if possible_pairs else 0.0,
        "tags": tags,
    }
