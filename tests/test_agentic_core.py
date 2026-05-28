"""Tests for the modular online/offline AutoSolver loops."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analyzer.feature_extractor import extract_case_profile
from evaluator.judge_local import evaluate_solution
import final_submit
from solver.parser import parse_problem
from solver.strategies.expected_cost_greedy import solve as expected_greedy


CASE = """task_id_list\tcourier_id\ttotal_score\twillingness
T1\tC1\t20\t0.90
T2\tC2\t25\t0.80
T1,T2\tC3\t30\t0.70
T2\tC4\t80\t0.20
"""


class AgenticCoreTest(unittest.TestCase):
    def test_parser_profile_and_evaluator(self):
        problem = parse_problem(CASE)
        profile = extract_case_profile(problem)
        evaluation = evaluate_solution(expected_greedy(problem), problem)
        self.assertEqual(profile["num_tasks"], 2)
        self.assertEqual(profile["num_candidates"], 4)
        self.assertIn("case_label_rules", profile)
        self.assertTrue(any(rule["label"] == "scarce_couriers" for rule in profile["case_label_rules"]))
        self.assertIn("expected_cost_distribution", profile)
        self.assertTrue(evaluation.valid)
        self.assertEqual(evaluation.covered_tasks, 2)
        self.assertIn("rejection_risk_cost", evaluation.score_decomposition)

    def test_final_submit_falls_back_when_champion_errors(self):
        champion = final_submit._validated_champion
        try:
            def fail(_input_text):
                raise RuntimeError("forced failure")

            final_submit._validated_champion = fail
            evaluation = evaluate_solution(final_submit.solve(CASE), parse_problem(CASE))
        finally:
            final_submit._validated_champion = champion
        self.assertTrue(evaluation.valid)
        self.assertEqual(evaluation.covered_tasks, 2)

    def test_online_log_then_offline_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = (
                "import json, sys; "
                "from agent.online_agent import OnlineAgent; "
                "p=json.load(sys.stdin); "
                "a=OnlineAgent(p['logs'], p['outputs'], p['memory']); "
                "r=a.solve(p['text'], 0.2, persist=True); "
                "print(json.dumps({'score': r['final_evaluation']['score'], 'strategy': r['selected_strategy']}))"
            )
            env = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(ROOT)}
            online = subprocess.run(
                [sys.executable, "-c", script],
                input=json.dumps(
                    {
                        "text": CASE,
                        "logs": str(root / "logs"),
                        "outputs": str(root / "outputs"),
                        "memory": str(root / "rule_memory.json"),
                    }
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(ROOT),
                env=env,
                check=True,
            )
            self.assertIn("score", json.loads(online.stdout))
            offline = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "agent.offline_agent",
                    "--logs",
                    str(root / "logs"),
                    "--reports",
                    str(root / "reports"),
                    "--memory",
                    str(root / "rule_memory.json"),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(ROOT),
                env=env,
                check=True,
            )
            offline_payload = json.loads(offline.stdout)
            self.assertEqual(offline_payload["runs"], 1)
            self.assertIn("learned_code", offline_payload)
            self.assertTrue((root / "reports" / "failure_analysis_report.md").exists())
            memory = json.loads((root / "rule_memory.json").read_text())
            self.assertEqual(memory["evidence_runs"], 1)
            case_memory = next(iter(memory["case_types"].values()))
            self.assertIn("offline_agent", case_memory)
            self.assertIn("ablation_result", case_memory["offline_agent"])
            for generated in case_memory["strategy_modules"].values():
                self.assertTrue(Path(generated["module_path"]).exists())
            self.assertIn("valuable_features", case_memory)

            from agent.strategy_planner import plan_strategies

            profile = extract_case_profile(parse_problem(CASE))
            learned_plan = plan_strategies(profile, 0.2, root / "rule_memory.json")
            self.assertIn("strategies", learned_plan)

    def test_online_returns_diagnostics_and_selected_algorithm_code(self):
        from agent.online_agent import OnlineAgent

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = OnlineAgent(root / "logs", root / "outputs", root / "rule_memory.json").solve(
                CASE,
                0.2,
                persist=True,
            )
            self.assertIn("data_analysis", result)
            self.assertIn("charts", result["data_analysis"])
            self.assertIn("online_agent", result)
            self.assertIn("score_diagnostics", result)
            self.assertIn("generated_strategies", result)
            self.assertIn("def solve", result["final_submit"]["code"])
            self.assertTrue((root / "outputs" / "latest_final_submit.py").exists())

    def test_llm_config_is_redacted_in_demo_payload(self):
        from backend.app import build_offline_demo

        result = build_offline_demo(
            0.2,
            301,
            {
                "api_key": "secret-key-should-not-leak",
                "model": "deepseek-v4-flash",
                "base_url": "http://127.0.0.1:9/chat/completions",
            },
        )
        dumped = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("secret-key-should-not-leak", dumped)
        self.assertEqual(result["llm_config"]["model"], "deepseek-v4-flash")
        self.assertTrue(result["llm_config"]["configured"])
        self.assertEqual(result["online"]["online_agent"]["topk_decision"]["used_llm"], True)
        self.assertIn(result["online"]["online_agent"]["topk_decision"]["status"], {"ok", "error"})

    def test_online_and_offline_demo_are_separate_stages(self):
        from backend.app import build_offline_demo, build_online_demo

        online = build_online_demo(0.2, 301, {})
        self.assertIsNone(online["offline"])
        self.assertIsNone(online["offline_config"])
        self.assertTrue(online["demo_state"]["state_root"])
        self.assertEqual(online["steps"][-1]["id"], "iterate")

        offline = build_offline_demo(
            0.2,
            301,
            {},
            {"max_iterations": 2, "patience": 1, "min_improvement": 0.002},
            {"demo_state": online["demo_state"]},
        )
        self.assertIsNotNone(offline["offline"])
        self.assertEqual(offline["offline_config"]["max_iterations"], 2)
        self.assertEqual(offline["offline_config"]["patience"], 1)
        self.assertEqual(offline["offline_config"]["min_improvement"], 0.002)
        self.assertEqual(offline["steps"][-1]["id"], "memory")
        self.assertEqual(offline["evidence_source"], "existing_demo_log")

        independent = build_offline_demo(
            0.2,
            301,
            {},
            {"max_iterations": 1, "patience": 1, "min_improvement": 0.001},
            {},
            CASE,
            "tiny_upload.txt",
            "uploaded",
        )
        self.assertEqual(independent["evidence_source"], "offline_bootstrap")
        self.assertEqual(independent["dataset_info"]["source"], "uploaded")

    def test_demo_accepts_uploaded_dataset_text(self):
        from backend.app import build_online_demo

        result = build_online_demo(
            0.2,
            301,
            {},
            input_text=CASE,
            dataset_name="tiny_upload.txt",
            dataset_source="uploaded",
        )
        self.assertEqual(result["dataset"], "tiny_upload.txt")
        self.assertEqual(result["dataset_info"]["source"], "uploaded")
        self.assertEqual(result["online"]["case_profile"]["num_tasks"], 2)
        self.assertLess(result["online"]["case_profile"]["num_candidates"], 10)

    def test_llm_test_requires_api_key(self):
        from backend.app import test_llm_connection

        with self.assertRaises(ValueError):
            test_llm_connection({"api_key": "", "model": "deepseek-v4-flash"})

    def test_llm_socket_timeout_returns_structured_error(self):
        from unittest import mock
        import socket

        from agent.llm_client import LLMClient

        client = LLMClient({"api_key": "x", "model": "deepseek-v4-flash", "base_url": "api.deepseek.com"})
        with mock.patch("urllib.request.urlopen", side_effect=socket.timeout("read timed out")):
            result = client.ask_json("system", "user", {"fallback": True}, timeout=1.0)
        self.assertTrue(result["used_llm"])
        self.assertEqual(result["status"], "error")
        self.assertIn("timeout", result["error"].lower())
        self.assertEqual(result["decision"], {"fallback": True})

    def test_llm_base_url_normalization(self):
        from agent.llm_client import LLMClient, normalize_chat_url

        self.assertEqual(
            normalize_chat_url("api.deepseek.com"),
            "https://api.deepseek.com/chat/completions",
        )
        self.assertEqual(
            normalize_chat_url("https://api.deepseek.com/chat/completions"),
            "https://api.deepseek.com/chat/completions",
        )
        client = LLMClient({"api_key": "x", "base_url": "api.deepseek.com", "model": "deepseek-v4-flash"})
        self.assertEqual(client.url, "https://api.deepseek.com/chat/completions")


if __name__ == "__main__":
    unittest.main()
