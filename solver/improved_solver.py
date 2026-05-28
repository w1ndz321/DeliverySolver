#!/usr/bin/env python3
"""
OJ submission solver.
The solver optimizes the official expected-cost objective rather than raw
total_score. It tries several deterministic starts and keeps the best solution
under the same evaluator used by the local judge.
"""
import random
import time
import itertools
from collections import defaultdict
DIAG_MODE = "final"
def _task_key(task_str):
    return tuple(sorted(t.strip() for t in task_str.split(",") if t.strip()))
def _bundle_cost(task_count, entries):
    reject_prob = 1.0
    weighted_score = 0.0
    willingness_sum = 0.0
    for score, courier_id, willingness, task_str in entries:
        reject_prob *= 1.0 - willingness
        weighted_score += willingness * score
        willingness_sum += willingness
    if willingness_sum <= 0.0:
        return 100.0 * task_count
    accept_prob = 1.0 - reject_prob
    accepted_score = weighted_score / willingness_sum
    return accept_prob * accepted_score + reject_prob * 100.0 * task_count
def _parse(input_text):
    lines = input_text.strip().splitlines()
    start = 1 if lines and lines[0].startswith("task_id_list") else 0
    task_ids = set()
    courier_ids = set()
    rows = []
    by_bundle = defaultdict(list)
    single_by_task = defaultdict(list)
    entry_by_task_courier = {}
    candidate_map = {}
    willingness_total = 0.0
    candidate_count = 0
    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        task_str, courier_id, score_str, willingness_str = parts[:4]
        try:
            score = float(score_str)
            willingness = float(willingness_str)
        except ValueError:
            continue
        raw_task_str = task_str.strip()
        task_key = _task_key(raw_task_str)
        courier_id = courier_id.strip()
        entry = (score, courier_id, willingness, raw_task_str)
        willingness_total += willingness
        candidate_count += 1
        rows.append((task_key, entry))
        by_bundle[task_key].append(entry)
        candidate_map[(task_key, courier_id)] = entry
        task_ids.update(task_key)
        courier_ids.add(courier_id)
        if len(task_key) == 1:
            task_id = task_key[0]
            single_by_task[task_id].append(entry)
            entry_by_task_courier[(task_id, courier_id)] = entry
    for entries in by_bundle.values():
        entries.sort()
    for entries in single_by_task.values():
        entries.sort()
    return {
        "task_ids": sorted(task_ids),
        "courier_ids": sorted(courier_ids),
        "rows": rows,
        "by_bundle": by_bundle,
        "single_by_task": single_by_task,
        "entry_by_task_courier": entry_by_task_courier,
        "candidate_map": candidate_map,
        "avg_willingness": willingness_total / candidate_count if candidate_count else 0.0,
    }
def _evaluate_solution(solution, data):
    covered = set()
    used = set()
    total = 0.0
    for task_str, couriers in solution:
        task_key = _task_key(task_str)
        if not task_key or any(task_id in covered for task_id in task_key):
            return float("inf")
        entries = []
        local = set()
        for courier_id in couriers:
            if courier_id in used or courier_id in local:
                return float("inf")
            entry = data["candidate_map"].get((task_key, courier_id))
            if entry is None:
                return float("inf")
            entries.append(entry)
            local.add(courier_id)
        if not entries:
            return float("inf")
        total += _bundle_cost(len(task_key), entries)
        covered.update(task_key)
        used.update(local)
    total += 100.0 * (len(data["task_ids"]) - len(covered))
    return total
def _official_baseline(data):
    rows = []
    for task_key, entry in data["rows"]:
        score, courier_id, willingness, task_str = entry
        rows.append((score, task_key, task_str, courier_id))
    rows.sort(key=lambda item: item[0])
    used_couriers = set()
    covered = set()
    result = []
    for score, task_key, task_str, courier_id in rows:
        if courier_id in used_couriers:
            continue
        if any(task_id in covered for task_id in task_key):
            continue
        used_couriers.add(courier_id)
        covered.update(task_key)
        result.append((task_str, [courier_id]))
    return result
def _weighted_greedy_baseline(data, mode):
    rows = []
    for task_key, entry in data["rows"]:
        score, courier_id, willingness, task_str = entry
        expected = _bundle_cost(len(task_key), [entry])
        if mode == "willingness":
            key = (-willingness, expected, score)
        elif mode == "balanced":
            key = (0.65 * expected - 18.0 * willingness, expected, score)
        elif mode == "larger_first":
            key = (-len(task_key), expected / len(task_key), expected)
        else:
            key = (expected, score)
        rows.append((key, task_key, task_str, courier_id))
    rows.sort(key=lambda item: item[0])
    used_couriers = set()
    covered = set()
    result = []
    for _, task_key, task_str, courier_id in rows:
        if courier_id in used_couriers:
            continue
        if any(task_id in covered for task_id in task_key):
            continue
        used_couriers.add(courier_id)
        covered.update(task_key)
        result.append((task_str, [courier_id]))
    return result
def _single_task_cost(entries):
    return _bundle_cost(1, entries)
def _greedy_single_start(data, alpha, seed, warmups=0):
    rng = random.Random(seed)
    for _ in range(warmups):
        rng.randrange(6)
    tasks = data["task_ids"]
    couriers = data["courier_ids"]
    single_by_task = data["single_by_task"]
    assignments = {task_id: [] for task_id in tasks if task_id in single_by_task}
    used = {}
    while len(used) < len(couriers):
        options = []
        best_benefit = 0.0
        for task_id in tasks:
            entries = single_by_task.get(task_id)
            if not entries:
                continue
            current = _single_task_cost(assignments[task_id])
            selected = {entry[1] for entry in assignments[task_id]}
            for entry in entries:
                courier_id = entry[1]
                if courier_id in used or courier_id in selected:
                    continue
                benefit = current - _single_task_cost(assignments[task_id] + [entry])
                if benefit <= 1e-12:
                    continue
                if benefit > best_benefit:
                    best_benefit = benefit
                options.append((benefit, task_id, entry))
        if not options:
            break
        if alpha > 0.0:
            threshold = best_benefit * (1.0 - alpha)
            restricted = [item for item in options if item[0] >= threshold]
            benefit, task_id, entry = rng.choice(restricted)
        else:
            benefit, task_id, entry = max(options, key=lambda item: item[0])
        assignments[task_id].append(entry)
        used[entry[1]] = task_id
    return assignments
def _local_search_single(assignments, data, max_passes=24):
    tasks = [task_id for task_id in data["task_ids"] if task_id in data["single_by_task"]]
    entry_by_task_courier = data["entry_by_task_courier"]
    used = {entry[1]: task_id for task_id, entries in assignments.items() for entry in entries}
    for _ in range(max_passes):
        best = None
        # Move one courier to another task.
        for courier_id, src_task in list(used.items()):
            src_entries = assignments[src_task]
            old_src = _single_task_cost(src_entries)
            new_src_entries = [entry for entry in src_entries if entry[1] != courier_id]
            new_src = _single_task_cost(new_src_entries)
            for dst_task in tasks:
                if dst_task == src_task:
                    continue
                dst_entry = entry_by_task_courier.get((dst_task, courier_id))
                if dst_entry is None:
                    continue
                old_dst = _single_task_cost(assignments[dst_task])
                new_dst = _single_task_cost(assignments[dst_task] + [dst_entry])
                delta = (new_src + new_dst) - (old_src + old_dst)
                if delta < -1e-10 and (best is None or delta < best[0]):
                    best = (delta, "move", courier_id, src_task, dst_task, dst_entry)
        # Swap two couriers between their current tasks.
        used_items = list(used.items())
        for i, (courier_a, task_a) in enumerate(used_items):
            for courier_b, task_b in used_items[i + 1 :]:
                if task_a == task_b:
                    continue
                entry_a_to_b = entry_by_task_courier.get((task_b, courier_a))
                entry_b_to_a = entry_by_task_courier.get((task_a, courier_b))
                if entry_a_to_b is None or entry_b_to_a is None:
                    continue
                old_cost = _single_task_cost(assignments[task_a]) + _single_task_cost(assignments[task_b])
                new_a = [entry for entry in assignments[task_a] if entry[1] != courier_a] + [entry_b_to_a]
                new_b = [entry for entry in assignments[task_b] if entry[1] != courier_b] + [entry_a_to_b]
                new_cost = _single_task_cost(new_a) + _single_task_cost(new_b)
                delta = new_cost - old_cost
                if delta < -1e-10 and (best is None or delta < best[0]):
                    best = (delta, "swap", courier_a, task_a, courier_b, task_b, entry_a_to_b, entry_b_to_a)
        if best is None:
            break
        if best[1] == "move":
            _, _, courier_id, src_task, dst_task, dst_entry = best
            assignments[src_task] = [entry for entry in assignments[src_task] if entry[1] != courier_id]
            assignments[dst_task].append(dst_entry)
            used[courier_id] = dst_task
        else:
            _, _, courier_a, task_a, courier_b, task_b, entry_a_to_b, entry_b_to_a = best
            assignments[task_a] = [entry for entry in assignments[task_a] if entry[1] != courier_a] + [entry_b_to_a]
            assignments[task_b] = [entry for entry in assignments[task_b] if entry[1] != courier_b] + [entry_a_to_b]
            used[courier_a] = task_b
            used[courier_b] = task_a
    return assignments
def _assignments_to_solution(assignments):
    result = []
    for task_id in sorted(assignments):
        entries = sorted(assignments[task_id])
        if not entries:
            continue
        result.append((entries[0][3], [entry[1] for entry in entries]))
    return result
def _solution_to_single_assignments(solution, data):
    assignments = {task_id: [] for task_id in data["task_ids"] if task_id in data["single_by_task"]}
    for task_str, couriers in solution:
        task_key = _task_key(task_str)
        if len(task_key) != 1:
            return None
        task_id = task_key[0]
        entries = []
        for courier_id in couriers:
            entry = data["entry_by_task_courier"].get((task_id, courier_id))
            if entry is None:
                return None
            entries.append(entry)
        assignments[task_id] = entries
    return assignments
