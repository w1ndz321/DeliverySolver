"""Tests for the self-contained submission package."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from backend.scenarios import SCENARIOS, analyze_input, scenario_text
from backend.app import compact_online_result


class SubmissionFlowTest(unittest.TestCase):
    def test_scenarios_are_generated_from_public_input(self):
        features = analyze_input(scenario_text("low-willingness"))
        self.assertEqual(features["tasks"], 30)
        self.assertEqual(features["couriers"], 60)
        self.assertIn("LOW WILLINGNESS", features["tags"])
        self.assertEqual(set(SCENARIOS), {"low-willingness", "scarce-couriers", "constrained-medium"})

    def test_online_result_can_be_compacted_for_backend_api(self):
        from agent.online_agent import OnlineAgent

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = OnlineAgent(root / "logs", root / "outputs", root / "rule_memory.json")
            result = agent.solve(scenario_text("constrained-medium"), 0.2, persist=False)
        compact = compact_online_result(result)
        self.assertEqual(compact["status"], "ok")
        self.assertEqual(compact["covered"], compact["tasks"])
        self.assertIn("def solve", compact["algorithm_code"])


if __name__ == "__main__":
    unittest.main()
