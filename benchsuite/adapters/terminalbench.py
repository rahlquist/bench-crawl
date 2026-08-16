"""Terminal-Bench v2 via Harbor (`harbor run`)."""
from __future__ import annotations

import json
from pathlib import Path

from .base import AdapterResult, BenchmarkAdapter


class TerminalBenchAdapter(BenchmarkAdapter):
    name = "terminalbench"
    category = "terminal-agent"
    description = "89 tasks: agents operating in real terminal environments (v2)"

    def prereqs(self) -> list[tuple[str, str | None]]:
        return [("harbor (uv tool install 'harbor[docker]' or harbor[modal])", "harbor")]

    def build_env(self, model: str, resolved_model: str) -> dict:
        return {
            "OPENAI_API_BASE": self.cfg.base_url,
            "OPENAI_API_KEY": self.cfg.api_key or "none",
        }

    def build_command(self, model: str, resolved_model: str) -> list[str]:
        dataset = self.bench_cfg.get("dataset", "terminal-bench/terminal-bench@latest")
        agent = self.bench_cfg.get("agent", "terminus")
        harbor_model = f"openai/{resolved_model}"  # Harbor/litellm openai-compatible
        cmd = [
            "harbor", "run",
            "-d", dataset,
            "--agent", agent,
            "--model", harbor_model,
            "--n-concurrent", str(self.bench_cfg.get("n_concurrent", 1)),
            "--jobs-dir", str(self.results_dir / "terminalbench"),
        ]
        task = self.bench_cfg.get("task", "")
        if task:
            cmd += ["--task-id", task]
        return cmd

    def parse(self, out_dir: Path, log: str) -> AdapterResult:
        # Harbor writes a results JSON under output-dir.
        candidates = sorted(self.results_dir.glob("**/*.json"))
        summary = None
        for cand in candidates:
            try:
                data = json.loads(cand.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and ("passed" in data or "succeeded" in data or "results" in data):
                summary = data
                break
        if summary is None:
            return AdapterResult(benchmark=self.name, status="failed",
                                 error="no harbor summary json found", detail={"log_tail": log[-1500:]})
        return AdapterResult(
            benchmark=self.name,
            status="ok",
            metric_name="pass@1",
            metric_value=summary.get("success_rate") or summary.get("pass@1"),
            detail=summary,
        )