def _local_search_single_cycles(assignments, data, deadline, max_passes=4):
    assignments = _copy_assignments(assignments)
    entry_by_task_courier = data["entry_by_task_courier"]
    for _ in range(max_passes):
        if time.perf_counter() >= deadline:
            break
        used_items = [
            (entry[1], task_id)
            for task_id, entries in assignments.items()
            for entry in entries
        ]
        task_costs = {
            task_id: _single_task_cost(entries)
            for task_id, entries in assignments.items()
            if entries
        }
        best = None
        for i, (courier_a, task_a) in enumerate(used_items):
            for j in range(i + 1, len(used_items)):
                courier_b, task_b = used_items[j]
                if task_a == task_b:
                    continue
                for k in range(j + 1, len(used_items)):
                    courier_c, task_c = used_items[k]
                    if task_c == task_a or task_c == task_b:
                        continue
                    old_cost = task_costs[task_a] + task_costs[task_b] + task_costs[task_c]
                    cycles = (
                        (
                            (task_a, courier_a, courier_c),
                            (task_b, courier_b, courier_a),
                            (task_c, courier_c, courier_b),
                        ),
                        (
                            (task_a, courier_a, courier_b),
                            (task_b, courier_b, courier_c),
                            (task_c, courier_c, courier_a),
                        ),
                    )
                    for cycle in cycles:
                        next_entries = []
                        possible = True
                        for task_id, old_courier, next_courier in cycle:
                            entry = entry_by_task_courier.get((task_id, next_courier))
                            if entry is None:
                                possible = False
                                break
                            next_task_entries = [
                                item for item in assignments[task_id] if item[1] != old_courier
                            ] + [entry]
                            next_entries.append((task_id, next_task_entries, next_courier))
                        if not possible:
                            continue
                        new_cost = sum(_single_task_cost(entries) for _, entries, _ in next_entries)
                        delta = new_cost - old_cost
                        if delta < -1e-10 and (best is None or delta < best[0]):
                            best = (delta, cycle, next_entries)
        if best is None:
            break
        _, cycle, next_entries = best
        for task_id, entries, _ in next_entries:
            assignments[task_id] = entries
    return assignments
def _local_search_single_pair_blocks(assignments, data, deadline, max_passes=6):
    assignments = _copy_assignments(assignments)
    tasks = [task_id for task_id, entries in assignments.items() if entries]
    entry_by_task_courier = data["entry_by_task_courier"]
    for _ in range(max_passes):
        if time.perf_counter() >= deadline:
            break
        best = None
        for i, task_a in enumerate(tasks):
            entries_a = assignments[task_a]
            if not entries_a:
                continue
            for task_b in tasks[i + 1 :]:
                entries_b = assignments[task_b]
                if not entries_b:
                    continue
                couriers = [entry[1] for entry in entries_a] + [entry[1] for entry in entries_b]
                if len(couriers) < 3 or len(couriers) > 8:
                    continue
                old_cost = _single_task_cost(entries_a) + _single_task_cost(entries_b)
                full_mask = (1 << len(couriers)) - 1
                for mask in range(1, full_mask):
                    if mask == full_mask:
                        continue
                    next_a = []
                    next_b = []
                    possible = True
                    for index, courier_id in enumerate(couriers):
                        if mask & (1 << index):
                            entry = entry_by_task_courier.get((task_a, courier_id))
                            if entry is None:
                                possible = False
                                break
                            next_a.append(entry)
                        else:
                            entry = entry_by_task_courier.get((task_b, courier_id))
                            if entry is None:
                                possible = False
                                break
                            next_b.append(entry)
                    if not possible or not next_a or not next_b:
                        continue
                    new_cost = _single_task_cost(next_a) + _single_task_cost(next_b)
                    delta = new_cost - old_cost
                    if delta < -1e-10 and (best is None or delta < best[0]):
                        best = (delta, task_a, task_b, next_a, next_b)
        if best is None:
            break
        _, task_a, task_b, next_a, next_b = best
        assignments[task_a] = next_a
        assignments[task_b] = next_b
    return assignments
def _local_search_single_triple_blocks(assignments, data, deadline, max_passes=3):
    assignments = _copy_assignments(assignments)
    entry_by_task_courier = data["entry_by_task_courier"]
    for _ in range(max_passes):
        if time.perf_counter() >= deadline:
            break
        task_costs = {
            task_id: _single_task_cost(entries)
            for task_id, entries in assignments.items()
            if entries
        }
        tasks = sorted(task_costs, key=lambda task_id: task_costs[task_id], reverse=True)[:14]
        best = None
        for i, task_a in enumerate(tasks):
            entries_a = assignments[task_a]
            for j in range(i + 1, len(tasks)):
                task_b = tasks[j]
                entries_b = assignments[task_b]
                for task_c in tasks[j + 1 :]:
                    entries_c = assignments[task_c]
                    couriers = [entry[1] for entry in entries_a + entries_b + entries_c]
                    if len(couriers) < 4 or len(couriers) > 10:
                        continue
                    old_cost = task_costs[task_a] + task_costs[task_b] + task_costs[task_c]
                    full_mask = (1 << len(couriers)) - 1
                    mask_costs = {}
                    possible = True
                    for task_id in (task_a, task_b, task_c):
                        costs = {}
                        for mask in range(1, full_mask + 1):
                            entries = []
                            for index, courier_id in enumerate(couriers):
                                if not (mask & (1 << index)):
                                    continue
                                entry = entry_by_task_courier.get((task_id, courier_id))
                                if entry is None:
                                    entries = None
                                    break
                                entries.append(entry)
                            if entries is not None:
                                costs[mask] = _single_task_cost(entries)
                        if not costs:
                            possible = False
                            break
                        mask_costs[task_id] = costs
                    if not possible:
                        continue
                    for mask_a, cost_a in mask_costs[task_a].items():
                        remaining_ab = full_mask ^ mask_a
                        if not remaining_ab:
                            continue
                        sub = remaining_ab
                        while sub:
                            mask_b = sub
                            mask_c = remaining_ab ^ mask_b
                            if mask_c:
                                cost_b = mask_costs[task_b].get(mask_b)
                                cost_c = mask_costs[task_c].get(mask_c)
                                if cost_b is not None and cost_c is not None:
                                    new_cost = cost_a + cost_b + cost_c
                                    delta = new_cost - old_cost
                                    if delta < -1e-10 and (best is None or delta < best[0]):
                                        best = (delta, task_a, task_b, task_c, mask_a, mask_b, mask_c, couriers)
                            sub = (sub - 1) & remaining_ab
        if best is None:
            break
        _, task_a, task_b, task_c, mask_a, mask_b, mask_c, couriers = best
        next_entries = {task_a: [], task_b: [], task_c: []}
        for index, courier_id in enumerate(couriers):
            bit = 1 << index
            if mask_a & bit:
                task_id = task_a
            elif mask_b & bit:
                task_id = task_b
            else:
                task_id = task_c
            next_entries[task_id].append(entry_by_task_courier[(task_id, courier_id)])
        assignments[task_a] = next_entries[task_a]
        assignments[task_b] = next_entries[task_b]
        assignments[task_c] = next_entries[task_c]
    return assignments
def _postprocess_single_assignments(assignments, data, deadline):
    assignments = _destroy_repair_single(assignments, data, deadline)
    if time.perf_counter() < deadline:
        assignments = _local_search_single_pair_blocks(assignments, data, deadline)
    if time.perf_counter() < deadline:
        assignments = _local_search_single_cycles(assignments, data, deadline)
    if time.perf_counter() < deadline and len(data["courier_ids"]) >= len(data["task_ids"]) * 2:
        assignments = _local_search_single_triple_blocks(assignments, data, deadline)
    if time.perf_counter() < deadline and len(data["courier_ids"]) >= len(data["task_ids"]) * 2:
        assignments = _focused_repair_single(assignments, data, deadline)
    if time.perf_counter() < deadline and len(data["courier_ids"]) > len(data["task_ids"]):
        assignments = _extra_general_destroy_repair_single(assignments, data, deadline)
    return assignments
def _single_multistart(data, deadline):
    if len(data["task_ids"]) >= 40 and len(data["courier_ids"]) > len(data["task_ids"]):
        if data["avg_willingness"] < 0.18:
            starts = [
                (0.03, 75, 0),
                (0.02, 55, 1),
                (0.00, 0, 0),
                (0.08, 31, 0),
            ]
        else:
            starts = [(0.03, 75, 0)]
    else:
        starts = [
            (0.03, 75, 0),
            (0.02, 55, 1),
            (0.02, 33, 0),
            (0.00, 0, 0),
            (0.10, 7, 0),
            (0.05, 51, 0),
            (0.03, 19, 0),
            (0.08, 31, 0),
            (0.12, 43, 0),
            (0.15, 67, 0),
            (0.20, 79, 0),
            (0.05, 91, 0),
            (0.02, 103, 0),
            (0.10, 127, 0),
        ]
    best_solution = None
    best_assignments = None
    best_score = float("inf")
    start_candidates = []
    for start_index, (alpha, seed, warmups) in enumerate(starts):
        if time.perf_counter() >= deadline:
            break
        assignments = _greedy_single_start(data, alpha, seed, warmups)
        assignments = _local_search_single(assignments, data)
        solution = _assignments_to_solution(assignments)
        score = _evaluate_solution(solution, data)
        start_candidates.append((score, start_index, assignments))
        if score < best_score:
            best_score = score
            best_solution = solution
            best_assignments = assignments
    if best_assignments is not None and time.perf_counter() < deadline:
        best_assignments = _postprocess_single_assignments(best_assignments, data, deadline)
        best_score = _assignments_score_full(best_assignments, data)
        if (
            time.perf_counter() < deadline
            and len(data["courier_ids"]) > len(data["task_ids"])
            and len(data["task_ids"]) <= 30
            and data["avg_willingness"] >= 0.18
        ):
            start_candidates.sort(key=lambda item: item[0])
            best_start_index = start_candidates[0][1]
            by_index = {start_index: assignments for _, start_index, assignments in start_candidates}
            ordered = []
            seen = {best_start_index}
            for _, start_index, candidate_assignments in start_candidates[1:3]:
                if start_index not in seen:
                    ordered.append(candidate_assignments)
                    seen.add(start_index)
            for start_index in (5, 2, 4, 12, 6, 3, 1, 8, 7, 10, 11):
                if start_index in by_index and start_index not in seen:
                    ordered.append(by_index[start_index])
                    seen.add(start_index)
            for _, start_index, candidate_assignments in start_candidates[1:]:
                if start_index not in seen:
                    ordered.append(candidate_assignments)
                    seen.add(start_index)
            for candidate_assignments in ordered[:5]:
                if time.perf_counter() >= deadline:
                    break
                candidate = _postprocess_single_assignments(candidate_assignments, data, deadline)
                candidate_score = _assignments_score_full(candidate, data)
                if candidate_score < best_score - 1e-10:
                    best_assignments = candidate
                    best_score = candidate_score
        best_solution = _assignments_to_solution(best_assignments)
    return best_solution if best_solution is not None else []
