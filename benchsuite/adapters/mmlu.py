"""MMLU via lm-evaluation-harness (local OpenAI-compatible chat completions)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .base import AdapterResult, BenchmarkAdapter


class MMLUAdapter(BenchmarkAdapter):
    name = "mmlu"
    category = "knowledge"
    description = "Massive Multitask Language Understanding (57 subjects, MCQ)"

    def prereqs(self) -> list[tuple[str, str | None]]:
        return [("lm_eval (lm_evaluation-harness)", "lm_eval")]

    def build_command(self, model: str, resolved_model: str) -> list[str]:
        tasks = self.bench_cfg.get("tasks", "mmlu")
        subset = self.bench_cfg.get("subset", "")
        if subset:
            tasks = subset
        cmd = [
            sys.executable, "-m", "lm_eval",
            # MMLU's MCQ metric uses log-likelihood; chat completions do not
            # implement that API. llama.cpp exposes the required completions
            # endpoint, so use lm-eval's local-completions model here.
            "--model", "local-completions",
            "--model_args",
            f"base_url={self.cfg.base_url}/completions,model={resolved_model},tokenizer={self.bench_cfg.get('tokenizer', '')},tokenizer_backend=huggingface,tokenized_requests=false,dtype={self.bench_cfg.get('dtype', 'bfloat16')}",
            "--tasks", tasks,
            "--num_fewshot", str(self.bench_cfg.get("num_fewshot", 5)),
            "--batch_size", str(self.bench_cfg.get("batch_size", 8)),
            "--output_path", str(self.results_dir / "mmlu"),
        ]
        return cmd

    def parse(self, out_dir: Path, log: str) -> AdapterResult:
        # lm-eval writes results to output_path as a directory of json files,
        # or a single <timestamp>.json when output_path points at a dir.
        json_file = None
        if (out_dir / "mmlu").exists():
            files = sorted((out_dir / "mmlu").glob("*.json"))
            if files:
                json_file = files[-1]
        if json_file is None:
            # search results dir upward
            for cand in self.results_dir.glob("**/*.json"):
                try:
                    if "mmlu" in cand.read_text():
                        json_file = cand
                        break
                except OSError:
                    continue
        if json_file is None:
            return AdapterResult(benchmark=self.name, status="failed",
                                 error="no lm-eval output json found", detail={"log_tail": log[-1500:]})

        data = json.loads(json_file.read_text())
        results = data.get("results", {})
        # find the mmlu-ish entry
        key = next((k for k in results if "mmlu" in k), None)
        if key is None and results:
            key = next(iter(results))
        if key is None:
            return AdapterResult(benchmark=self.name, status="failed",
                                 error="no result entry in lm-eval output")
        metrics = results[key]
        acc = metrics.get("acc_norm", metrics.get("acc"))
        return AdapterResult(
            benchmark=self.name,
            status="ok",
            metric_name="acc_norm" if "acc_norm" in metrics else "acc",
            metric_value=acc,
            detail={"task": key, "metrics": metrics, "config": data.get("config", {})},
        )
