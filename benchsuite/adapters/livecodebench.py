"""LiveCodeBench via lcb_runner (litellm / OpenAI-compatible backend)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .base import AdapterResult, BenchmarkAdapter


class LiveCodeBenchAdapter(BenchmarkAdapter):
    name = "livecodebench"
    category = "code-gen"
    description = "Contamination-free competitive programming code generation"

    def prereqs(self) -> list[tuple[str, str | None]]:
        return [("livecodebench (lcb_runner)", "python"),
                ("lcb_runner module importable", None)]

    def build_env(self, model: str, resolved_model: str) -> dict:
        # lcb_runner talks to the model through litellm; OPENAI_API_BASE points
        # it at our endpoint and model id is passed on the CLI.
        return {
            "OPENAI_API_BASE": self.cfg.base_url,
            "OPENAI_API_KEY": self.cfg.api_key or "none",
        }

    def extra_preflight_failures(self) -> list[str]:
        import importlib.util

        return [] if importlib.util.find_spec("lcb_runner") else ["Python module not installed: lcb_runner"]

    def build_command(self, model: str, resolved_model: str) -> list[str]:
        repo = self.bench_cfg.get("repo", "")
        release = self.bench_cfg.get("release", "release_v2")
        scenario = self.bench_cfg.get("scenario", "codegeneration")
        evaluate = self.bench_cfg.get("evaluate", True)

        module = f"lcb_runner.runner.main" if not repo else \
            f"lcb_runner.runner.main"  # repo path used as cwd

        cmd = [
            "python", "-m", module,
            "--model", resolved_model,
            "--scenario", scenario,
            "--release_version", release,
            "--output_file", str(self.results_dir / f"livecodebench_{resolved_model}.json"),
        ]
        if evaluate:
            cmd.append("--evaluate")
        # lcb_runner pulls the dataset from HF; set version-specific env
        return cmd

    def parse(self, out_dir: Path, log: str) -> AdapterResult:
        # lcb_runner writes results to the output_file path.
        target = self.results_dir / f"livecodebench_{self.cfg.model}.json"
        if not target.exists():
            candidates = sorted(self.results_dir.glob("livecodebench_*.json"))
            target = candidates[-1] if candidates else None
        if target is None:
            return AdapterResult(benchmark=self.name, status="failed",
                                 error="no lcb output json", detail={"log_tail": log[-1500:]})
        data = json.loads(target.read_text())
        # structure varies by release; surface whatever numeric keys exist
        detail = data if isinstance(data, dict) else {"items": len(data)}
        return AdapterResult(
            benchmark=self.name,
            status="ok",
            metric_name="pass@1",
            metric_value=detail.get("pass@1"),
            detail=detail,
        )