def _copy_assignments(assignments):
    return {task_id: entries[:] for task_id, entries in assignments.items()}
def _assignments_score(assignments):
    total = 0.0
    for entries in assignments.values():
        if entries:
            total += _single_task_cost(entries)
    return total
def _assignments_score_full(assignments, data):
    total = 0.0
    for task_id in data["task_ids"]:
        entries = assignments.get(task_id, [])
        total += _single_task_cost(entries) if entries else 100.0
    return total
def _repair_removed_couriers(assignments, data, seed, remove_count, alpha):
    rng = random.Random(seed)
    repaired = _copy_assignments(assignments)
    used_couriers = [entry[1] for entries in repaired.values() for entry in entries]
    rng.shuffle(used_couriers)
    removed = set(used_couriers[: min(remove_count, len(used_couriers))])
    for task_id in repaired:
        repaired[task_id] = [entry for entry in repaired[task_id] if entry[1] not in removed]
    assigned = {entry[1] for entries in repaired.values() for entry in entries}
    all_couriers = data["courier_ids"]
    while True:
        options = []
        best_benefit = 0.0
        for task_id in data["task_ids"]:
            if task_id not in repaired:
                repaired[task_id] = []
            current_entries = repaired[task_id]
            current_cost = _single_task_cost(current_entries) if current_entries else 100.0
            selected = {entry[1] for entry in current_entries}
            for courier_id in all_couriers:
                if courier_id in assigned or courier_id in selected:
                    continue
                entry = data["entry_by_task_courier"].get((task_id, courier_id))
                if entry is None:
                    continue
                benefit = current_cost - _single_task_cost(current_entries + [entry])
                if benefit <= 1e-12:
                    continue
                if benefit > best_benefit:
                    best_benefit = benefit
                options.append((benefit, task_id, entry))
        if not options:
            break
        if alpha > 0.0:
            threshold = best_benefit * (1.0 - alpha)
            restricted = [item for item in options if item[0] >= threshold]
            benefit, task_id, entry = rng.choice(restricted)
        else:
            benefit, task_id, entry = max(options, key=lambda item: item[0])
        repaired[task_id].append(entry)
        assigned.add(entry[1])
    return _local_search_single(repaired, data)
def _repair_specific_couriers(assignments, data, removed, seed, alpha, bonus_tasks=None, bonus=0.0):
    rng = random.Random(seed)
    repaired = _copy_assignments(assignments)
    removed = set(removed)
    bonus_tasks = set(bonus_tasks or ())
    for task_id in repaired:
        repaired[task_id] = [entry for entry in repaired[task_id] if entry[1] not in removed]
    assigned = {entry[1] for entries in repaired.values() for entry in entries}
    all_couriers = data["courier_ids"]
    while True:
        options = []
        best_key = 0.0
        for task_id in data["task_ids"]:
            if task_id not in repaired:
                repaired[task_id] = []
            current_entries = repaired[task_id]
            current_cost = _single_task_cost(current_entries) if current_entries else 100.0
            selected = {entry[1] for entry in current_entries}
            for courier_id in all_couriers:
                if courier_id in assigned or courier_id in selected:
                    continue
                entry = data["entry_by_task_courier"].get((task_id, courier_id))
                if entry is None:
                    continue
                benefit = current_cost - _single_task_cost(current_entries + [entry])
                if benefit <= 1e-12:
                    continue
                key = benefit + (bonus if task_id in bonus_tasks else 0.0)
                if key > best_key:
                    best_key = key
                options.append((key, benefit, task_id, entry))
        if not options:
            break
        if alpha > 0.0:
            threshold = best_key * (1.0 - alpha)
            restricted = [item for item in options if item[0] >= threshold]
            _, _, task_id, entry = rng.choice(restricted)
        else:
            _, _, task_id, entry = max(options, key=lambda item: item[0])
        repaired[task_id].append(entry)
        assigned.add(entry[1])
    return _local_search_single(repaired, data)
def _focused_repair_single(assignments, data, deadline):
    best = _copy_assignments(assignments)
    best_score = _assignments_score_full(best, data)
    configs = (
        (8, 0.00, 211),
        (12, 0.02, 223),
        (16, 0.05, 227),
        (24, 0.08, 229),
        (32, 0.10, 233),
    )
    for remove_count, alpha, seed in configs:
        if time.perf_counter() >= deadline:
            break
        marginals = []
        for task_id, entries in best.items():
            if not entries:
                continue
            current = _single_task_cost(entries)
            for entry in entries:
                without = [item for item in entries if item[1] != entry[1]]
                without_cost = _single_task_cost(without) if without else 100.0
                marginal = without_cost - current
                standalone_gain = 100.0 - _single_task_cost([entry])
                marginals.append((marginal, standalone_gain, entry[1]))
        if not marginals:
            break
        marginals.sort(key=lambda item: (item[0], item[1]))
        removed = [courier_id for _, _, courier_id in marginals[: min(remove_count, len(marginals))]]
        candidate = _repair_specific_couriers(best, data, removed, seed, alpha)
        score = _assignments_score_full(candidate, data)
        if score < best_score - 1e-10:
            best = candidate
            best_score = score
    return best
def _extra_low_destroy_repair_single(assignments, data, deadline):
    best = _copy_assignments(assignments)
    best_score = _assignments_score_full(best, data)
    configs = (
        (100, 30, 0.20),
        (100, 36, 0.20),
        (102, 20, 0.35),
        (103, 8, 0.20),
        (104, 12, 0.35),
        (105, 24, 0.08),
        (101, 8, 0.35),
        (102, 12, 0.00),
        (106, 30, 0.12),
        (108, 16, 0.35),
        (109, 24, 0.20),
        (111, 36, 0.12),
    )
    for seed, remove_count, alpha in configs:
        if time.perf_counter() >= deadline:
            break
        candidate = _repair_removed_couriers(best, data, seed, remove_count, alpha)
        score = _assignments_score_full(candidate, data)
        if score < best_score - 1e-10:
            best = candidate
            best_score = score
    return best
def _extra_general_destroy_repair_single(assignments, data, deadline):
    best = _copy_assignments(assignments)
    best_score = _assignments_score_full(best, data)
    configs = (
        (100, 30, 0.08),
        (103, 8, 0.20),
        (104, 12, 0.35),
        (101, 4, 0.00),
        (103, 6, 0.35),
        (105, 24, 0.08),
    )
    for seed, remove_count, alpha in configs:
        if time.perf_counter() >= deadline:
            break
        candidate = _repair_removed_couriers(best, data, seed, remove_count, alpha)
        score = _assignments_score_full(candidate, data)
        if score < best_score - 1e-10:
            best = candidate
            best_score = score
    return best
def _cost_bucket_repair_single(assignments, data, deadline):
    best = _copy_assignments(assignments)
    best_score = _assignments_score_full(best, data)
    configs = (
        (3, 0.00, 0.10, 293),
        (5, 0.00, 0.20, 307),
        (7, 0.02, 0.35, 311),
        (9, 0.05, 0.50, 313),
        (12, 0.08, 0.75, 317),
        (15, 0.10, 1.00, 331),
        (20, 0.12, 1.25, 337),
    )
    for task_count, alpha, bonus, seed in configs:
        if time.perf_counter() >= deadline:
            break
        task_costs = []
        for task_id in data["task_ids"]:
            entries = best.get(task_id, [])
            cost = _single_task_cost(entries) if entries else 100.0
            task_costs.append((cost, task_id))
        task_costs.sort(reverse=True)
        focus_tasks = [task_id for _, task_id in task_costs[: min(task_count, len(task_costs))]]
        removed = [
            entry[1]
            for task_id in focus_tasks
            for entry in best.get(task_id, [])
        ]
        if not removed:
            continue
        candidate = _repair_specific_couriers(best, data, removed, seed, alpha, focus_tasks, bonus)
        score = _assignments_score_full(candidate, data)
        if score < best_score - 1e-10:
            best = candidate
            best_score = score
    return best
def _balanced_single_solution(data, deadline):
    tasks = [task_id for task_id in data["task_ids"] if task_id in data["single_by_task"]]
    couriers = data["courier_ids"]
    if not tasks or len(couriers) < len(tasks):
        return []
    cost = []
    for task_id in tasks:
        row = []
        for courier_id in couriers:
            entry = data["entry_by_task_courier"].get((task_id, courier_id))
            row.append(_single_task_cost([entry]) if entry is not None else 1e6)
        cost.append(row)
    assignment = _hungarian(cost)
    base = {task_id: [] for task_id in tasks}
    used = set()
    for task_index, courier_index in enumerate(assignment):
        if courier_index < 0 or courier_index >= len(couriers):
            continue
        task_id = tasks[task_index]
        courier_id = couriers[courier_index]
        entry = data["entry_by_task_courier"].get((task_id, courier_id))
        if entry is not None and courier_id not in used:
            base[task_id].append(entry)
            used.add(courier_id)
    if any(not base.get(task_id) for task_id in tasks):
        return []
    configs = (
        (0.15, 0.00),
        (0.30, 0.00),
        (0.45, 0.02),
        (0.70, 0.05),
        (1.00, 0.08),
    )
    best_assignments = None
    best_score = float("inf")
    for pressure, alpha in configs:
        if time.perf_counter() >= deadline:
            break
        rng = random.Random(int(pressure * 1000) + int(alpha * 10000) + 401)
        assignments = _copy_assignments(base)
        assigned = set(used)
        while len(assigned) < len(couriers):
            options = []
            best_key = 0.0
            costs = {
                task_id: _single_task_cost(entries)
                for task_id, entries in assignments.items()
                if entries
            }
            avg_cost = sum(costs.values()) / len(costs) if costs else 100.0
            for task_id in tasks:
                current_entries = assignments[task_id]
                current_cost = costs[task_id]
                selected = {entry[1] for entry in current_entries}
                pressure_gain = max(0.0, current_cost - avg_cost) * pressure
                for entry in data["single_by_task"].get(task_id, []):
                    courier_id = entry[1]
                    if courier_id in assigned or courier_id in selected:
                        continue
                    benefit = current_cost - _single_task_cost(current_entries + [entry])
                    if benefit <= 1e-12:
                        continue
                    key = benefit + pressure_gain
                    if key > best_key:
                        best_key = key
                    options.append((key, benefit, task_id, entry))
            if not options:
                break
            if alpha > 0.0:
                threshold = best_key * (1.0 - alpha)
                restricted = [item for item in options if item[0] >= threshold]
                _, _, task_id, entry = rng.choice(restricted)
            else:
                _, _, task_id, entry = max(options, key=lambda item: item[0])
            assignments[task_id].append(entry)
            assigned.add(entry[1])
        assignments = _local_search_single(assignments, data)
        if time.perf_counter() < deadline:
            assignments = _local_search_single_pair_blocks(assignments, data, deadline, max_passes=3)
        if time.perf_counter() < deadline and len(couriers) >= len(tasks) * 2:
            assignments = _local_search_single_triple_blocks(assignments, data, deadline, max_passes=2)
        score = _assignments_score_full(assignments, data)
        if score < best_score:
            best_assignments = assignments
            best_score = score
    return _assignments_to_solution(best_assignments) if best_assignments is not None else []
