import json
import tempfile
import unittest
from pathlib import Path

from benchsuite.adapters.base import AdapterResult
from benchsuite.adapters.terminalbench import TerminalBenchAdapter
from benchsuite.config import Config


class AdapterParsingTests(unittest.TestCase):
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

    def test_terminalbench_rejects_cancelled_trial_with_zero_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            adapter = TerminalBenchAdapter(self._cfg(), {}, results)
            job = results / "2026-01-01"
            job.mkdir()
            (job / "result.json").write_text(json.dumps({
                "stats": {
                    "n_completed_trials": 1,
                    "n_errored_trials": 1,
                    "n_cancelled_trials": 1,
                    "evals": {"task": {"n_errors": 1, "metrics": [{"mean": 0.0}]}}
                }
            }))
            result = adapter.parse(results, "")
            self.assertEqual(result.status, "failed")
            self.assertIsNone(result.metric_value)

    def test_terminalbench_accepts_completed_scored_trial(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            adapter = TerminalBenchAdapter(self._cfg(), {}, results)
            job = results / "2026-01-01"
            job.mkdir()
            (job / "result.json").write_text(json.dumps({
                "stats": {
                    "n_completed_trials": 1,
                    "n_errored_trials": 0,
                    "n_cancelled_trials": 0,
                    "evals": {"task": {"n_errors": 0, "metrics": [{"mean": 0.5}]}}
                }
            }))
            result = adapter.parse(results, "")
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.metric_value, 0.5)


if __name__ == "__main__":
    unittest.main()
