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
# DOCUMENTED GAP: B0 state machine not wired into live run path (D1)
# --------------------------------------------------------------------------- #
def test_b0_workflow_is_not_used_by_live_run_path():
    """Reproduction / documentation of the integration gap.

    The SerialWorkflow/SnapshotStore/DependencyScheduler/request_cancel/recover
    machinery lives in execution.py/execution_contract.py but is never invoked
    by cli.cmd_run -> core.run_benchmarks -> run_one. Until this is wired, the
    recovery/cancellation/dependency features are dead code and the operator has
    no persisted run snapshot to reload after a crash.
    """
    import importlib
    import benchsuite.cli as cli
    import benchsuite.core as runcore

    src_cli = inspect.getsource(cli)
    src_core = inspect.getsource(runcore)

    assert "SerialWorkflow" not in src_cli, "cli should not reference SerialWorkflow (gap closed?)"
    assert "SerialWorkflow" not in src_core, "core should not reference SerialWorkflow (gap closed?)"
    assert "SnapshotStore" not in src_cli
    assert "recover" not in src_core, "core.run_benchmarks should not call recover() (gap closed?)"


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