def _destroy_repair_single(assignments, data, deadline):
    schedule = [
        (6, 20, 0.01),
        (7, 20, 0.10),
        (13, 14, 0.00),
        (17, 20, 0.01),
        (0, 24, 0.08),
        (2, 40, 0.08),
        (3, 20, 0.05),
        (4, 12, 0.10),
        (6, 24, 0.20),
        (19, 40, 0.00),
        (21, 30, 0.10),
        (22, 24, 0.02),
        (30, 8, 0.08),
        (40, 24, 0.15),
        (0, 16, 0.00),
    ]
    best = _copy_assignments(assignments)
    best_score = _assignments_score_full(best, data)
    for seed, remove_count, alpha in schedule:
        if time.perf_counter() >= deadline:
            break
        candidate = _repair_removed_couriers(best, data, seed, remove_count, alpha)
        score = _assignments_score_full(candidate, data)
        if score < best_score:
            best = candidate
            best_score = score
    return best
def _pair_greedy(data):
    by_bundle = data["by_bundle"]
    used_couriers = set()
    covered_tasks = set()
    selected = {}
    # First create a disjoint task partition. This is useful for scarce-courier
    # cases, but the final evaluator decides whether to keep it.
    while len(covered_tasks) < len(data["task_ids"]):
        best = None
        for task_key, entries in by_bundle.items():
            if any(task_id in covered_tasks for task_id in task_key):
                continue
            base_cost = 100.0 * len(task_key)
            for entry in entries:
                courier_id = entry[1]
                if courier_id in used_couriers:
                    continue
                benefit = base_cost - _bundle_cost(len(task_key), [entry])
                if benefit > 1e-12 and (best is None or benefit > best[0]):
                    best = (benefit, task_key, entry)
        if best is None:
            break
        _, task_key, entry = best
        selected[task_key] = [entry]
        used_couriers.add(entry[1])
        covered_tasks.update(task_key)
    _repair_pair_partition(selected, data)
    # Then add extra couriers to already selected bundles by true marginal gain.
    while len(used_couriers) < len(data["courier_ids"]):
        best = None
        for task_key, entries in selected.items():
            current = _bundle_cost(len(task_key), entries)
            selected_couriers = {entry[1] for entry in entries}
            for entry in by_bundle[task_key]:
                courier_id = entry[1]
                if courier_id in used_couriers or courier_id in selected_couriers:
                    continue
                benefit = current - _bundle_cost(len(task_key), entries + [entry])
                if benefit > 1e-12 and (best is None or benefit > best[0]):
                    best = (benefit, task_key, entry)
        if best is None:
            break
        _, task_key, entry = best
        selected[task_key].append(entry)
        used_couriers.add(entry[1])
    selected = _local_search_bundles(selected, data)
    result = []
    for task_key in sorted(selected):
        entries = sorted(selected[task_key])
        result.append((entries[0][3], [entry[1] for entry in entries]))
    return result
def _repair_pair_partition(selected, data, max_passes=32):
    for _ in range(max_passes):
        best = None
        keys = [task_key for task_key, entries in selected.items() if len(task_key) == 2 and len(entries) == 1]
        for i, task_key_a in enumerate(keys):
            for task_key_b in keys[i + 1 :]:
                tasks = list(task_key_a + task_key_b)
                courier_a = selected[task_key_a][0][1]
                courier_b = selected[task_key_b][0][1]
                old_cost = (
                    _bundle_cost(2, selected[task_key_a])
                    + _bundle_cost(2, selected[task_key_b])
                )
                pairings = (
                    ((tasks[0], tasks[2]), (tasks[1], tasks[3])),
                    ((tasks[0], tasks[3]), (tasks[1], tasks[2])),
                )
                for next_a, next_b in pairings:
                    next_key_a = tuple(sorted(next_a))
                    next_key_b = tuple(sorted(next_b))
                    for next_courier_a, next_courier_b in (
                        (courier_a, courier_b),
                        (courier_b, courier_a),
                    ):
                        next_entry_a = data["candidate_map"].get((next_key_a, next_courier_a))
                        next_entry_b = data["candidate_map"].get((next_key_b, next_courier_b))
                        if next_entry_a is None or next_entry_b is None:
                            continue
                        new_cost = _bundle_cost(2, [next_entry_a]) + _bundle_cost(2, [next_entry_b])
                        delta = new_cost - old_cost
                        if delta < -1e-10 and (best is None or delta < best[0]):
                            best = (
                                delta,
                                task_key_a,
                                task_key_b,
                                next_key_a,
                                next_entry_a,
                                next_key_b,
                                next_entry_b,
                            )
        if best is None:
            break
        _, old_key_a, old_key_b, next_key_a, next_entry_a, next_key_b, next_entry_b = best
        del selected[old_key_a]
        del selected[old_key_b]
        selected[next_key_a] = [next_entry_a]
        selected[next_key_b] = [next_entry_b]
def _task_pairings(tasks):
    if not tasks:
        return [()]
    first = tasks[0]
    pairings = []
    for index in range(1, len(tasks)):
        second = tasks[index]
        rest = tasks[1:index] + tasks[index + 1 :]
        for tail in _task_pairings(rest):
            pairings.append((tuple(sorted((first, second))),) + tail)
    return pairings
def _repair_pair_triples(selected, data, max_passes=6, top_limit=12):
    for _ in range(max_passes):
        pair_keys = [
            task_key
            for task_key, entries in selected.items()
            if len(task_key) == 2 and len(entries) == 1
        ]
        if len(pair_keys) < 3:
            break
        pair_keys.sort(
            key=lambda task_key: _bundle_cost(2, selected[task_key]),
            reverse=True,
        )
        pair_keys = pair_keys[: min(top_limit, len(pair_keys))]
        best = None
        for old_keys in itertools.combinations(pair_keys, 3):
            tasks = list(old_keys[0] + old_keys[1] + old_keys[2])
            couriers = [selected[task_key][0][1] for task_key in old_keys]
            old_cost = sum(_bundle_cost(2, selected[task_key]) for task_key in old_keys)
            for next_keys in _task_pairings(tasks):
                if len(set(next_keys)) != 3:
                    continue
                for next_couriers in itertools.permutations(couriers):
                    next_entries = []
                    possible = True
                    for task_key, courier_id in zip(next_keys, next_couriers):
                        entry = data["candidate_map"].get((task_key, courier_id))
                        if entry is None:
                            possible = False
                            break
                        next_entries.append((task_key, entry))
                    if not possible:
                        continue
                    new_cost = sum(_bundle_cost(2, [entry]) for _, entry in next_entries)
                    delta = new_cost - old_cost
                    if delta < -1e-10 and (best is None or delta < best[0]):
                        best = (delta, old_keys, next_entries)
        if best is None:
            break
        _, old_keys, next_entries = best
        for task_key in old_keys:
            del selected[task_key]
        for task_key, entry in next_entries:
            selected[task_key] = [entry]
def _local_search_bundles(selected, data, max_passes=12, deadline=None):
    selected = {task_key: entries[:] for task_key, entries in selected.items()}
    for _ in range(max_passes):
        if deadline is not None and time.perf_counter() >= deadline:
            break
        best = None
        keys = list(selected.keys())
        for src_key in keys:
            if deadline is not None and time.perf_counter() >= deadline:
                break
            old_src = _bundle_cost(len(src_key), selected[src_key])
            for entry in selected[src_key]:
                courier_id = entry[1]
                next_src = [item for item in selected[src_key] if item[1] != courier_id]
                if not next_src:
                    continue
                next_src_cost = _bundle_cost(len(src_key), next_src)
                for dst_key in keys:
                    if dst_key == src_key:
                        continue
                    if any(item[1] == courier_id for item in selected[dst_key]):
                        continue
                    dst_entry = data["candidate_map"].get((dst_key, courier_id))
                    if dst_entry is None:
                        continue
                    old_dst = _bundle_cost(len(dst_key), selected[dst_key])
                    next_dst_cost = _bundle_cost(len(dst_key), selected[dst_key] + [dst_entry])
                    delta = (next_src_cost + next_dst_cost) - (old_src + old_dst)
                    if delta < -1e-10 and (best is None or delta < best[0]):
                        best = (delta, "move", src_key, dst_key, courier_id, dst_entry)
        for index, key_a in enumerate(keys):
            if deadline is not None and time.perf_counter() >= deadline:
                break
            for key_b in keys[index + 1 :]:
                old_cost = _bundle_cost(len(key_a), selected[key_a]) + _bundle_cost(len(key_b), selected[key_b])
                for entry_a in selected[key_a]:
                    courier_a = entry_a[1]
                    for entry_b in selected[key_b]:
                        courier_b = entry_b[1]
                        next_a_entry = data["candidate_map"].get((key_a, courier_b))
                        next_b_entry = data["candidate_map"].get((key_b, courier_a))
                        if next_a_entry is None or next_b_entry is None:
                            continue
                        next_a = [item for item in selected[key_a] if item[1] != courier_a] + [next_a_entry]
                        next_b = [item for item in selected[key_b] if item[1] != courier_b] + [next_b_entry]
                        next_cost = _bundle_cost(len(key_a), next_a) + _bundle_cost(len(key_b), next_b)
                        delta = next_cost - old_cost
                        if delta < -1e-10 and (best is None or delta < best[0]):
                            best = (
                                delta,
                                "swap",
                                key_a,
                                key_b,
                                courier_a,
                                courier_b,
                                next_a_entry,
                                next_b_entry,
                            )
        if best is None:
            break
        if best[1] == "move":
            _, _, src_key, dst_key, courier_id, dst_entry = best
            selected[src_key] = [item for item in selected[src_key] if item[1] != courier_id]
            selected[dst_key].append(dst_entry)
        else:
            _, _, key_a, key_b, courier_a, courier_b, next_a_entry, next_b_entry = best
            selected[key_a] = [item for item in selected[key_a] if item[1] != courier_a] + [next_a_entry]
            selected[key_b] = [item for item in selected[key_b] if item[1] != courier_b] + [next_b_entry]
    return selected
