import unittest
from pathlib import Path

from benchsuite.adapters.livecodebench import LiveCodeBenchAdapter
from benchsuite.adapters.terminalbench import TerminalBenchAdapter
from benchsuite.config import Config


class AdapterCommandContractTests(unittest.TestCase):
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

    def test_livecodebench_uses_supported_custom_output_flag(self):
        adapter = LiveCodeBenchAdapter(
            self._cfg(),
            {"repo": "LiveCodeBench", "release": "release_v2", "scenario": "codegeneration"},
            Path("results"),
        )
        cmd = adapter.build_command("qwen3-8-27b-ud-iq2-m", "qwen3-8-27b-ud-iq2-m")
        self.assertIn("--custom_output_file", cmd)
        self.assertNotIn("--output_file", cmd)

    def test_terminalbench_is_serial_and_selects_single_task_when_configured(self):
        adapter = TerminalBenchAdapter(
            self._cfg(),
            {
                "dataset": "terminal-bench/terminal-bench@latest",
                "agent": "terminus-2",
                "n_concurrent": 1,
                "task": "ico-path-patch",
            },
            Path("results"),
        )
        cmd = adapter.build_command("qwen3-8-27b-ud-iq2-m", "qwen3-8-27b-ud-iq2-m")
        self.assertEqual(cmd[cmd.index("--agent") + 1], "terminus-2")
        self.assertEqual(cmd[cmd.index("--n-concurrent") + 1], "1")
        self.assertEqual(cmd[cmd.index("--include-task-name") + 1], "ico-path-patch")


if __name__ == "__main__":
    unittest.main()
