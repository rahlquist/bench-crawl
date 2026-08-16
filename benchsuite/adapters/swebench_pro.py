"""SWE-bench Pro via the Scale API harness (swe_bench_pro_eval.py)."""
from __future__ import annotations

import json
from pathlib import Path

from .base import AdapterResult, BenchmarkAdapter


class SWEBenchProAdapter(BenchmarkAdapter):
    name = "swebench_pro"
    category = "agentic-coding"
    description = "1,865 long-horizon software engineering tasks (Scale)"

    def prereqs(self) -> list[tuple[str, str | None]]:
        return [
            ("SWE-bench_Pro-os clone", None),
            ("docker", "docker"),
            ("swe_bench_pro_eval.py (in repo)", "python"),
        ]

    def build_env(self, model: str, resolved_model: str) -> dict:
        # The scale harness accepts vllm / OpenAI-compatible base URL.
        return {
            "VLLM_API_KEY": self.cfg.api_key or "EMPTY",
            "OPENAI_API_BASE": self.cfg.base_url,
        }

    def build_command(self, model: str, resolved_model: str) -> list[str]:
        repo = self.bench_cfg.get("repo", "SWE-bench_Pro-os")
        script = f"{repo}/swe_bench_pro_eval.py"
        cmd = [
            "python", script,
            "--raw_sample_path", f"{repo}/swe_bench_pro_full.csv",
            "--patch_path", str(self.results_dir / f"swebench_pro_{resolved_model}.json"),
            "--output_dir", str(self.results_dir / "swebench_pro"),
            "--num_workers", str(self.bench_cfg.get("max_workers", 4)),
        ]
        return cmd

    def parse(self, out_dir: Path, log: str) -> AdapterResult:
        # Output: a report json with instance-level pass/fail.
        candidates = sorted(self.results_dir.glob("**/*.json"))
        detail: dict = {}
        for cand in candidates:
            try:
                data = json.loads(cand.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and len(data) > 2:
                detail = data
                break
        if not detail:
            return AdapterResult(benchmark=self.name, status="failed",
                                 error="no swebench_pro output json", detail={"log_tail": log[-1500:]})
        # compute pass rate from resolved/non-resolved keys if present
        passed = sum(1 for v in detail.values() if isinstance(v, dict) and v.get("resolved"))
        total = sum(1 for v in detail.values() if isinstance(v, dict))
        return AdapterResult(
            benchmark=self.name,
            status="ok",
            metric_name="resolve_rate",
            metric_value=(passed / total) if total else None,
            detail={"instances": total, "resolved": passed, "sample": detail},
        )