def _coverage_first_greedy(data):
    by_bundle = data["by_bundle"]
    used_couriers = set()
    covered_tasks = set()
    selected = {}
    while len(covered_tasks) < len(data["task_ids"]) and len(used_couriers) < len(data["courier_ids"]):
        best = None
        for task_key, entries in by_bundle.items():
            new_tasks = [task_id for task_id in task_key if task_id not in covered_tasks]
            if not new_tasks:
                continue
            if len(new_tasks) != len(task_key):
                continue
            for entry in entries:
                courier_id = entry[1]
                if courier_id in used_couriers:
                    continue
                expected = _bundle_cost(len(task_key), [entry])
                benefit = 100.0 * len(task_key) - expected
                key = (len(new_tasks), benefit / len(new_tasks), -expected)
                if best is None or key > best[0]:
                    best = (key, task_key, entry)
        if best is None:
            break
        _, task_key, entry = best
        selected[task_key] = [entry]
        used_couriers.add(entry[1])
        covered_tasks.update(task_key)
    _repair_pair_partition(selected, data)
    while len(used_couriers) < len(data["courier_ids"]):
        best = None
        for task_key, entries in selected.items():
            current = _bundle_cost(len(task_key), entries)
            selected_couriers = {entry[1] for entry in entries}
            for entry in by_bundle[task_key]:
                courier_id = entry[1]
                if courier_id in used_couriers or courier_id in selected_couriers:
                    continue
                benefit = current - _bundle_cost(len(task_key), entries + [entry])
                if benefit > 1e-12 and (best is None or benefit > best[0]):
                    best = (benefit, task_key, entry)
        if best is None:
            break
        _, task_key, entry = best
        selected[task_key].append(entry)
        used_couriers.add(entry[1])
    selected = _local_search_bundles(selected, data)
    result = []
    for task_key in sorted(selected):
        entries = sorted(selected[task_key])
        result.append((entries[0][3], [entry[1] for entry in entries]))
    return result
def _estimated_pair_solution(data):
    configs = (
        ("cost", 2, False),
        ("cost", 3, False),
        ("cost", 4, False),
        ("cost", 5, False),
        ("cost", 6, False),
        ("cost", 8, False),
        ("hybrid", 5, False),
        ("hybrid", 6, False),
        ("cost", 3, True),
        ("cost", 4, True),
        ("cost", 5, True),
        ("cost", 6, True),
        ("hybrid", 4, True),
        ("hybrid", 8, True),
        ("hybrid", 10, True),
    )
    best_solution = None
    best_score = float("inf")
    for metric, estimate_count, repair in configs:
        estimated_costs = _estimated_bundle_costs(data, estimate_count, metric)
        selected = _estimated_pair_partition_from_costs(data, estimated_costs)
        if repair:
            selected = _repair_estimated_pair_partition(selected, estimated_costs)
        selected = _allocate_bundle_couriers(selected, data)
        solution = _bundles_to_solution(selected)
        score = _evaluate_solution(solution, data)
        if score < best_score:
            best_score = score
            best_solution = solution
    return best_solution if best_solution is not None else []
def _scarce_randomized_pair_greedy(data):
    configs = (
        (0.02, 93),
        (0.02, 13),
        (0.01, 30),
        (0.02, 30),
        (0.03, 93),
        (0.01, 93),
        (0.05, 93),
        (0.04, 31),
        (0.05, 1),
    )
    best_solution = None
    best_score = float("inf")
    for alpha, seed in configs:
        solution = _scarce_pair_greedy_start(data, alpha, seed)
        score = _evaluate_solution(solution, data)
        if score < best_score:
            best_score = score
            best_solution = solution
    return best_solution if best_solution is not None else []
def _scarce_coverage_randomized(data):
    configs = (
        (0.05, 85, 0.0),
        (0.02, 17, 20.0),
        (0.05, 7, 80.0),
        (0.10, 31, 40.0),
        (0.10, 57, 80.0),
        (0.02, 23, 5.0),
        (0.01, 17, 60.0),
        (0.03, 43, 160.0),
    )
    best_solution = None
    best_score = float("inf")
    for alpha, seed, willingness_weight in configs:
        solution = _scarce_coverage_start(data, alpha, seed, willingness_weight)
        score = _evaluate_solution(solution, data)
        if score < best_score:
            best_score = score
            best_solution = solution
    return best_solution if best_solution is not None else []
def _scarce_coverage_start(data, alpha, seed, willingness_weight):
    rng = random.Random(seed)
    selected = {}
    covered = set()
    used_couriers = set()
    while len(covered) < len(data["task_ids"]) and len(used_couriers) < len(data["courier_ids"]):
        options = []
        best_key = None
        worst_key = None
        for task_key, entries in data["by_bundle"].items():
            if len(task_key) != 2:
                continue
            if any(task_id in covered for task_id in task_key):
                continue
            for entry in entries:
                if entry[1] in used_couriers:
                    continue
                benefit = 200.0 - _bundle_cost(2, [entry])
                key = benefit + willingness_weight * entry[2]
                options.append((key, task_key, entry))
                if best_key is None or key > best_key:
                    best_key = key
                if worst_key is None or key < worst_key:
                    worst_key = key
        if not options:
            break
        if alpha > 0.0 and best_key is not None and worst_key is not None:
            threshold = best_key - alpha * (best_key - worst_key)
            restricted = [item for item in options if item[0] >= threshold]
            _, task_key, entry = rng.choice(restricted)
        else:
            _, task_key, entry = max(options, key=lambda item: item[0])
        selected[task_key] = [entry]
        covered.update(task_key)
        used_couriers.add(entry[1])
    while len(covered) < len(data["task_ids"]) and len(used_couriers) < len(data["courier_ids"]):
        best = None
        for task_key, entries in data["by_bundle"].items():
            if len(task_key) != 1 or task_key[0] in covered:
                continue
            for entry in entries:
                if entry[1] in used_couriers:
                    continue
                benefit = 100.0 - _bundle_cost(1, [entry])
                if benefit > 1e-12 and (best is None or benefit > best[0]):
                    best = (benefit, task_key, entry)
        if best is None:
            break
        _, task_key, entry = best
        selected[task_key] = [entry]
        covered.update(task_key)
        used_couriers.add(entry[1])
    _repair_pair_partition(selected, data)
    _repair_pair_triples(selected, data)
    while len(used_couriers) < len(data["courier_ids"]):
        best = None
        for task_key, entries in selected.items():
            current = _bundle_cost(len(task_key), entries)
            local_couriers = {entry[1] for entry in entries}
            for entry in data["by_bundle"].get(task_key, []):
                if entry[1] in used_couriers or entry[1] in local_couriers:
                    continue
                benefit = current - _bundle_cost(len(task_key), entries + [entry])
                if benefit > 1e-12 and (best is None or benefit > best[0]):
                    best = (benefit, task_key, entry)
        if best is None:
            break
        _, task_key, entry = best
        selected[task_key].append(entry)
        used_couriers.add(entry[1])
    selected = _local_search_bundles(selected, data)
    return _bundles_to_solution(selected)
def _scarce_pair_greedy_start(data, alpha, seed):
    rng = random.Random(seed)
    selected = {}
    covered = set()
    used_couriers = set()
    while len(covered) < len(data["task_ids"]) and len(used_couriers) < len(data["courier_ids"]):
        options = []
        best_key = None
        worst_key = None
        for task_key, entries in data["by_bundle"].items():
            if len(task_key) != 2:
                continue
            if any(task_id in covered for task_id in task_key):
                continue
            for entry in entries:
                if entry[1] in used_couriers:
                    continue
                key = -_bundle_cost(2, [entry])
                if best_key is None or key > best_key:
                    best_key = key
                if worst_key is None or key < worst_key:
                    worst_key = key
                options.append((key, task_key, entry))
        if not options:
            break
        if alpha > 0.0 and best_key is not None and worst_key is not None:
            threshold = best_key - alpha * (best_key - worst_key)
            restricted = [item for item in options if item[0] >= threshold]
            key, task_key, entry = rng.choice(restricted)
        else:
            key, task_key, entry = max(options, key=lambda item: item[0])
        selected[task_key] = [entry]
        used_couriers.add(entry[1])
        covered.update(task_key)
    _repair_pair_partition(selected, data)
    _repair_pair_triples(selected, data)
    return _bundles_to_solution(selected)
def _random_estimated_pair_partition(data, estimated_costs, alpha, seed):
    rng = random.Random(seed)
    uncovered = set(data["task_ids"])
    selected = {}
    while len(uncovered) >= 2:
        options = []
        best_key = None
        worst_key = None
        tasks = sorted(uncovered)
        for i, task_a in enumerate(tasks):
            for task_b in tasks[i + 1 :]:
                task_key = tuple(sorted((task_a, task_b)))
                if task_key not in estimated_costs:
                    continue
                key = -estimated_costs[task_key]
                options.append((key, task_key))
                if best_key is None or key > best_key:
                    best_key = key
                if worst_key is None or key < worst_key:
                    worst_key = key
        if not options:
            break
        if alpha > 0.0 and best_key is not None and worst_key is not None:
            threshold = best_key - alpha * (best_key - worst_key)
            restricted = [item for item in options if item[0] >= threshold]
            _, task_key = rng.choice(restricted)
        else:
            _, task_key = max(options, key=lambda item: item[0])
        selected[task_key] = []
        uncovered.remove(task_key[0])
        uncovered.remove(task_key[1])
    for task_id in uncovered:
        selected[(task_id,)] = []
    return selected
