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
            cmd += ["--include-task-name", task]
        return cmd

    def parse(self, out_dir: Path, log: str) -> AdapterResult:
        # Harbor's job summary is authoritative. A clean CLI exit is not enough:
        # an errored/cancelled trial is a failed benchmark outcome.
        candidates = sorted(self.results_dir.glob("**/result.json"))
        summary = None
        for cand in candidates:
            try:
                data = json.loads(cand.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and isinstance(data.get("stats"), dict):
                summary = data
        if summary is None:
            return AdapterResult(
                benchmark=self.name,
                status="failed",
                error="no harbor result.json found",
                detail={"log_tail": log[-1500:]},
            )
        stats = summary["stats"]
        if stats.get("n_errored_trials", 0) or stats.get("n_cancelled_trials", 0):
            return AdapterResult(
                benchmark=self.name,
                status="failed",
                error="harbor trial errored or was cancelled",
                detail=summary,
            )
        evals = stats.get("evals", {})
        if stats.get("n_completed_trials", 0) < 1 or not evals:
            return AdapterResult(
                benchmark=self.name,
                status="failed",
                error="harbor completed without a scored trial",
                detail=summary,
            )
        evaluation = next(iter(evals.values()))
        errors = evaluation.get("n_errors", 0)
        metrics = evaluation.get("metrics", [])
        if errors or not metrics:
            return AdapterResult(
                benchmark=self.name,
                status="failed",
                error="harbor produced no valid metric",
                detail=summary,
            )
        score = metrics[0].get("mean") if isinstance(metrics[0], dict) else None
        if score is None:
            return AdapterResult(
                benchmark=self.name,
                status="failed",
                error="harbor metric mean missing",
                detail=summary,
            )
        return AdapterResult(
            benchmark=self.name,
            status="ok",
            metric_name="pass@1",
            metric_value=float(score),
            detail=summary,
        )
