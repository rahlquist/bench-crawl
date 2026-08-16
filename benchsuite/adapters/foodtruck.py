"""FoodTruck Bench.

IMPORTANT: FoodTruck's simulation engine, system prompt, and demand model are
**closed source** (per foodtruckbench.com/methodology). It cannot be run against
a local OpenAI-compatible endpoint the way the other benchmarks can. Models are
submitted to the hosted channel and evaluated there.

This adapter therefore does NOT execute anything. `run` produces a submission
template (model identity + config) under results/foodtruck, which the operator
submits to the FoodTruck team. It cannot be fully automated from this suite.
"""
from __future__ import annotations

import json
import datetime
from pathlib import Path

from .base import AdapterResult, BenchmarkAdapter


class FoodTruckAdapter(BenchmarkAdapter):
    name = "foodtruck"
    category = "business-sim"
    description = "30-day business simulation, 5-run median net worth (CLOSED SOURCE)"

    def prereqs(self) -> list[tuple[str, str | None]]:
        # Nothing to install locally; submission is over the hosted channel.
        return [("hosted submission only — no local harness", None)]

    def build_command(self, model: str, resolved_model: str) -> list[str]:
        # No executable harness exists for local runs. We generate a submission
        # bundle instead of running a subprocess; the runner handles the not-run
        # status via a dedicated path.
        self.make_submission(model, resolved_model)
        return ["true"]

    def build_env(self, model: str, resolved_model: str) -> dict:
        return {}

    def make_submission(self, model: str, resolved_model: str) -> Path:
        sub_dir = self.results_dir / "foodtruck"
        sub_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "benchmark": "foodtruck",
            "generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "status": "hosted_submission_required",
            "note": (
                "FoodTruck is closed source. Submit this bundle to "
                f"{self.bench_cfg.get('contact_email', 'contact@foodtruckbench.com')} "
                "to have the model benchmarked on their hosted engine."
            ),
            "config": {
                "model": model,
                "resolved_model_id": resolved_model,
                "endpoint": self.cfg.base_url,
                "version": "v1.0 Standard Mode",
                "runs_requested": 5,
            },
        }
        path = sub_dir / f"submission_{resolved_model}.json"
        path.write_text(json.dumps(payload, indent=2))
        return path

    def parse(self, out_dir: Path, log: str) -> AdapterResult:
        # A prior submission bundle may already carry a measured result.
        for cand in sorted(self.results_dir.glob("foodtruck/**/*.json")):
            try:
                data = json.loads(cand.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("measured_net_worth") is not None:
                return AdapterResult(
                    benchmark=self.name, status="ok",
                    metric_name="net_worth",
                    metric_value=data["measured_net_worth"],
                    detail=data,
                )
        return AdapterResult(
            benchmark=self.name,
            status="not_run",
            metric_name="net_worth",
            error="hosted submission required (closed-source engine)",
            detail={"log_tail": log[-1000:]},
        )