def _estimated_bundle_costs(data, estimate_count, metric):
    estimated_costs = {}
    for task_key, entries in data["by_bundle"].items():
        if len(task_key) > 2:
            continue
        chosen = []
        for _ in range(estimate_count):
            current = _bundle_cost(len(task_key), chosen) if chosen else 100.0 * len(task_key)
            used = {entry[1] for entry in chosen}
            best = None
            for entry in entries:
                if entry[1] in used:
                    continue
                next_cost = _bundle_cost(len(task_key), chosen + [entry])
                benefit = current - next_cost
                if benefit > 1e-12 and (best is None or benefit > best[0]):
                    best = (benefit, entry)
            if best is None:
                break
            chosen.append(best[1])
        if chosen:
            estimated_cost = _bundle_cost(len(task_key), chosen)
            willingness_sum = sum(entry[2] for entry in chosen)
        else:
            estimated_cost = 100.0 * len(task_key)
            willingness_sum = 0.0
        if metric == "hybrid":
            estimated_cost -= 5.0 * willingness_sum
        estimated_costs[task_key] = estimated_cost
    return estimated_costs
def _estimated_bundle_costs_biased(data, estimate_count, willingness_bonus):
    estimated_costs = {}
    for task_key, entries in data["by_bundle"].items():
        if len(task_key) > 2:
            continue
        chosen = []
        for _ in range(estimate_count):
            current = _bundle_cost(len(task_key), chosen) if chosen else 100.0 * len(task_key)
            used = {entry[1] for entry in chosen}
            best = None
            for entry in entries:
                if entry[1] in used:
                    continue
                next_cost = _bundle_cost(len(task_key), chosen + [entry])
                benefit = current - next_cost
                if benefit > 1e-12 and (best is None or benefit > best[0]):
                    best = (benefit, entry)
            if best is None:
                break
            chosen.append(best[1])
        if chosen:
            estimated_cost = _bundle_cost(len(task_key), chosen)
            estimated_cost -= willingness_bonus * sum(entry[2] for entry in chosen)
        else:
            estimated_cost = 100.0 * len(task_key)
        estimated_costs[task_key] = estimated_cost
    return estimated_costs
def _low_willingness_pair_solution(data, deadline):
    configs = (
        ("det", 4, 0.0, False, 0.0, 0),
        ("det", 4, 30.0, True, 0.0, 0),
        ("rand", 6, 0.0, True, 0.20, 3),
        ("det", 6, 3.0, True, 0.0, 0),
        ("det", 3, 30.0, True, 0.0, 0),
        ("det", 5, 0.0, False, 0.0, 0),
        ("det", 4, 0.0, True, 0.0, 0),
        ("rand", 6, 0.0, True, 0.02, 29),
        ("det", 8, 1.0, True, 0.0, 0),
        ("det", 8, 45.0, True, 0.0, 0),
    )
    best_solution = None
    best_score = float("inf")
    for mode, estimate_count, willingness_bonus, repair, alpha, seed in configs:
        if time.perf_counter() >= deadline:
            break
        estimated_costs = _estimated_bundle_costs_biased(data, estimate_count, willingness_bonus)
        if mode == "rand":
            selected = _random_estimated_pair_partition(data, estimated_costs, alpha, seed)
        else:
            selected = _estimated_pair_partition_from_costs(data, estimated_costs)
        if repair:
            selected = _repair_estimated_pair_partition(selected, estimated_costs)
        selected = _allocate_bundle_couriers(selected, data)
        solution = _bundles_to_solution(selected)
        score = _evaluate_solution(solution, data)
        if score < best_score:
            best_score = score
            best_solution = solution
    return best_solution if best_solution is not None else []
