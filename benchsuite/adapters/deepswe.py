"""DeepSWE via pier (Harbor-compatible sandboxed agent eval)."""
from __future__ import annotations

import json
from pathlib import Path

from .base import AdapterResult, BenchmarkAdapter


class DeepSWEAdapter(BenchmarkAdapter):
    name = "deepswe"
    category = "agentic-coding"
    description = "113 original long-horizon software engineering tasks (Datacurve)"

    def prereqs(self) -> list[tuple[str, str | None]]:
        return [
            ("pier (uv tool install datacurve-pier)", "pier"),
            (f"deep-swe tasks_dir clone at {self.bench_cfg.get('tasks_dir', 'deep-swe/tasks')}", None),
        ]

    def build_env(self, model: str, resolved_model: str) -> dict:
        # pier runs mini-swe-agent which is OpenAI-compatible.
        return {
            "OPENAI_API_BASE": self.cfg.base_url,
            "OPENAI_API_KEY": self.cfg.api_key or "none",
            "ANTHROPIC_API_KEY": "",  # unused; pier reads model prefix
        }

    def extra_preflight_failures(self) -> list[str]:
        tasks = Path(self.bench_cfg.get("tasks_dir", "deep-swe/tasks"))
        return [] if tasks.is_dir() else [f"tasks directory not found: {tasks}"]

    def build_command(self, model: str, resolved_model: str) -> list[str]:
        tasks_dir = self.bench_cfg.get("tasks_dir", "deep-swe/tasks")
        agent = self.bench_cfg.get("agent", "mini-swe-agent")
        pier_model = f"openai/{resolved_model}"  # pier routes via litellm openai/
        cmd = [
            "pier", "run",
            "-p", tasks_dir,
            "--agent", agent,
            "--model", pier_model,
            "--output-dir", str(self.results_dir / "deepswe"),
        ]
        n_tasks = self.bench_cfg.get("n_tasks", 0)
        if n_tasks:
            cmd += ["--n-tasks", str(n_tasks), "--sample-seed", str(self.bench_cfg.get("sample_seed", 0))]
        return cmd

    def parse(self, out_dir: Path, log: str) -> AdapterResult:
        # pier/harbor writes per-task verifier/reward.json under output-dir.
        reward_files = sorted(self.results_dir.glob("**/verifier/reward.json"))
        reward_files += sorted(self.results_dir.glob("**/reward.json"))
        if not reward_files:
            return AdapterResult(benchmark=self.name, status="failed",
                                 error="no pier reward.json found", detail={"log_tail": log[-1500:]})
        passed = 0
        total = 0
        for rf in reward_files:
            try:
                d = json.loads(rf.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            total += 1
            if isinstance(d, dict) and d.get("reward") or (isinstance(d, dict) and d.get("success")):
                passed += 1
        return AdapterResult(
            benchmark=self.name,
            status="ok",
            metric_name="pass@1",
            metric_value=(passed / total) if total else None,
            detail={"tasks_graded": total, "tasks_passed": passed,
                    "reward_files": len(reward_files)},
        )
