import unittest
import json
import tempfile
from pathlib import Path

from benchsuite.adapters.taubench import TauBenchAdapter
from benchsuite.config import Config


class TauBenchAdapterTests(unittest.TestCase):
    def _cfg(self):
        return Config(
            base_url="http://wimpy.home.lan:8080/v1",
            api_key="",
            model="qwen3-8-27b-ud-iq2-m",
            timeout_s=2400,
            results_dir=Path("results"),
            env={},
            benchmarks={},
        )

    def test_builds_official_tau2_banking_command(self):
        adapter = TauBenchAdapter(
            self._cfg(),
            {
                "repo": "tau2-bench",
                "env": "banking_knowledge",
                "agent_strategy": "llm_agent",
                "user_strategy": "user_simulator",
                "max_concurrency": 1,
            },
            Path("results"),
        )
        cmd = adapter.build_command("qwen3-8-27b-ud-iq2-m", "qwen3-8-27b-ud-iq2-m")
        self.assertIn("--domain", cmd)
        self.assertEqual(cmd[cmd.index("--domain") + 1], "banking_knowledge")
        self.assertIn("--retrieval-config", cmd)
        self.assertEqual(cmd[cmd.index("--retrieval-config") + 1], "golden_retrieval")
        self.assertIn("--agent", cmd)
        self.assertEqual(cmd[cmd.index("--agent") + 1], "llm_agent")
        self.assertIn("--user", cmd)
        self.assertEqual(cmd[cmd.index("--user") + 1], "user_simulator")
        self.assertIn("--max-concurrency", cmd)
        self.assertEqual(cmd[cmd.index("--max-concurrency") + 1], "1")
        self.assertIn("--max-retries", cmd)
        self.assertEqual(cmd[cmd.index("--max-retries") + 1], "0")
        self.assertNotIn("--task-ids", cmd)

    def test_uses_configured_retrieval_mode_when_overridden(self):
        adapter = TauBenchAdapter(
            self._cfg(),
            {
                "repo": "tau2-bench",
                "env": "banking_knowledge",
                "retrieval_config": "no_knowledge",
            },
            Path("results"),
        )
        cmd = adapter.build_command("model", "model")
        self.assertEqual(cmd[cmd.index("--retrieval-config") + 1], "no_knowledge")

    def test_parse_accepts_completed_official_simulation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "tau2-bench"
            target = repo / "data" / "simulations" / "run-1"
            target.mkdir(parents=True)
            (target / "results.json").write_text(json.dumps({
                "simulations": [
                    {"termination_reason": "user_stop", "reward_info": {"reward": 1.0}, "info": None}
                ]
            }))
            adapter = TauBenchAdapter(self._cfg(), {"repo": str(repo)}, root / "results")
            adapter.project_root = root
            adapter._active_save_to = "run-1"
            result = adapter.parse(root / "results", "")
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.metric_name, "average_reward")
            self.assertEqual(result.metric_value, 1.0)

    def test_parse_rejects_official_infrastructure_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "tau2-bench"
            target = repo / "data" / "simulations" / "run-1"
            target.mkdir(parents=True)
            (target / "results.json").write_text(json.dumps({
                "simulations": [
                    {
                        "termination_reason": "infrastructure_error",
                        "reward_info": None,
                        "info": {"error": "context exceeded"},
                    }
                ]
            }))
            adapter = TauBenchAdapter(self._cfg(), {"repo": str(repo)}, root / "results")
            adapter.project_root = root
            adapter._active_save_to = "run-1"
            result = adapter.parse(root / "results", "")
            self.assertEqual(result.status, "failed")
            self.assertIn("infrastructure", result.error or "")

    def test_absolute_checkout_path_is_not_prefixed_with_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "tau2-bench"
            (repo / ".venv-tau2" / "bin").mkdir(parents=True)
            executable = repo / ".venv-tau2" / "bin" / "tau2"
            executable.write_text("#!/bin/sh\n")
            adapter = TauBenchAdapter(
                self._cfg(),
                {"repo": str(repo), "env": "banking_knowledge"},
                Path(tmp) / "results",
            )
            adapter.project_root = Path("/unrelated/project")
            cmd = adapter.build_command("model", "model")
            self.assertEqual(cmd[0], str(executable))
            self.assertEqual(adapter.run_cwd, repo)


if __name__ == "__main__":
    unittest.main()