def _bipartite_pair_partition_from_costs(data, estimated_costs, seed):
    tasks = data["task_ids"][:]
    if len(tasks) % 2:
        return None
    random.Random(seed).shuffle(tasks)
    left = tasks[: len(tasks) // 2]
    right = tasks[len(tasks) // 2 :]
    cost = []
    for task_a in left:
        row = []
        for task_b in right:
            row.append(estimated_costs.get(tuple(sorted((task_a, task_b))), 1e6))
        cost.append(row)
    assignment = _hungarian(cost)
    selected = {}
    for task_index, pair_index in enumerate(assignment):
        if pair_index < 0 or cost[task_index][pair_index] >= 1e5:
            return None
        pair_key = tuple(sorted((left[task_index], right[pair_index])))
        selected[pair_key] = []
    return selected
def _low_bipartite_pair_solution(data, deadline):
    configs = (
        (6, 0.0, 27),
        (6, 0.0, 53),
        (4, 0.0, 33),
        (4, 0.0, 16),
        (2, 15.0, 26),
        (6, 0.0, 7),
        (4, 0.0, 11),
        (6, 3.0, 29),
    )
    best_solution = None
    best_selected = None
    best_score = float("inf")
    for estimate_count, willingness_bonus, seed in configs:
        if time.perf_counter() >= deadline:
            break
        estimated_costs = _estimated_bundle_costs_biased(data, estimate_count, willingness_bonus)
        selected = _bipartite_pair_partition_from_costs(data, estimated_costs, seed)
        if selected is None:
            continue
        selected = _allocate_bundle_couriers(selected, data)
        solution = _bundles_to_solution(selected)
        score = _evaluate_solution(solution, data)
        if score < best_score:
            best_solution = solution
            best_selected = selected
            best_score = score
    if best_selected is not None and time.perf_counter() < deadline:
        selected, improved = _block_reoptimize_selected(
            best_selected,
            data,
            deadline,
            max_passes=6,
            top_limit=11,
        )
        if improved:
            solution = _bundles_to_solution(selected)
            score = _evaluate_solution(solution, data)
            if score < best_score:
                best_solution = solution
                best_selected = selected
                best_score = score
    if best_selected is not None and time.perf_counter() < deadline:
        selected, improved = _low_reallocate_pair_blocks(
            best_selected,
            data,
            deadline,
            max_passes=2,
            top_limit=4,
        )
        if improved:
            solution = _bundles_to_solution(selected)
            score = _evaluate_solution(solution, data)
            if score < best_score:
                best_solution = solution
    return best_solution if best_solution is not None else []
def _estimated_pair_partition(data, estimate_count, metric):
    return _estimated_pair_partition_from_costs(data, _estimated_bundle_costs(data, estimate_count, metric))
def _estimated_pair_partition_from_costs(data, estimated_costs):
    edge_scores = []
    for task_key, estimated_cost in estimated_costs.items():
        if len(task_key) != 2:
            continue
        edge_scores.append((estimated_cost, task_key))
    edge_scores.sort()
    selected = {}
    covered = set()
    for score_key, task_key in edge_scores:
        if any(task_id in covered for task_id in task_key):
            continue
        selected[task_key] = []
        covered.update(task_key)
        if len(covered) == len(data["task_ids"]):
            break
    for task_id in data["task_ids"]:
        if task_id not in covered:
            selected[(task_id,)] = []
    return selected
def _repair_estimated_pair_partition(selected, estimated_costs, max_passes=48):
    selected = {task_key: [] for task_key in selected}
    def estimated_cost(task_key):
        return estimated_costs.get(task_key, 100.0 * len(task_key) + 1e6)
    for _ in range(max_passes):
        best = None
        pair_keys = [task_key for task_key in selected if len(task_key) == 2]
        single_keys = [task_key for task_key in selected if len(task_key) == 1]
        for i, key_a in enumerate(pair_keys):
            for key_b in pair_keys[i + 1 :]:
                tasks = list(key_a + key_b)
                old_cost = estimated_cost(key_a) + estimated_cost(key_b)
                pairings = (
                    ((tasks[0], tasks[2]), (tasks[1], tasks[3])),
                    ((tasks[0], tasks[3]), (tasks[1], tasks[2])),
                )
                for next_a, next_b in pairings:
                    next_a = tuple(sorted(next_a))
                    next_b = tuple(sorted(next_b))
                    if next_a not in estimated_costs or next_b not in estimated_costs:
                        continue
                    delta = estimated_cost(next_a) + estimated_cost(next_b) - old_cost
                    if delta < -1e-10 and (best is None or delta < best[0]):
                        best = (delta, key_a, key_b, next_a, next_b)
        for single_key in single_keys:
            single_task = single_key[0]
            for pair_key in pair_keys:
                task_a, task_b = pair_key
                old_cost = estimated_cost(single_key) + estimated_cost(pair_key)
                for kept_task, next_single_task in ((task_a, task_b), (task_b, task_a)):
                    next_pair = tuple(sorted((single_task, kept_task)))
                    next_single = (next_single_task,)
                    if next_pair not in estimated_costs or next_single not in estimated_costs:
                        continue
                    delta = estimated_cost(next_pair) + estimated_cost(next_single) - old_cost
                    if delta < -1e-10 and (best is None or delta < best[0]):
                        best = (delta, single_key, pair_key, next_pair, next_single)
        if best is None:
            break
        _, old_a, old_b, next_a, next_b = best
        del selected[old_a]
        del selected[old_b]
        selected[next_a] = []
        selected[next_b] = []
    return selected
def _allocate_bundle_couriers(selected, data):
    selected = {task_key: entries[:] for task_key, entries in selected.items()}
    used_couriers = {
        entry[1]
        for entries in selected.values()
        for entry in entries
    }
    while True:
        empty_keys = [task_key for task_key, entries in selected.items() if not entries]
        if not empty_keys:
            break
        best = None
        for task_key in empty_keys:
            base_cost = 100.0 * len(task_key)
            for entry in data["by_bundle"].get(task_key, []):
                if entry[1] in used_couriers:
                    continue
                benefit = base_cost - _bundle_cost(len(task_key), [entry])
                if best is None or benefit > best[0]:
                    best = (benefit, task_key, entry)
        if best is None:
            break
        _, task_key, entry = best
        selected[task_key].append(entry)
        used_couriers.add(entry[1])
    while len(used_couriers) < len(data["courier_ids"]):
        best = None
        for task_key, entries in selected.items():
            if not entries:
                continue
            current = _bundle_cost(len(task_key), entries)
            local_couriers = {entry[1] for entry in entries}
            for entry in data["by_bundle"].get(task_key, []):
                if entry[1] in used_couriers or entry[1] in local_couriers:
                    continue
                benefit = current - _bundle_cost(len(task_key), entries + [entry])
                if benefit > 1e-12 and (best is None or benefit > best[0]):
                    best = (benefit, task_key, entry)
        if best is None:
            break
        _, task_key, entry = best
        selected[task_key].append(entry)
        used_couriers.add(entry[1])
    return _local_search_bundles(selected, data)
def _bundles_to_solution(selected):
    result = []
    for task_key in sorted(selected):
        entries = sorted(selected[task_key])
        if entries:
            result.append((entries[0][3], [entry[1] for entry in entries]))
    return result
def _solution_to_selected(solution, data):
    selected = {}
    for task_str, couriers in solution:
        task_key = _task_key(task_str)
        entries = []
        for courier_id in couriers:
            entry = data["candidate_map"].get((task_key, courier_id))
            if entry is None:
                return None
            entries.append(entry)
        selected[task_key] = entries
    return selected
def _selected_cost(selected, data):
    total = 0.0
    covered = set()
    for task_key, entries in selected.items():
        if not entries or any(task_id in covered for task_id in task_key):
            return float("inf")
        total += _bundle_cost(len(task_key), entries)
        covered.update(task_key)
    total += 100.0 * (len(data["task_ids"]) - len(covered))
    return total
def _add_released_couriers(selected, data, released_couriers):
    selected = {task_key: entries[:] for task_key, entries in selected.items()}
    available = []
    seen = set()
    used = {entry[1] for entries in selected.values() for entry in entries}
    for courier_id in released_couriers:
        if courier_id not in used and courier_id not in seen:
            available.append(courier_id)
            seen.add(courier_id)
    while available:
        best = None
        for courier_id in available:
            for task_key, entries in selected.items():
                if any(entry[1] == courier_id for entry in entries):
                    continue
                entry = data["candidate_map"].get((task_key, courier_id))
                if entry is None:
                    continue
                old_cost = _bundle_cost(len(task_key), entries)
                new_cost = _bundle_cost(len(task_key), entries + [entry])
                benefit = old_cost - new_cost
                if benefit > 1e-12 and (best is None or benefit > best[0]):
                    best = (benefit, courier_id, task_key, entry)
        if best is None:
            break
        _, courier_id, task_key, entry = best
        selected[task_key].append(entry)
        available.remove(courier_id)
    return selected
def _repartition_candidate(selected, data, old_keys, new_keys, current_score):
    if len(new_keys) != 2 or new_keys[0] == new_keys[1]:
        return None
    if any(task_id in new_keys[0] for task_id in new_keys[1]):
        return None
    old_key_set = set(old_keys)
    involved = []
    seen = set()
    for task_key in old_keys:
        for entry in selected[task_key]:
            if entry[1] not in seen:
                involved.append(entry)
                seen.add(entry[1])
    if len(involved) < 2 or len(involved) > 8:
        return None
    base = {
        task_key: entries[:]
        for task_key, entries in selected.items()
        if task_key not in old_key_set
    }
    full_mask = (1 << len(involved)) - 1
    best = None
    def entries_for_mask(task_key, mask):
        entries = []
        for index, entry in enumerate(involved):
            if not (mask & (1 << index)):
                continue
            next_entry = data["candidate_map"].get((task_key, entry[1]))
            if next_entry is None:
                return None
            entries.append(next_entry)
        return entries
    for mask_a in range(1, full_mask + 1):
        entries_a = entries_for_mask(new_keys[0], mask_a)
        if entries_a is None:
            continue
        remaining = full_mask ^ mask_a
        sub = remaining
        while sub:
            mask_b = sub
            entries_b = entries_for_mask(new_keys[1], mask_b)
            if entries_b is not None:
                selected_next = {task_key: entries[:] for task_key, entries in base.items()}
                selected_next[new_keys[0]] = entries_a[:]
                selected_next[new_keys[1]] = entries_b[:]
                used_mask = mask_a | mask_b
                released = [
                    entry[1]
                    for index, entry in enumerate(involved)
                    if not (used_mask & (1 << index))
                ]
                if released:
                    selected_next = _add_released_couriers(selected_next, data, released)
                new_score = _selected_cost(selected_next, data)
                delta = new_score - current_score
                if delta < -1e-10 and (best is None or delta < best[0]):
                    best = (delta, selected_next)
            sub = (sub - 1) & remaining
    return best
def _single_pair_partitions(tasks):
    if not tasks:
        return [()]
    first = tasks[0]
    partitions = []
    for tail in _single_pair_partitions(tasks[1:]):
        partitions.append(((first,),) + tail)
    for index in range(1, len(tasks)):
        second = tasks[index]
        rest = tasks[1:index] + tasks[index + 1 :]
        for tail in _single_pair_partitions(rest):
            partitions.append((tuple(sorted((first, second))),) + tail)
    return partitions
def _block_repartition_candidate(selected, data, old_keys, current_score, deadline):
    old_key_set = set(old_keys)
    tasks = tuple(sorted(task_id for task_key in old_keys for task_id in task_key))
    if len(tasks) < 3 or len(tasks) > 6:
        return None
    couriers = []
    seen = set()
    for task_key in old_keys:
        for entry in selected[task_key]:
            if entry[1] not in seen:
                couriers.append(entry[1])
                seen.add(entry[1])
    if len(couriers) < 2 or len(couriers) > 8:
        return None
    base = {
        task_key: entries[:]
        for task_key, entries in selected.items()
        if task_key not in old_key_set
    }
    full_mask = (1 << len(couriers)) - 1
    best = None
    for next_keys in _single_pair_partitions(tasks):
        if time.perf_counter() >= deadline:
            break
        if len(next_keys) > len(couriers):
            continue
        option_sets = []
        possible = True
        for task_key in next_keys:
            entry_by_index = [
                data["candidate_map"].get((task_key, courier_id))
                for courier_id in couriers
            ]
            options = []
            for mask in range(1, full_mask + 1):
                entries = []
                for index, entry in enumerate(entry_by_index):
                    if not (mask & (1 << index)):
                        continue
                    if entry is None:
                        entries = None
                        break
                    entries.append(entry)
                if entries is not None:
                    options.append((mask, _bundle_cost(len(task_key), entries), entries))
            if not options:
                possible = False
                break
            option_sets.append((task_key, options))
        if not possible:
            continue
        states = {0: (0.0, [])}
        for task_key, options in option_sets:
            next_states = {}
            for used_mask, (state_cost, chosen) in states.items():
                for mask, bundle_cost, entries in options:
                    if used_mask & mask:
                        continue
                    next_mask = used_mask | mask
                    next_cost = state_cost + bundle_cost
                    previous = next_states.get(next_mask)
                    if previous is None or next_cost < previous[0]:
                        next_states[next_mask] = (next_cost, chosen + [(task_key, entries)])
            states = next_states
            if not states:
                break
        if not states:
            continue
        for used_mask, (_, chosen) in sorted(states.items(), key=lambda item: item[1][0])[:2]:
            selected_next = {task_key: entries[:] for task_key, entries in base.items()}
            for task_key, entries in chosen:
                selected_next[task_key] = entries[:]
            released = [
                courier_id
                for index, courier_id in enumerate(couriers)
                if not (used_mask & (1 << index))
            ]
            if released:
                selected_next = _add_released_couriers(selected_next, data, released)
            next_score = _selected_cost(selected_next, data)
            delta = next_score - current_score
            if delta < -1e-10 and (best is None or delta < best[0]):
                best = (delta, next_score, selected_next)
    return best
def _block_reoptimize_selected(selected, data, deadline, max_passes=4, top_limit=7):
    selected = {task_key: entries[:] for task_key, entries in selected.items()}
    current_score = _selected_cost(selected, data)
    improved = False
    for _ in range(max_passes):
        if time.perf_counter() >= deadline:
            break
        ranked_keys = sorted(
            selected,
            key=lambda task_key: _bundle_cost(len(task_key), selected[task_key]),
            reverse=True,
        )[: min(top_limit, len(selected))]
        best = None
        for old_keys in itertools.combinations(ranked_keys, 3):
            if time.perf_counter() >= deadline:
                break
            candidate = _block_repartition_candidate(selected, data, old_keys, current_score, deadline)
            if candidate is not None and (best is None or candidate[0] < best[0]):
                best = candidate
        if best is None:
            break
        _, current_score, selected = best
        refined = _local_search_bundles(selected, data, max_passes=2, deadline=deadline)
        refined_score = _selected_cost(refined, data)
        if refined_score < current_score - 1e-10:
            selected = refined
            current_score = refined_score
        improved = True
    return selected, improved
def _block_reoptimize_solution(solution, data, deadline, max_passes=4, top_limit=7):
    selected = _solution_to_selected(solution, data)
    if selected is None:
        return solution
    selected, improved = _block_reoptimize_selected(
        selected,
        data,
        deadline,
        max_passes=max_passes,
        top_limit=top_limit,
    )
    return _bundles_to_solution(selected) if improved else solution
def _low_reallocate_pair_blocks(selected, data, deadline, max_passes=2, top_limit=4):
    selected = {task_key: entries[:] for task_key, entries in selected.items()}
    current_score = _selected_cost(selected, data)
    improved = False
    for _ in range(max_passes):
        if time.perf_counter() >= deadline:
            break
        ranked_keys = sorted(
            selected,
            key=lambda task_key: _bundle_cost(len(task_key), selected[task_key]),
            reverse=True,
        )[: min(top_limit, len(selected))]
        best = None
        for old_keys in itertools.combinations(ranked_keys, 2):
            if time.perf_counter() >= deadline:
                break
            tasks = tuple(sorted(task_id for task_key in old_keys for task_id in task_key))
            old_key_set = set(old_keys)
            for next_keys in _single_pair_partitions(tasks):
                if time.perf_counter() >= deadline:
                    break
                if any(task_key not in data["by_bundle"] for task_key in next_keys):
                    continue
                partition = {
                    task_key: []
                    for task_key in selected
                    if task_key not in old_key_set
                }
                for task_key in next_keys:
                    partition[task_key] = []
                candidate = _allocate_bundle_couriers(partition, data)
                score = _selected_cost(candidate, data)
                if score < current_score - 1e-10 and (best is None or score < best[0]):
                    best = (score, candidate)
        if best is None:
            break
        current_score, selected = best
        improved = True
    return selected, improved
def _mixed_partition_exchange(selected, data, deadline):
    current_score = _selected_cost(selected, data)
    improved = False
    for _ in range(12):
        if deadline is not None and time.perf_counter() >= deadline:
            break
        singles = [task_key for task_key in selected if len(task_key) == 1]
        pairs = [task_key for task_key in selected if len(task_key) == 2]
        best = None
        for single_key in singles:
            if deadline is not None and time.perf_counter() >= deadline:
                break
            single_task = single_key[0]
            for pair_key in pairs:
                task_a, task_b = pair_key
                for kept_task, next_single_task in ((task_a, task_b), (task_b, task_a)):
                    next_pair = tuple(sorted((single_task, kept_task)))
                    next_single = (next_single_task,)
                    candidate = _repartition_candidate(
                        selected,
                        data,
                        (single_key, pair_key),
                        (next_pair, next_single),
                        current_score,
                    )
                    if candidate is not None and (best is None or candidate[0] < best[0]):
                        best = candidate
        for index, pair_a in enumerate(pairs):
            if deadline is not None and time.perf_counter() >= deadline:
                break
            for pair_b in pairs[index + 1 :]:
                tasks = list(pair_a + pair_b)
                for next_a, next_b in (
                    (tuple(sorted((tasks[0], tasks[2]))), tuple(sorted((tasks[1], tasks[3])))),
                    (tuple(sorted((tasks[0], tasks[3]))), tuple(sorted((tasks[1], tasks[2])))),
                ):
                    candidate = _repartition_candidate(
                        selected,
                        data,
                        (pair_a, pair_b),
                        (next_a, next_b),
                        current_score,
                    )
                    if candidate is not None and (best is None or candidate[0] < best[0]):
                        best = candidate
        if best is None:
            break
        delta, selected = best
        current_score += delta
        refined = _local_search_bundles(selected, data, max_passes=3, deadline=deadline)
        refined_score = _selected_cost(refined, data)
        if refined_score < current_score - 1e-10:
            selected = refined
            current_score = refined_score
        improved = True
    return selected, improved
def _mixed_single_pair_merge(solution, data, deadline=None):
    selected = _solution_to_selected(solution, data)
    if selected is None:
        return solution
    improved = False
    current_score = _selected_cost(selected, data)
    while True:
        if deadline is not None and time.perf_counter() >= deadline:
            break
        singles = [task_key for task_key in selected if len(task_key) == 1]
        best = None
        for index, task_a in enumerate(singles):
            if deadline is not None and time.perf_counter() >= deadline:
                break
            entries_a = selected[task_a]
            for task_b in singles[index + 1 :]:
                pair_key = tuple(sorted((task_a[0], task_b[0])))
                pair_entries = []
                missing_pair_couriers = []
                for entry in entries_a + selected[task_b]:
                    pair_entry = data["candidate_map"].get((pair_key, entry[1]))
                    if pair_entry is None:
                        missing_pair_couriers.append(entry[1])
                    else:
                        pair_entries.append(pair_entry)
                if not pair_entries:
                    continue
                entry_options = [pair_entries]
                if len(pair_entries) <= 10:
                    entry_options = []
                    for mask in range(1, 1 << len(pair_entries)):
                        entry_options.append(
                            [
                                entry
                                for entry_index, entry in enumerate(pair_entries)
                                if mask & (1 << entry_index)
                            ]
                        )
                for next_entries in entry_options:
                    selected_next = {
                        task_key: entries[:]
                        for task_key, entries in selected.items()
                        if task_key != task_a and task_key != task_b
                    }
                    selected_next[pair_key] = next_entries[:]
                    next_couriers = {entry[1] for entry in next_entries}
                    released = [
                        entry[1]
                        for entry in entries_a + selected[task_b]
                        if entry[1] not in next_couriers
                    ] + missing_pair_couriers
                    if released:
                        selected_next = _add_released_couriers(selected_next, data, released)
                    new_score = _selected_cost(selected_next, data)
                    delta = new_score - current_score
                    if delta < -1e-10 and (best is None or delta < best[0]):
                        best = (delta, selected_next)
        if best is None:
            break
        delta, selected = best
        current_score += delta
        improved = True
    if improved:
        refined = _local_search_bundles(selected, data, max_passes=6, deadline=deadline)
        refined_score = _selected_cost(refined, data)
        if refined_score < current_score - 1e-10:
            selected = refined
            current_score = refined_score
    if deadline is None or time.perf_counter() < deadline:
        selected, exchange_improved = _mixed_partition_exchange(selected, data, deadline)
        improved = improved or exchange_improved
    return _bundles_to_solution(selected) if improved else solution
def _hungarian(cost):
    n = len(cost)
    if n == 0:
        return []
    m = len(cost[0])
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    assignment = [-1] * n
    for j in range(1, m + 1):
        if p[j] > 0:
            assignment[p[j] - 1] = j - 1
    return assignment
def _ilp_linearized_single(data, secondary_weight=0.30):
    return _ilp_linearized_single_weights(data, [1.0, secondary_weight])
def _ilp_linearized_single_weights(data, slot_weights):
    tasks = [task_id for task_id in data["task_ids"] if task_id in data["single_by_task"]]
    couriers = data["courier_ids"]
    slots = []
    for task_id in tasks:
        for weight in slot_weights:
            slots.append((task_id, weight))
    while len(slots) < len(couriers):
        slots.append((None, 0.0))
    cost = []
    for courier_id in couriers:
        row = []
        for task_id, weight in slots:
            if task_id is None:
                row.append(0.0)
                continue
            entry = data["entry_by_task_courier"].get((task_id, courier_id))
            if entry is None:
                row.append(1e6)
                continue
            score, _, willingness, _ = entry
            row.append(-willingness * (100.0 - score) * weight)
        cost.append(row)
    assignment = _hungarian(cost)
    assignments = {task_id: [] for task_id in tasks}
    for courier_index, slot_index in enumerate(assignment):
        if slot_index < 0:
            continue
        task_id, _ = slots[slot_index]
        if task_id is None:
            continue
        courier_id = couriers[courier_index]
        entry = data["entry_by_task_courier"].get((task_id, courier_id))
        if entry is not None:
            assignments[task_id].append(entry)
    assignments = _local_search_single(assignments, data)
    return _assignments_to_solution(assignments)
def solve(input_text: str) -> list:
    data = _parse(input_text)
    deadline = time.perf_counter() + 9.5
    low_pair_searched = False
    if DIAG_MODE == "pair_only":
        return _pair_greedy(data)
    if DIAG_MODE == "estimated_pair_only":
        return _estimated_pair_solution(data)
    if DIAG_MODE == "scarce_only":
        return _scarce_randomized_pair_greedy(data)
    if DIAG_MODE == "ilp_only":
        return _ilp_linearized_single(data)
    if DIAG_MODE == "single_only":
        return _single_multistart(data, deadline)
    if DIAG_MODE == "single_cycle_only":
        solution = _single_multistart(data, deadline)
        assignments = _solution_to_single_assignments(solution, data)
        if assignments is not None and time.perf_counter() < deadline:
            assignments = _local_search_single_cycles(assignments, data, deadline)
            return _assignments_to_solution(assignments)
        return solution
    candidates = []
    baseline = _official_baseline(data)
    candidates.append((_evaluate_solution(baseline, data), baseline))
    for mode in ("expected", "willingness", "balanced", "larger_first"):
        weighted_baseline = _weighted_greedy_baseline(data, mode)
        candidates.append((_evaluate_solution(weighted_baseline, data), weighted_baseline))
    pair_solution = _pair_greedy(data)
    candidates.append((_evaluate_solution(pair_solution, data), pair_solution))
    coverage_solution = _coverage_first_greedy(data)
    candidates.append((_evaluate_solution(coverage_solution, data), coverage_solution))
    if len(data["courier_ids"]) * 2 <= len(data["task_ids"]):
        scarce_solution = _scarce_randomized_pair_greedy(data)
        candidates.append((_evaluate_solution(scarce_solution, data), scarce_solution))
    if len(data["courier_ids"]) <= len(data["task_ids"]):
        scarce_coverage_solution = _scarce_coverage_randomized(data)
        candidates.append((_evaluate_solution(scarce_coverage_solution, data), scarce_coverage_solution))
    ilp_solution = _ilp_linearized_single(data)
    candidates.append((_evaluate_solution(ilp_solution, data), ilp_solution))
    if len(data["courier_ids"]) >= len(data["task_ids"]) * 2:
        ilp_wide_solution = _ilp_linearized_single_weights(data, [1.0, 0.7])
        candidates.append((_evaluate_solution(ilp_wide_solution, data), ilp_wide_solution))
    cheap_best_score = min(score for score, _ in candidates)
    low_pair_pressure = (
        20 <= len(data["task_ids"]) <= 30
        and data["avg_willingness"] < 0.32
        and cheap_best_score > 1200.0
        and time.perf_counter() < deadline
    )
    if low_pair_pressure:
        low_bipartite_solution = _low_bipartite_pair_solution(data, deadline)
        candidates.append((_evaluate_solution(low_bipartite_solution, data), low_bipartite_solution))
        if time.perf_counter() < deadline:
            low_pair_solution = _low_willingness_pair_solution(data, deadline)
            candidates.append((_evaluate_solution(low_pair_solution, data), low_pair_solution))
        low_pair_searched = True
    single_solution = _single_multistart(data, deadline)
    candidates.append((_evaluate_solution(single_solution, data), single_solution))
    if (
        len(data["task_ids"]) >= 40
        and len(data["courier_ids"]) <= len(data["task_ids"]) * 2.1
        and data["avg_willingness"] >= 0.18
        and time.perf_counter() < deadline
    ):
        large_mixed_solution = _mixed_single_pair_merge(single_solution, data, deadline)
        candidates.append((_evaluate_solution(large_mixed_solution, data), large_mixed_solution))
    if len(data["courier_ids"]) <= len(data["task_ids"]) * 1.25:
        for score, solution in list(candidates):
            merged_solution = _mixed_single_pair_merge(solution, data, deadline)
            merged_score = _evaluate_solution(merged_solution, data)
            if merged_score < score - 1e-10:
                candidates.append((merged_score, merged_solution))
    best_candidate_score = min(score for score, _ in candidates)
    if (
        not low_pair_searched
        and
        data["avg_willingness"] < 0.18
        and best_candidate_score > 1200.0
        and time.perf_counter() < deadline
    ):
        low_bipartite_solution = _low_bipartite_pair_solution(data, deadline)
        candidates.append((_evaluate_solution(low_bipartite_solution, data), low_bipartite_solution))
    if not low_pair_searched and data["avg_willingness"] < 0.18 and time.perf_counter() < deadline:
        low_pair_solution = _low_willingness_pair_solution(data, deadline)
        candidates.append((_evaluate_solution(low_pair_solution, data), low_pair_solution))
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]
