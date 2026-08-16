from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from benchsuite.adapters.base import AdapterResult
from benchsuite.config import Config
from benchsuite import core
from benchsuite.report import render_markdown


class PreflightReportingTests(unittest.TestCase):
    def make_config(self, root: Path) -> Config:
        return Config(
            base_url="http://model.test/v1",
            api_key="",
            model="demo-model",
            timeout_s=10,
            results_dir=root / "results",
            env={},
            benchmarks={
                "mmlu": {"enabled": True},
                "foodtruck": {"enabled": True},
            },
        )

    def test_preflight_reports_missing_binary_without_running_harness(self):
        with TemporaryDirectory() as tmp:
            cfg = self.make_config(Path(tmp))
            with patch("benchsuite.preflight.check_endpoint") as endpoint:
                endpoint.return_value.reachable = True
                endpoint.return_value.model_ids = ["demo-model"]
                with patch("shutil.which", return_value=None), patch("benchsuite.preflight.sys.executable", "/missing/python"):
                    report = core.preflight(["mmlu", "foodtruck"], cfg)

            self.assertFalse(report.ok)
            self.assertEqual(report.benchmarks["mmlu"].status, "blocked")
            self.assertTrue(report.benchmarks["mmlu"].failures)
            self.assertEqual(report.benchmarks["foodtruck"].status, "ready")

    def test_ending_report_shows_score_and_non_scoring_status(self):
        results = {
            "mmlu": AdapterResult(
                benchmark="mmlu", status="ok", metric_name="acc", metric_value=0.75
            ),
            "deepswe": AdapterResult(
                benchmark="deepswe", status="blocked", error="missing pier"
            ),
            "foodtruck": AdapterResult(
                benchmark="foodtruck", status="not_run",
                error="hosted submission required"
            ),
        }
        report = render_markdown(results, "demo-model", "http://model.test/v1")
        self.assertIn("| mmlu |", report)
        self.assertIn("| acc | 0.7500 |", report)
        self.assertIn("| deepswe |", report)
        self.assertIn("blocked", report)
        self.assertIn("| foodtruck |", report)
        self.assertIn("hosted submission required", report)
        self.assertIn("Scored benchmarks", report)
        self.assertIn("1", report)


if __name__ == "__main__":
    unittest.main()
