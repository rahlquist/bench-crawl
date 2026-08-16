"""Run orchestration: drive adapters, collect results."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .adapters.base import AdapterResult, BenchmarkAdapter
from .config import Config, model_for_benchmark
from .endpoint import resolve_model_id

# registry filled by adapters/__init__.py
ADAPTERS: dict[str, type[BenchmarkAdapter]] = {}


def register(cls: type[BenchmarkAdapter]) -> type[BenchmarkAdapter]:
    ADAPTERS[cls.name] = cls
    return cls


def list_adapters() -> list[str]:
    return sorted(ADAPTERS)


def run_one(
    name: str,
    cfg: Config,
    resolved_model: str,
    timeout_s: int,
) -> AdapterResult:
    if name not in ADAPTERS:
        return AdapterResult(benchmark=name, status="not_run",
                             error=f"unknown benchmark '{name}'")
    bench_cfg = cfg.benchmarks.get(name, {})
    adapter = ADAPTERS[name](cfg, bench_cfg, cfg.results_dir)
    model = model_for_benchmark(cfg, bench_cfg)

    try:
        cmd = adapter.build_command(model, resolved_model)
    except Exception as exc:  # noqa: BLE001
        return AdapterResult(benchmark=name, status="failed", error=f"build command: {exc}")

    run_id = adapter.run_id(model)
    out_dir = adapter.make_outdir(run_id)
    env = {"BENCHSUITE_BENCH": name, "BENCHSUITE_MODEL": model,
           "BENCHSUITE_RESOLVED_MODEL": resolved_model}
    env.update(cfg.env)
    env.update(adapter.build_env(model, resolved_model))

    log_path = out_dir / "harness.log"
    try:
        from .adapters.base import run_cmd

        proc = run_cmd(cmd, env, cwd=out_dir, timeout_s=timeout_s, log_path=log_path)
    except subprocess.TimeoutExpired:
        return AdapterResult(benchmark=name, status="failed", output_dir=str(out_dir),
                             error="timeout")
    except Exception as exc:  # noqa: BLE001
        return AdapterResult(benchmark=name, status="failed", output_dir=str(out_dir),
                             error=str(exc))

    log = log_path.read_text() if log_path.exists() else ""
    if proc.returncode != 0:
        return AdapterResult(
            benchmark=name,
            status="failed",
            output_dir=str(out_dir),
            error=f"harness exited with code {proc.returncode}",
            detail={"log_tail": log[-3000:]},
        )
    try:
        result = adapter.parse(out_dir, log)
    except Exception as exc:  # noqa: BLE001
        result = AdapterResult(benchmark=name, status="failed", output_dir=str(out_dir),
                               error=f"parse: {exc}")
    result.output_dir = str(out_dir)
    return result


def run_benchmarks(names: list[str], cfg: Config) -> dict[str, AdapterResult]:
    resolved = resolve_model_id(cfg.base_url, cfg.api_key, cfg.model)
    results: dict[str, AdapterResult] = {}
    for name in names:
        results[name] = run_one(name, cfg, resolved or cfg.model, cfg.timeout_s)
        # persist incrementally so a long multi-benchmark run survives a crash
        write_results(cfg, results)
    return results


def write_results(cfg: Config, results: dict[str, AdapterResult]) -> Path:
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.results_dir / "latest.json"
    payload = {
        "base_url": cfg.base_url,
        "model": cfg.model,
        "benchmarks": {k: v.to_dict() for k, v in results.items()},
    }
    path.write_text(json.dumps(payload, indent=2))
    return path
