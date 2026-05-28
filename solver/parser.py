"""Input parsing and shared problem data structures."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Dict, List, Sequence, Tuple


TaskKey = Tuple[str, ...]
Solution = List[Tuple[str, List[str]]]


def canonical_task_key(task_id_list: str) -> TaskKey:
    """Return a stable bundle key regardless of input task order."""
    return tuple(sorted(task.strip() for task in task_id_list.split(",") if task.strip()))


@dataclass(frozen=True)
class Candidate:
    task_key: TaskKey
    task_str: str
    courier_id: str
    total_score: float
    willingness: float

    @property
    def task_count(self) -> int:
        return len(self.task_key)

    @property
    def expected_cost(self) -> float:
        penalty = 100.0 * self.task_count
        return self.willingness * self.total_score + (1.0 - self.willingness) * penalty

    @property
    def gain(self) -> float:
        return 100.0 * self.task_count - self.expected_cost


@dataclass
class Problem:
    raw_text: str
    candidates: List[Candidate]
    candidate_map: Dict[Tuple[TaskKey, str], Candidate]
    task_ids: set[str]
    courier_ids: set[str]
    task_lists: set[TaskKey]
    candidates_by_task: Dict[str, List[Candidate]]
    candidates_by_courier: Dict[str, List[Candidate]]
    candidates_by_bundle: Dict[TaskKey, List[Candidate]]
    skipped_rows: int = 0

    @property
    def num_tasks(self) -> int:
        return len(self.task_ids)

    @property
    def num_couriers(self) -> int:
        return len(self.courier_ids)


def parse_problem(input_text: str) -> Problem:
    """Parse a TSV case and retain one record for each bundle/courier pair."""
    candidate_map: Dict[Tuple[TaskKey, str], Candidate] = {}
    task_ids: set[str] = set()
    courier_ids: set[str] = set()
    task_lists: set[TaskKey] = set()
    skipped_rows = 0

    lines = input_text.strip().splitlines()
    start = 1 if lines and lines[0].strip().startswith("task_id_list") else 0
    for line in lines[start:]:
        if not line.strip():
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 4:
            skipped_rows += 1
            continue
        task_key = canonical_task_key(parts[0])
        courier_id = parts[1].strip()
        try:
            total_score = float(parts[2])
            willingness = float(parts[3])
        except ValueError:
            skipped_rows += 1
            continue
        if not task_key or not courier_id:
            skipped_rows += 1
            continue
        candidate = Candidate(
            task_key=task_key,
            task_str=",".join(task_key),
            courier_id=courier_id,
            total_score=total_score,
            willingness=willingness,
        )
        candidate_map[(task_key, courier_id)] = candidate
        task_ids.update(task_key)
        courier_ids.add(courier_id)
        task_lists.add(task_key)

    candidates = list(candidate_map.values())
    by_task: DefaultDict[str, List[Candidate]] = defaultdict(list)
    by_courier: DefaultDict[str, List[Candidate]] = defaultdict(list)
    by_bundle: DefaultDict[TaskKey, List[Candidate]] = defaultdict(list)
    for candidate in candidates:
        for task_id in candidate.task_key:
            by_task[task_id].append(candidate)
        by_courier[candidate.courier_id].append(candidate)
        by_bundle[candidate.task_key].append(candidate)

    return Problem(
        raw_text=input_text,
        candidates=candidates,
        candidate_map=candidate_map,
        task_ids=task_ids,
        courier_ids=courier_ids,
        task_lists=task_lists,
        candidates_by_task=dict(by_task),
        candidates_by_courier=dict(by_courier),
        candidates_by_bundle=dict(by_bundle),
        skipped_rows=skipped_rows,
    )


def normalize_solution(solution: Sequence[Tuple[str, Sequence[str]]]) -> Solution:
    """Materialize any solver output in the public list format."""
    return [
        (",".join(canonical_task_key(task_str)), [str(courier).strip() for courier in couriers])
        for task_str, couriers in solution
    ]
