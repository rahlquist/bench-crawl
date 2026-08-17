"""Live-path B0 acceptance verification (no pytest needed).

Drives the REAL benchsuite package the CLI uses:
  cli.cmd_run -> core.run_benchmarks -> SerialWorkflow.run_all()
                -> run_one -> adapters.base.run_cmd (live subprocess)
                -> SnapshotStore (incremental persistence)
                -> DependencyScheduler (runtime gating)

Proves each of the 7 B0 pillars EXECUTES on the live path, not just that the
dead module imports. Plain stdlib; run with:  python3 verify_b0_live.py
"""
from __future__ import annotations
import io
import os
import sys
import time
import types
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from benchsuite import core
from benchsuite.adapters.base import run_cmd, AdapterResult
from benchsuite.execution_contract import SnapshotStore, Dependency, MAX_BENCHMARK_TIMEOUT_S, clamp_timeout

results = []
def check(name, cond, detail=""):
    results.append((bool(cond), name, detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))

# ---------------------------------------------------------------------------
# Pillar A: LIVE SUBPROCESS OUTPUT actually streams to the sink (run_cmd)
# ---------------------------------------------------------------------------
def test_live_streaming():
    sink = io.StringIO()
    child = [sys.executable, "-c",
             "import time,sys;"
             "print('LINE-ONE'); sys.stdout.flush();"
             "time.sleep(0.2);"
             "print('LINE-TWO'); sys.stdout.flush()"]
    proc = run_cmd(child, env={}, cwd=None, timeout_s=10, stream_to=sink)
    out = sink.getvalue()
    check("live output streams stdout lines to sink",
          "LINE-ONE" in out and "LINE-TWO" in out, repr(out[:120]))
    check("run_cmd returns real exit code", proc.returncode == 0, f"rc={proc.returncode}")

# ---------------------------------------------------------------------------
# Pillar B: 40-MINUTE TIMEOUT BOUNDARY enforced inside run_one (regression D4)
# ---------------------------------------------------------------------------
def test_timeout_clamp_in_run_one():
    cfg = _cfg(timeout_s=9_999_999)
    eff, clamped = clamp_timeout(cfg.timeout_s)
    check("clamp_timeout caps at 40-min boundary", clamped and eff == MAX_BENCHMARK_TIMEOUT_S,
          f"eff={eff}")
    # run_one must ACCEPT the capped value and use it (no error, runs fast).
    class Quick:
        name = "quick"
        def __init__(self, *a): pass
        def build_command(self, *a): return [sys.executable, "-c", "pass"]
        def build_env(self, *a): return {}
        def run_id(self, *a): return "q"
        def make_outdir(self, rid):
            d = cfg.results_dir / "quick" / rid; d.mkdir(parents=True, exist_ok=True); return d
        def parse(self, *a): return AdapterResult(benchmark="quick", status="ok")
    core.ADAPTERS["quick"] = Quick
    res = core.run_one("quick", cfg, "m", timeout_s=eff)
    check("run_one runs a capped-timeout benchmark to completion", res.status == "ok", res.error or "")

