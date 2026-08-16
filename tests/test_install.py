import unittest
from unittest.mock import patch

from benchsuite.install import build_install_plan, format_plan


class InstallPlanTests(unittest.TestCase):
    def test_all_plan_contains_every_local_benchmark_and_marks_foodtruck_hosted(self):
        plan = build_install_plan()
        names = [item.name for item in plan]
        self.assertEqual(
            names,
            ["mmlu", "livecodebench", "deepswe", "terminalbench", "swebench_pro", "taubench", "foodtruck"],
        )
        foodtruck = next(item for item in plan if item.name == "foodtruck")
        self.assertEqual(foodtruck.kind, "hosted")
        self.assertEqual(foodtruck.commands, ())
        self.assertIn("closed-source", foodtruck.notes.lower())

    def test_dry_run_format_is_explicit_and_contains_commands(self):
        output = format_plan(build_install_plan())
        self.assertIn("DRY RUN", output)
        self.assertIn("lm-eval", output)
        self.assertIn("LiveCodeBench.git", output)
        self.assertIn("datacurve-pier", output)
        self.assertIn("harbor", output)
        self.assertIn("hosted-only", output)

    @patch("benchsuite.install.subprocess.run")
    def test_execute_runs_commands_and_skips_hosted_adapter(self, run):
        run.return_value.returncode = 0
        from benchsuite.install import execute_install_plan
        summary = execute_install_plan(build_install_plan(), execute=True)
        self.assertEqual(summary["foodtruck"], "skipped")
        self.assertGreater(run.call_count, 0)
        self.assertTrue(all(call.kwargs.get("check") is True for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
