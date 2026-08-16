"""tau-bench (retail/banking) via sierra-research/tau-bench run.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .base import AdapterResult, BenchmarkAdapter


class TauBenchAdapter(BenchmarkAdapter):
    name = "taubench"
    category = "tool-use"
    description = "Tool-Agent-User interaction in enterprise domains (banking)"

    def prereqs(self) -> list[tuple[str, str | None]]:
        return [
            (f"tau-bench clone at {self.bench_cfg.get('repo', 'tau-bench')}", None),
            ("python run.py (pip install -r tau-bench/requirements.txt)", "python"),
        ]

    def build_env(self, model: str, resolved_model: str) -> dict:
        # tau-bench uses the OpenAI provider; point it at our endpoint.
        return {
            "OPENAI_API_BASE": self.cfg.base_url,
            "OPENAI_API_KEY": self.cfg.api_key or "none",
        }

    def extra_preflight_failures(self) -> list[str]:
        repo = Path(self.bench_cfg.get("repo", "tau-bench"))
        run_script = repo / "run.py"
        failures = []
        if not repo.is_dir():
            failures.append(f"repository not found: {repo}")
        if not run_script.exists():
            failures.append(f"run script not found: {run_script}")
        return failures

    def build_command(self, model: str, resolved_model: str) -> list[str]:
        repo = str(self.project_root / self.bench_cfg.get("repo", "tau-bench"))
        env_name = self.bench_cfg.get("env", "banking")
        cmd = [
            sys.executable, f"{repo}/run.py",
            "--agent-strategy", self.bench_cfg.get("agent_strategy", "tool-calling"),
            "--env", env_name,
            "--model", resolved_model,
            "--model-provider", "openai",
            "--user-strategy", self.bench_cfg.get("user_strategy", "llm"),
            "--max-concurrency", str(self.bench_cfg.get("max_concurrency", 2)),
        ]
        return cmd

    def parse(self, out_dir: Path, log: str) -> AdapterResult:
        # tau-bench prints per-task pass and aggregate. Search logs/results.
        candidates = sorted(self.results_dir.glob("**/*.json"))
        detail: dict = {}
        for cand in candidates:
            try:
                data = json.loads(cand.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and ("pass" in str(data).lower() or "results" in data):
                detail = data
                break
        if not detail:
            return AdapterResult(benchmark=self.name, status="failed",
                                 error="no tau-bench result json", detail={"log_tail": log[-2000:]})
        return AdapterResult(
            benchmark=self.name,
            status="ok",
            metric_name="pass",
            metric_value=detail.get("pass") or detail.get("pass_rate"),
            detail=detail,
        )