# ---------------------------------------------------------------------------
# Pillars C/E/F/G: run_benchmarks drives the workflow END-TO-END with a fake
# adapter that streams lines, depends on a failing prereq, and supports cancel.
# We capture: on_event progress, incremental snapshot saves, dependency gating,
# elapsed time, and live streaming to a captured stderr.
# ---------------------------------------------------------------------------
def test_run_benchmarks_end_to_end():
    tmp = Path(tempfile.mkdtemp())
    cfg = _cfg(timeout_s=600)
    cfg.results_dir = tmp
    store_path = tmp / "run.json"

    # Count incremental persistence (SnapshotStore.save) calls.
    saves = {"n": 0, "versions": []}
    real_save = SnapshotStore.save
    def counting_save(self, run):
        saves["n"] += 1
        saves["versions"].append(run.version)
        return real_save(self, run)
    SnapshotStore.save = counting_save

    events = []
    # Capture live output by redirecting sys.stderr to a recording tee.
    captured_stderr = io.StringIO()
    real_stderr = sys.stderr
    class Tee:
        def write(self, s):
            captured_stderr.write(s); real_stderr.write(s); return len(s)
        def flush(self): real_stderr.flush()
    sys.stderr = Tee()

    try:
        class Echo:
            name = "echo"
            def __init__(self, *a): pass
            def build_command(self, *a):
                return [sys.executable, "-c",
                        "print('BENCH-STREAMED-OUTPUT'); import sys; sys.stdout.flush()"]
            def build_env(self, *a): return {}
            def run_id(self, *a): return f"echo-{int(time.time()*1000)}"
            def make_outdir(self, rid):
                d = cfg.results_dir / "echo" / rid; d.mkdir(parents=True, exist_ok=True); return d
            def parse(self, *a): return AdapterResult(benchmark="echo", status="ok",
                                                       metric_name="score", metric_value=0.42)

        class Boom:
            name = "boom"
            def __init__(self, *a): pass
            def build_command(self, *a): return [sys.executable, "-c", "pass"]
            def build_env(self, *a): return {}
            def run_id(self, *a): return "boom"
            def make_outdir(self, rid):
                d = cfg.results_dir / "boom" / rid; d.mkdir(parents=True, exist_ok=True); return d
            def parse(self, *a): return AdapterResult(benchmark="boom", status="failed",
                                                       error="boom detonated")

        core.ADAPTERS["echo"] = Echo
        core.ADAPTERS["boom"] = Boom

        # 'blocked_dep' depends on failed 'boom' -> must be runtime-BLOCKED.
        deps = [Dependency(benchmark="blocked_dep", prerequisites=("boom",))]
        class Dep:
            name = "blocked_dep"
            def __init__(self, *a): pass
            def build_command(self, *a): return [sys.executable, "-c", "pass"]
            def build_env(self, *a): return {}
            def run_id(self, *a): return "bd"
            def make_outdir(self, rid):
                d = cfg.results_dir / "blocked_dep" / rid; d.mkdir(parents=True, exist_ok=True); return d
            def parse(self, *a): return AdapterResult(benchmark="blocked_dep", status="ok")

        core.ADAPTERS["blocked_dep"] = Dep

        results_map = core.run_benchmarks(
            ["boom", "echo", "blocked_dep"], cfg, None,
            deps=deps, store_path=store_path,
            on_event=events.append,
        )

        # --- Pillar F: dependency gating on the LIVE path ---
        check("failed prerequisite 'boom' -> failed", results_map["boom"].status == "failed",
              results_map["boom"].error or "")
        check("dependent 'blocked_dep' runtime-BLOCKED by failed prereq",
              results_map["blocked_dep"].status == "blocked",
              results_map["blocked_dep"].status)

        # --- Pillar A (run path): live streaming reached the captured stderr ---
        check("live subprocess output streamed on run path (stderr tee)",
              "BENCH-STREAMED-OUTPUT" in captured_stderr.getvalue(),
              captured_stderr.getvalue()[:80])

        # --- Pillar E: progress events emitted (started/finished) ---
        kinds = {e.get("kind") for e in events}
        check("progress events emitted (started/finished)",
              "started" in kinds and "finished" in kinds, str(kinds))

        # --- Pillar C: elapsed time recorded (>0) in the persisted snapshot ---
        store = SnapshotStore(store_path)
        snap = store.load()
        echo_b = next(b for b in snap.benchmarks if b.name == "echo")
        check("elapsed time recorded (>0) in snapshot",
              isinstance(echo_b.elapsed_s, (int, float)) and echo_b.elapsed_s > 0,
              f"elapsed_s={echo_b.elapsed_s}")
        check("snapshot terminal state == succeeded", echo_b.state.value == "succeeded",
              echo_b.state.value)

        # --- Pillar G: incremental persistence (save called many times) ---
        # RUNNING set + each transition => multiple atomic saves, not one.
        check("incremental persistence: SnapshotStore.save called multiple times",
              saves["n"] >= 3, f"saves={saves['n']}, versions={saves['versions']}")
    finally:
        sys.stderr = real_stderr
        SnapshotStore.save = real_save

# ---------------------------------------------------------------------------
# Pillar D: COOPERATIVE CANCELLATION skips remaining benchmarks, no mid-run kill
# ---------------------------------------------------------------------------
def test_cooperative_cancel():
    tmp = Path(tempfile.mkdtemp())
    cfg = _cfg(timeout_s=600)
    cfg.results_dir = tmp

    class Fake:
        name = ""
        def __init__(self, *a): pass
        def build_command(self, *a): return [sys.executable, "-c", "pass"]
        def build_env(self, *a): return {}
        def run_id(self, *a): return f"f-{int(time.time()*1000)}"
        def make_outdir(self, rid):
            d = cfg.results_dir / self.name / rid; d.mkdir(parents=True, exist_ok=True); return d
        def parse(self, *a): return AdapterResult(benchmark=self.name, status="ok")

    for n in ("a", "b", "c"):
        core.ADAPTERS[n] = type(f"Adp{n}", (Fake,), {"name": n})

    cancel = _CancelHandle()
    real_run_one = core.run_one
    calls = {"n": 0}
    def wrapped(name, c, rm, to, stream_to=None, cancel_callback=None):
        res = real_run_one(name, c, rm, to, stream_to=stream_to, cancel_callback=cancel_callback)
        calls["n"] += 1
        if calls["n"] == 1:
            cancel.set()  # SIGINT analogue: request cancel after 1st benchmark
        return res
    core.run_one = wrapped
    try:
        out = core.run_benchmarks(["a", "b", "c"], cfg, None,
                                  cancel_handle=cancel, store_path=tmp / "run.json")
        check("in-flight benchmark 'a' completes before cancel (no mid-run kill)",
              out["a"].status == "ok", out["a"].status)
        check("queued 'b' skipped on cancel", out["b"].status == "not_run", out["b"].status)
        check("queued 'c' skipped on cancel", out["c"].status == "not_run", out["c"].status)
    finally:
        core.run_one = real_run_one


class _CancelHandle:
    def __init__(self): self._set = False
    def is_set(self): return self._set
    def set(self): self._set = True


def _cfg(timeout_s: int):
    from benchsuite.config import Config
    rd = Path(tempfile.mkdtemp())
    return Config(base_url="http://localhost:1/v1", api_key="", model="m",
                  timeout_s=timeout_s, results_dir=rd, env={}, benchmarks={})


if __name__ == "__main__":
    test_live_streaming()
    test_timeout_clamp_in_run_one()
    test_run_benchmarks_end_to_end()
    test_cooperative_cancel()
    print("\n=== SUMMARY ===")
    failed = [n for ok, n, _ in results if not ok]
    print(f"{len(results)-len(failed)}/{len(results)} live-path checks passed")
    if failed:
        print("FAILURES:")
        for ok, n, d in results:
            if not ok: print(f"  - {n}: {d}")
        sys.exit(1)
    print("ALL LIVE-PATH CHECKS PASSED")
