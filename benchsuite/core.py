"""Run orchestration: drive adapters, collect results."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from .adapters.base import AdapterResult, BenchmarkAdapter
from .config import Config, model_for_benchmark
from .endpoint import resolve_model_id
from .preflight import PreflightReport, preflight, write_preflight

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
    stream_to: "object | None" = None,
    cancel_callback: "object | None" = None,
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

    # Enforce the B0 40-minute timeout boundary: a single benchmark subprocess
    # must never run longer than MAX_BENCHMARK_TIMEOUT_S regardless of cfg.
    from .execution_contract import clamp_timeout
    effective_timeout, _clamped = clamp_timeout(timeout_s)
    if _clamped:
        # Surface the clamp so an operator watching the run sees the override.
        print(f"  {name}: requested timeout {timeout_s}s capped to {effective_timeout}s (B0 40-min boundary)",
              file=sys.stderr)

    log_path = out_dir / "harness.log"
    try:
        from .adapters.base import run_cmd

        run_cwd = getattr(adapter, "run_cwd", None) or out_dir
        # Stream the harness's stdout/stderr to the console live (B0 "visible
        # serial execution"); the CLI passes sys.stderr so an operator sees each
        # benchmark's output as it runs, not only the post-run harness.log.
        proc = run_cmd(cmd, env, cwd=run_cwd, timeout_s=effective_timeout,
                       log_path=log_path, stream_to=stream_to,
                       cancel_callback=cancel_callback)
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


def run_benchmarks(names: list[str], cfg: Config, preflight_report: PreflightReport | None = None,
                   deps: list | None = None,
                   store_path: Path | None = None,
                   on_event=None,
                   cancel_handle: object | None = None) -> dict[str, AdapterResult]:
    """Run benchmarks serially through the B0 recoverable execution workflow.

    The public signature is preserved: callers (the CLI, report regeneration,
    etc.) still receive ``dict[str, AdapterResult]`` keyed by benchmark name.
    Internally the run is now driven by ``SerialWorkflow`` so that the six B0
    acceptance pillars actually execute on the live path: incremental
    persistence (SnapshotStore), visible serial output (streamed to the
    console), cooperative cancellation, runtime dependency gating, elapsed
    timing, and progress.

    ``deps`` / ``store_path`` / ``on_event`` / ``cancel_handle`` are optional
    wiring hooks used by the CLI. ``deps`` defaults to no dependencies.
    ``store_path`` defaults to ``<results_dir>/run.json``. ``cancel_handle`` is
    an object whose ``is_set()`` returns True to request a cooperative cancel
    between benchmarks; if omitted the run is never cancelled.
    """
    import sys

    from .execution import SerialWorkflow, make_run
    from .execution_contract import BenchmarkState, SnapshotStore

    resolved = (preflight_report.resolved_model if preflight_report else None) or resolve_model_id(cfg.base_url, cfg.api_key, cfg.model)
    run_id = f"run-{int(time.time())}"

    # Static preflight blocking (a prerequisite that never resolved) is folded
    # into the snapshot so a crash mid-run leaves a correct resume snapshot and
    # the scheduler runtime-blocks any dependent immediately.
    deps = list(deps or [])
    preflight_blocked = {name for name in names
                         if preflight_report and preflight_report.benchmarks[name].status == "blocked"}

    run = make_run(run_id, names, dependencies=deps)
    store = SnapshotStore(store_path or (cfg.results_dir / "run.json"))

    for name in preflight_blocked:
        b = next(x for x in run.benchmarks if x.name == name)
        b.state = BenchmarkState.BLOCKED
        b.error = "; ".join(preflight_report.benchmarks[name].failures)

    def execute(name: str) -> AdapterResult:
        # Preflight-blocked benchmarks never execute; the seeded BLOCKED state
        # lets the scheduler runtime-block dependents too.
        if name in preflight_blocked:
            item = preflight_report.benchmarks[name]
            return AdapterResult(benchmark=name, status="blocked",
                                 error="; ".join(item.failures),
                                 detail={"prerequisites": item.prerequisites})
        # Stream live and honor cooperative cancel between output lines.
        cancel_cb = (lambda: bool(getattr(cancel_handle, "is_set", lambda: False)())) if cancel_handle is not None else None
        return run_one(name, cfg, resolved or cfg.model, cfg.timeout_s,
                       stream_to=sys.stderr, cancel_callback=cancel_cb)

    def event(evt):
        if on_event:
            on_event(evt)
        kind = evt.get("kind")
        name = evt.get("benchmark")
        if kind == "started":
            print(f"  >> [{name}] running...", file=sys.stderr)
        elif kind == "finished":
            st = evt.get("state")
            el = evt.get("elapsed_s")
            el_s = f" ({el:.1f}s)" if isinstance(el, (int, float)) else ""
            print(f"  << [{name}] {st}{el_s}", file=sys.stderr)

    wf = SerialWorkflow(run, dependencies=deps, store=store, execute=execute,
                        on_event=event, cancel_handle=cancel_handle)
    final = wf.run_all()

    # Translate the contract states back into the public AdapterResult vocabulary
    # so downstream consumers (report regen, etc.) see the same statuses as
    # before the wiring.
    state_from = {
        "succeeded": "ok", "failed": "failed", "blocked": "blocked",
        "timed_out": "failed", "cancelled": "not_run", "skipped": "skipped",
    }
    results: dict[str, AdapterResult] = {}
    for b in final.benchmarks:
        if b.name in preflight_blocked:
            item = preflight_report.benchmarks[b.name]
            results[b.name] = AdapterResult(benchmark=b.name, status="blocked",
                                            error="; ".join(item.failures),
                                            detail={"prerequisites": item.prerequisites})
            continue
        results[b.name] = AdapterResult(
            benchmark=b.name,
            status=state_from.get(b.state.value, "failed"),
            error=b.error,
            detail={"elapsed_s": b.elapsed_s} if b.elapsed_s else {},
        )
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
