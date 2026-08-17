"""B0 failure & recovery regression tests.

Covers the defects found during adversarial verification of the integrated B0
implementation:
  - cancel idempotency (request_cancel must not re-transition)
  - 40-minute timeout boundary (clamp_timeout caps runaway requests)
  - orphaned subprocess on timeout (run_cmd kills the whole process group)
  - live-result mapping in SerialWorkflow (status/error, not state/failure_reason)
  - dependency gating (dependent blocked on failed/skipped/cancelled prereq)
  - recover() marks an interrupted RUNNING active benchmark as FAILED
  - snapshot persistence roundtrip (atomic, no leftover temp)
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from benchsuite.execution_contract import (
    BenchmarkSnapshot,
    BenchmarkState,
    Dependency,
    DependencyScheduler,
    RunSnapshot,
    RunState,
    SnapshotStore,
    clamp_timeout,
    recover,
    request_cancel,
)
from benchsuite.execution import SerialWorkflow, make_run


# --------------------------------------------------------------------------- #
# Cancel idempotency (regression for D2)
# --------------------------------------------------------------------------- #
def test_request_cancel_is_idempotent():
    run = make_run("r", ["a"])
    assert request_cancel(run) is True
    # Second call must NOT re-transition and must report no change.
    assert request_cancel(run) is False
    assert run.cancel_requested is True
    assert run.state is RunState.CANCELLING


def test_request_cancel_refused_on_terminal_run():
    for terminal in (RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED):
        run = make_run("r", ["a"])
        run.state = terminal
        assert request_cancel(run) is False


# --------------------------------------------------------------------------- #
# 40-minute timeout boundary (regression for D4)
# --------------------------------------------------------------------------- #
def test_clamp_timeout_caps_at_40_min():
    eff, clamped = clamp_timeout(99999)
    assert clamped is True
    assert eff == 2400


def test_clamp_timeout_passthrough_within_bound():
    eff, clamped = clamp_timeout(600)
    assert clamped is False
    assert eff == 600


def test_clamp_timeout_defaults_to_40_min():
    eff, _ = clamp_timeout(None)
    assert eff == 2400


# --------------------------------------------------------------------------- #
# Orphaned subprocess (regression for D3)
# --------------------------------------------------------------------------- #
def test_run_cmd_kills_process_group_on_timeout():
    """A harness that spawns a long-lived grandchild must not leave it
    orphaned when the parent times out."""
    harness = Path(__file__).resolve().parent.parent / "_orphan_harness.py"
    gc_pid = "/tmp/repro_orphan_gc.pid"
    if os.path.exists(gc_pid):
        os.remove(gc_pid)

    from benchsuite.adapters.base import run_cmd

    with pytest.raises(subprocess.TimeoutExpired):
        run_cmd([sys.executable, str(harness)], env={}, timeout_s=1.5)

    time.sleep(0.5)
    assert os.path.exists(gc_pid), "grandchild pid file should have been written"
    gc = int(open(gc_pid).read())
    alive = os.path.exists(f"/proc/{gc}")
    if alive:
        try:
            os.kill(gc, signal.SIGKILL)
        except Exception:
            pass
    assert not alive, "grandchild was orphaned after parent timeout (process-group kill failed)"


# --------------------------------------------------------------------------- #
# SerialWorkflow live-result mapping (regression for D5)
# --------------------------------------------------------------------------- #
class _LiveResult:
    """Mimics adapters.base.AdapterResult: status/error, NOT state/failure_reason."""
    def __init__(self, status, error=None):
        self.status = status
        self.error = error


def test_run_all_maps_live_result_status():
    run = make_run("r", ["a"])
    wf = SerialWorkflow(run, execute=lambda n: _LiveResult("ok", error=None))

    class _NS:
        pass
    wf.store = _NS()
    # Avoid filesystem store; stub _save.
    wf._save = lambda: None
    res = wf.run_all()
    assert res.benchmarks[0].state is BenchmarkState.SUCCEEDED


def test_run_all_maps_live_result_failure():
    run = make_run("r", ["a"])
    wf = SerialWorkflow(run, execute=lambda n: _LiveResult("failed", error="boom"))
    wf._save = lambda: None
    res = wf.run_all()
    assert res.benchmarks[0].state is BenchmarkState.FAILED
    assert res.benchmarks[0].error == "boom"


def test_run_all_maps_live_result_not_run_to_skipped():
    run = make_run("r", ["a"])
    wf = SerialWorkflow(run, execute=lambda n: _LiveResult("not_run"))
    wf._save = lambda: None
    res = wf.run_all()
    assert res.benchmarks[0].state is BenchmarkState.SKIPPED


def test_run_all_returns_failed_when_any_benchmark_failed():
    run = make_run("r", ["a", "b"])
    def fake(n):
        return _LiveResult("ok") if n == "a" else _LiveResult("failed", error="x")
    wf = SerialWorkflow(run, execute=fake)
    wf._save = lambda: None
    res = wf.run_all()
    assert res.state is RunState.FAILED


# --------------------------------------------------------------------------- #
# Dependency gating (explicit verify item)
# --------------------------------------------------------------------------- #
def test_scheduler_blocks_dependent_on_failed_prereq():
    run = make_run("r", ["a", "b"], [Dependency("b", ("a",))])
    sched = DependencyScheduler(run, [Dependency("b", ("a",))])
    first = sched.next()
    assert first.name == "a"
    first.transition(BenchmarkState.RUNNING)
    first.transition(BenchmarkState.FAILED)
    first.error = "boom"
    assert sched.next() is None
    assert run.benchmarks[1].state is BenchmarkState.BLOCKED
    assert run.benchmarks[1].error == "prerequisite did not succeed"


# --------------------------------------------------------------------------- #
# Recover (crash/reload) semantics
# --------------------------------------------------------------------------- #
def test_recover_fails_interrupted_active_benchmark():
    run = make_run("r", ["a"])
    run.active = "a"
    run.benchmarks[0].state = BenchmarkState.RUNNING
    recovered = recover(run)
    assert recovered.benchmarks[0].state is BenchmarkState.FAILED
    assert recovered.benchmarks[0].error == "interrupted"
    assert recovered.active is None
    assert recovered.state is RunState.FAILED


# --------------------------------------------------------------------------- #
# Snapshot persistence roundtrip (lost-incremental-write guard)
# --------------------------------------------------------------------------- #
def test_snapshot_store_roundtrip_and_atomic(tmp_path):
    store = SnapshotStore(tmp_path / "run.json")
    run = make_run("r", ["a", "b"])
    run.benchmarks[0].state = BenchmarkState.RUNNING
    run.active = "a"
    store.save(run)
    loaded = store.load()
    assert loaded.active == "a"
    assert loaded.benchmarks[0].state is BenchmarkState.RUNNING
    assert loaded.version == 1
    # No leftover temp files.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".run-")]
    assert not leftovers
