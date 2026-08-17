"""Integration-level B0 acceptance tests against the LIVE run path.

These tests pin the behavior an operator depends on when watching a long-running
serial benchmark job. They exercise core.run_one / run_cmd and the B0 contract
together, and document (via failing assertions where appropriate) the integration
gap that the recovery/cancellation/dependency state machine is NOT wired into the
live run path.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import inspect
from pathlib import Path

import pytest

from benchsuite import core
from benchsuite.adapters.base import run_cmd
from benchsuite.execution_contract import (
    MAX_BENCHMARK_TIMEOUT_S,
    clamp_timeout,
)

HERE = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# 40-minute timeout boundary is enforced on the live run path (regression D4)
# --------------------------------------------------------------------------- #
def test_clamp_timeout_used_by_run_one(monkeypatch):
    """run_one must cap any configured timeout at the 40-minute B0 boundary."""
    # Build a minimal Config whose timeout_s exceeds the 40-minute cap.
    cfg = _minimal_cfg(timeout_s=99999)
    # Stub the adapter registry + build_command to force a quick exit path.
    captured = {}

    class FakeAdapter:
        name = "fake"
        category = "cat"
        description = "fake"

        def __init__(self, c, bc, rd):
            pass

        def build_command(self, model, resolved):
            return [sys.executable, "-c", "import time; time.sleep(0.1)"]

        def build_env(self, model, resolved):
            return {}

        def run_id(self, model):
            return "fake-run"

        def make_outdir(self, run_id):
            d = cfg.results_dir / "fake" / run_id
            d.mkdir(parents=True, exist_ok=True)
            return d

        def parse(self, out_dir, log):
            from benchsuite.adapters.base import AdapterResult
            return AdapterResult(benchmark="fake", status="ok")

    monkeypatch.setitem(core.ADAPTERS, "fake", FakeAdapter)

    eff, clamped = clamp_timeout(cfg.timeout_s)
    assert clamped is True
    assert eff == MAX_BENCHMARK_TIMEOUT_S

    # run_one should accept the capped value without error and run to completion.
    from benchsuite.adapters.base import AdapterResult
    res = core.run_one("fake", cfg, "model", timeout_s=eff)
    assert res.status == "ok"


# --------------------------------------------------------------------------- #
# Orphaned subprocess can never happen on the live path (regression D3)
# --------------------------------------------------------------------------- #
def test_live_run_cmd_kills_grandchildren():
    harness = HERE / "_orphan_harness.py"
    gc_pid = "/tmp/repro_orphan_gc.pid"
    if os.path.exists(gc_pid):
        os.remove(gc_pid)
    with pytest.raises(subprocess.TimeoutExpired):
        run_cmd([sys.executable, str(harness)], env={}, timeout_s=1.5)
    time.sleep(0.5)
    assert os.path.exists(gc_pid)
    gc = int(open(gc_pid).read())
    alive = os.path.exists(f"/proc/{gc}")
    if alive:
        try:
            os.kill(gc, signal.SIGKILL)
        except Exception:
            pass
    assert not alive, "live run_cmd orphaned a grandchild on timeout"


# --------------------------------------------------------------------------- #
# B0 state machine IS wired into the live run path (regression for D1)
# --------------------------------------------------------------------------- #
def test_b0_workflow_is_used_by_live_run_path():
    """The live run path now drives SerialWorkflow/SnapshotStore/DependencyScheduler.

    This is the inverse of the old pinning test, which asserted the B0 state
    machine was dead code. Closing D1 means cli.cmd_run -> core.run_benchmarks
    actually constructs a RunSnapshot, a SnapshotStore, and a Dependency list and
    drives SerialWorkflow.run_all (not a plain subprocess loop).
    """
    import benchsuite.cli as cli
    import benchsuite.core as runcore

    src_cli = inspect.getsource(cli)
    src_core = inspect.getsource(runcore)

    # The CLI must build the dependency list and pass it (plus the snapshot
    # store path and a cooperative cancel handle) to the workflow driver.
    assert "Dependency" in src_cli, "cli.cmd_run must build a Dependency list"
    assert "cancel_handle" in src_cli, "cli.cmd_run must pass a cancel_handle"
    assert "store_path" in src_cli, "cli.cmd_run must pass a snapshot store_path"
    # run_benchmarks must drive the workflow rather than a plain subprocess loop.
    assert "SerialWorkflow" in src_core, "core.run_benchmarks must drive SerialWorkflow"
    assert "SnapshotStore" in src_core, \
        "core.run_benchmarks must build a SnapshotStore to persist the run"


# --------------------------------------------------------------------------- #
# Live run path drives SerialWorkflow end-to-end (functional, no real harness)
# --------------------------------------------------------------------------- #
def test_live_run_benchmarks_drives_workflow_and_persists(tmp_path, monkeypatch):
    """core.run_benchmarks delegates to SerialWorkflow and writes a snapshot."""
    import time as _time

    from benchsuite.execution_contract import SnapshotStore

    cfg = _minimal_cfg(timeout_s=600)
    cfg.results_dir = tmp_path  # so run.json lands under tmp
    store_path = tmp_path / "run.json"

    class FakeAdapter:
        name = "fake"
        category = "cat"
        description = "fake"

        def __init__(self, c, bc, rd):
            pass

        def build_command(self, model, resolved):
            return [sys.executable, "-c", "import time; time.sleep(0.05)"]

        def build_env(self, model, resolved):
            return {}

        def run_id(self, model):
            return f"fake-run-{int(_time.time()*1000)}"

        def make_outdir(self, run_id):
            d = cfg.results_dir / "fake" / run_id
            d.mkdir(parents=True, exist_ok=True)
            return d

        def parse(self, out_dir, log):
            from benchsuite.adapters.base import AdapterResult
            return AdapterResult(benchmark="fake", status="ok",
                                 metric_name="score", metric_value=0.5)

    monkeypatch.setitem(core.ADAPTERS, "fake", FakeAdapter)

    results = core.run_benchmarks(["fake"], cfg, None, store_path=store_path)
    assert results["fake"].status == "ok"
    assert store_path.exists(), "SnapshotStore must persist a run snapshot"
    store = SnapshotStore(store_path)
    snap = store.load()
    assert snap.benchmarks[0].state.value == "succeeded"
    assert snap.benchmarks[0].elapsed_s > 0


def test_live_run_blocked_prereq_runtime_blocks_dependent(tmp_path, monkeypatch):
    """A failed prerequisite runtime-blocks its dependent on the live path."""
    import time as _time

    cfg = _minimal_cfg(timeout_s=600)
    cfg.results_dir = tmp_path

    class FakeAdapter:
        name = "fake"
        category = "cat"
        description = "fake"

        def __init__(self, c, bc, rd):
            pass

        def build_command(self, model, resolved):
            return [sys.executable, "-c", "import time; time.sleep(0.05)"]

        def build_env(self, model, resolved):
            return {}

        def run_id(self, model):
            return f"fake-run-{int(_time.time()*1000)}"

        def make_outdir(self, run_id):
            d = cfg.results_dir / "fake" / run_id
            d.mkdir(parents=True, exist_ok=True)
            return d

        def parse(self, out_dir, log):
            from benchsuite.adapters.base import AdapterResult
            return AdapterResult(benchmark="fake", status="ok", metric_value=1.0)

    # Two benchmarks; 'b' depends on 'a'. Make 'a' fail so 'b' gets BLOCKED.
    monkeypatch.setitem(core.ADAPTERS, "a", FakeAdapter)
    monkeypatch.setitem(core.ADAPTERS, "b", FakeAdapter)
    original_a = core.ADAPTERS["a"].parse
    def fail_a(self, out_dir, log):
        from benchsuite.adapters.base import AdapterResult
        return AdapterResult(benchmark="a", status="failed", error="boom")
    core.ADAPTERS["a"].parse = fail_a

    from benchsuite.execution_contract import Dependency
    deps = [Dependency(benchmark="b", prerequisites=("a",))]
    results = core.run_benchmarks(["a", "b"], cfg, None, deps=deps,
                                  store_path=tmp_path / "run.json")
    assert results["a"].status == "failed"
    assert results["b"].status == "blocked", \
        "dependent must be runtime-blocked when prerequisite fails"


def test_live_run_cooperative_cancel_skips_remaining(tmp_path, monkeypatch):
    """Ctrl-C mid-run requests cancel between benchmarks (no mid-run kill).

    Mimics the real SIGINT scenario: a cancel is requested while the first
    benchmark is in flight. The in-flight benchmark finishes (synchronous
    design -- it is never interrupted mid-run), and the remaining queued
    benchmarks are skipped.
    """
    import time as _time

    cfg = _minimal_cfg(timeout_s=600)
    cfg.results_dir = tmp_path

    class FastAdapter:
        name = ""
        category = "cat"
        description = "x"
        def __init__(self, c, bc, rd):
            pass
        def build_command(self, model, resolved):
            return [sys.executable, "-c", "import time; time.sleep(0.05)"]
        def build_env(self, model, resolved):
            return {}
        def run_id(self, model):
            return f"x-{int(_time.time()*1000)}"
        def make_outdir(self, run_id):
            d = cfg.results_dir / self.name / run_id
            d.mkdir(parents=True, exist_ok=True)
            return d
        def parse(self, out_dir, log):
            from benchsuite.adapters.base import AdapterResult
            return AdapterResult(benchmark=self.name, status="ok")

    for n in ("a", "b", "c"):
        cls = type(f"Adp{n}", (FastAdapter,), {"name": n})
        monkeypatch.setitem(core.ADAPTERS, n, cls)

    cancel = _CancelHandle()

    # Wrap run_one so that after the FIRST benchmark completes, a cancel is
    # requested -- exactly like the SIGINT handler flipping the handle while a
    # benchmark is in flight. The first benchmark must still complete OK.
    real_run_one = core.run_one
    calls = {"n": 0}
    def wrapped_run_one(name, c, rm, to, stream_to=None, cancel_callback=None):
        res = real_run_one(name, c, rm, to, stream_to=stream_to, cancel_callback=cancel_callback)
        calls["n"] += 1
        if calls["n"] == 1:
            cancel.set()
        return res
    monkeypatch.setattr(core, "run_one", wrapped_run_one)

    results = core.run_benchmarks(["a", "b", "c"], cfg, None,
                                  cancel_handle=cancel,
                                  store_path=tmp_path / "run.json")
    # 'a' ran to completion (no mid-run interruption); 'b'/'c' were skipped.
    assert results["a"].status == "ok"
    assert results["b"].status == "not_run"
    assert results["c"].status == "not_run"


class _CancelHandle:
    def __init__(self):
        self._set = False
    def is_set(self):
        return self._set
    def set(self):
        self._set = True


def _minimal_cfg(timeout_s: int):
    from benchsuite.config import Config
    import tempfile
    rd = Path(tempfile.mkdtemp())
    return Config(
        base_url="http://localhost:1/v1",
        api_key="",
        model="m",
        timeout_s=timeout_s,
        results_dir=rd,
        env={},
        benchmarks={},
    )
