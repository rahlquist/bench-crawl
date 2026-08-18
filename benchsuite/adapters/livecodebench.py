"""LiveCodeBench via lcb_runner (OpenAI-compatible backend)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .base import AdapterResult, BenchmarkAdapter


class LiveCodeBenchAdapter(BenchmarkAdapter):
    name = "livecodebench"
    category = "code-gen"
    description = "Contamination-free competitive programming code generation"

    def prereqs(self) -> list[tuple[str, str | None]]:
        return [
            ("livecodebench (lcb_runner)", "python"),
            ("lcb_runner module importable", None),
        ]

    def build_env(self, model: str, resolved_model: str) -> dict:
        return {
            "OPENAI_API_BASE": self.cfg.base_url,
            "OPENAI_KEY": self.cfg.api_key or "none",
            "OPENAI_API_KEY": self.cfg.api_key or "none",
        }

    @property
    def run_cwd(self) -> Path:
        return self.project_root / self.bench_cfg.get("repo", "LiveCodeBench")

    def extra_preflight_failures(self) -> list[str]:
        import importlib.util

        return [] if importlib.util.find_spec("lcb_runner") else [
            "Python module not installed: lcb_runner"
        ]

    def build_command(self, model: str, resolved_model: str) -> list[str]:
        cmd = [
            sys.executable,
            "-m",
            "lcb_runner.runner.main",
            "--model",
            resolved_model,
            "--scenario",
            self.bench_cfg.get("scenario", "codegeneration"),
            "--release_version",
            self.bench_cfg.get("release", "release_v2"),
            "--custom_output_file",
            str(self.results_dir / f"livecodebench_{resolved_model}.json"),
        ]
        if self.bench_cfg.get("evaluate", True):
            cmd.append("--evaluate")
        return cmd

    def parse(self, out_dir: Path, log: str) -> AdapterResult:
        target = self.results_dir / f"livecodebench_{self.cfg.model}.json"
        if not target.exists():
            candidates = sorted(self.results_dir.glob("livecodebench_*.json"))
            target = candidates[-1] if candidates else None
        if target is not None and not target.exists():
            # lcb_runner writes its generated output beside the custom path
            # using the model/scenario naming convention. Locate the matching
            # eval summary without accepting an unrelated historical run.
            repo_output = self.run_cwd / "output" / self.cfg.model
            eval_files = sorted(repo_output.glob("*_eval.json"))
            target = eval_files[-1] if eval_files else None
        if target is None:
            return AdapterResult(
                benchmark=self.name,
                status="failed",
                error="no lcb output json",
                detail={"log_tail": log[-1500:]},
            )

        data = json.loads(target.read_text())
        detail = data if isinstance(data, dict) else {"items": len(data)}
        metric = detail.get("pass@1") if isinstance(detail, dict) else None
        if metric is None and isinstance(data, list) and data and isinstance(data[0], dict):
            metric = data[0].get("pass@1")
        if metric is None:
            return AdapterResult(
                benchmark=self.name,
                status="failed",
                error="lcb output has no pass@1 metric",
                detail=detail,
            )
        return AdapterResult(
            benchmark=self.name,
            status="ok",
            metric_name="pass@1",
            metric_value=float(metric),
            detail=detail,
        )
