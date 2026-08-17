"""Adversarial verification of the B0 execution_contract / execution modules.

Run with: .venv/bin/python verify_b0.py
No pytest needed; prints PASS/FAIL lines and a final summary.
"""
from __future__ import annotations
import importlib.util, sys, os, time, subprocess, tempfile, json, textwrap, types
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Load execution_contract + execution as a tiny package so the relative import
# `from .execution_contract import *` in execution.py resolves without the heavy
# benchsuite adapter deps.
pkg_name = "_b0pkg"
pkg = types.ModuleType(pkg_name)
pkg.__path__ = [str(HERE / "benchsuite")]
sys.modules[pkg_name] = pkg

def load(modname, filename):
    qual = f"{pkg_name}.{modname}"
    spec = importlib.util.spec_from_file_location(qual, HERE / "benchsuite" / filename)
    m = importlib.util.module_from_spec(spec)
    sys.modules[qual] = m
    spec.loader.exec_module(m)
    return m

ec = load("execution_contract", "execution_contract.py")
ex = load("execution", "execution.py")

RunState = ec.RunState
BenchmarkState = ec.BenchmarkState
Dependency = ec.Dependency
BenchmarkSnapshot = ec.BenchmarkSnapshot
RunSnapshot = ec.RunSnapshot
SnapshotStore = ec.SnapshotStore
DependencyScheduler = ec.DependencyScheduler
request_cancel = ec.request_cancel
recover = ec.recover
make_run = ex.make_run
SerialWorkflow = ex.SerialWorkflow

results = []
def check(name, cond, detail=""):
    results.append((bool(cond), name, detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""))

# ---------------------------------------------------------------------------
# 1. State machine: invalid transition raises
# ---------------------------------------------------------------------------
b = BenchmarkSnapshot("x")
try:
    b.transition(BenchmarkState.SUCCEEDED)  # QUEUED -> SUCCEEDED not allowed
    check("transition QUEUED->SUCCEEDED blocked", False, "no error raised")
except ValueError:
    check("transition QUEUED->SUCCEEDED blocked", True)

# RUNNING -> TIMED_OUT allowed
b2 = BenchmarkSnapshot("y", state=BenchmarkState.RUNNING)
try:
    b2.transition(BenchmarkState.TIMED_OUT)
    check("transition RUNNING->TIMED_OUT allowed", True)
except ValueError as e:
    check("transition RUNNING->TIMED_OUT allowed", False, str(e))

# ---------------------------------------------------------------------------
# 2. Dependency scheduler: blocks dependent on failed prereq
# ---------------------------------------------------------------------------
run = make_run("r1", ["a", "b"], [Dependency("b", ("a",))])
sched = DependencyScheduler(run, [Dependency("b", ("a",))])
# a is ready (no prereqs) -> next returns a
first = sched.next()
check("scheduler picks prerequisite-free 'a' first", first is not None and first.name == "a",
      f"got {None if first is None else first.name}")
# A real benchmark must enter RUNNING before it can fail (state-machine invariant).
first.transition(BenchmarkState.RUNNING)
first.transition(BenchmarkState.FAILED); first.error = "boom"
# now b should be BLOCKED because a did not succeed
nxt = sched.next()
check("dependent 'b' blocked after prereq failure", nxt is None and run.benchmarks[1].state is BenchmarkState.BLOCKED,
      f"b.state={run.benchmarks[1].state}, next={None if nxt is None else nxt.name}")
check("blocked reason recorded", run.benchmarks[1].error == "prerequisite did not succeed",
      f"error={run.benchmarks[1].error!r}")

# ---------------------------------------------------------------------------
# 3. request_cancel: idempotent + terminal guard
# ---------------------------------------------------------------------------
run2 = make_run("r2", ["a"])
request_cancel(run2)
check("cancel sets cancel_requested", run2.cancel_requested is True)
changed2 = request_cancel(run2)
check("cancel idempotent (second call returns False)", changed2 is False)
run3 = make_run("r3", ["a"]); run3.state = RunState.COMPLETED
check("cancel refused on terminal run", request_cancel(run3) is False)

# ---------------------------------------------------------------------------
# 4. recover(): does it clear a stuck RUNNING active benchmark?
# ---------------------------------------------------------------------------
run4 = make_run("r4", ["a"])
run4.active = "a"
run4.benchmarks[0].state = BenchmarkState.RUNNING
recovered = recover(run4)
check("recover fails to clear RUNNING active benchmark", recovered.benchmarks[0].state is BenchmarkState.FAILED,
      f"state={recovered.benchmarks[0].state} (expected FAILED; interrupt NOT detected)")
check("recover markes run FAILED", recovered.state is RunState.FAILED)

# ---------------------------------------------------------------------------
# 5. SnapshotStore: atomic write + load roundtrip
# ---------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
store = SnapshotStore(tmp / "run.json")
run5 = make_run("r5", ["a", "b"])
run5.benchmarks[0].state = BenchmarkState.RUNNING; run5.active = "a"
store.save(run5)
loaded = store.load()
check("store roundtrip preserves active", loaded.active == "a")
check("store roundtrip preserves version increment", loaded.version == 1, f"version={loaded.version}")
# atomic: only one file, no leftover temp
leftover = [p for p in tmp.iterdir() if p.name.startswith(".run-")]
check("no leftover temp files after save", not leftover, f"leftovers={leftover}")

# ---------------------------------------------------------------------------
# 6. SerialWorkflow.run_all with a stub execute fn that throws on the 2nd item
# ---------------------------------------------------------------------------
run6 = make_run("r6", ["a", "b"])
events = []
wf = SerialWorkflow(run6, store=SnapshotStore(tmp / "run6.json"),
                   execute=lambda name: (_ for _ in ()).throw(Exception("boom")) if name == "b" else None,
                   on_event=events.append)
res = wf.run_all()
check("run_all: first benchmark succeeds", res.benchmarks[0].state is BenchmarkState.SUCCEEDED)
check("run_all: exception in execute -> FAILED", res.benchmarks[1].state is BenchmarkState.FAILED,
      f"state={res.benchmarks[1].state}")
check("run_all: run FAILED when a benchmark failed", res.state is RunState.FAILED, f"state={res.state}")

# ---------------------------------------------------------------------------
# 7. SerialWorkflow CANCEL semantics.
#    run_all is SYNCHRONOUS: execute() must return before the loop checks
#    cancel_requested again, so an IN-FLIGHT benchmark cannot be interrupted.
#    Only benchmarks not yet started are skipped (CANCELLED).
# ---------------------------------------------------------------------------
def slow_execute(name):
    time.sleep(0.6)  # simulate a long in-flight benchmark
    return None

run7 = make_run("r7", ["a", "b"])
wf7 = SerialWorkflow(run7, execute=slow_execute, store=SnapshotStore(tmp / "run7.json"))
import threading
def cancel_after_delay():
    time.sleep(0.2)
    wf7.cancel()
t = threading.Thread(target=cancel_after_delay); t.start()
res7 = wf7.run_all(); t.join()
check("cancel does NOT interrupt in-flight benchmark 'a' (still SUCCEEDED)",
      res7.benchmarks[0].state is BenchmarkState.SUCCEEDED,
      f"a.state={res7.benchmarks[0].state}")
check("cancel skips not-yet-started benchmark 'b' (CANCELLED)",
      res7.benchmarks[1].state is BenchmarkState.CANCELLED,
      f"b.state={res7.benchmarks[1].state}")
check("cancel -> overall run CANCELLED", res7.state is RunState.CANCELLED, f"state={res7.state}")

# ---------------------------------------------------------------------------
# 8. Duplicate execution after reload: a second SerialWorkflow on a snapshot
#    that already completed must NOT re-run.
# ---------------------------------------------------------------------------
run8 = make_run("r8", ["a"])
run8.benchmarks[0].state = BenchmarkState.SUCCEEDED
store8 = SnapshotStore(tmp / "run8.json"); store8.save(run8)
reloaded = store8.load()
wf8 = SerialWorkflow(reloaded, execute=lambda n: (_ for _ in ()).throw(RuntimeError("SHOULD NOT RUN")),
                    store=store8)
res8 = wf8.run_all()
check("reload of completed run does not re-execute", res8.benchmarks[0].state is BenchmarkState.SUCCEEDED,
      f"state={res8.benchmarks[0].state}")

# ---------------------------------------------------------------------------
print("\n=== SUMMARY ===")
failed = [n for ok, n, _ in results if not ok]
print(f"{len(results)-len(failed)}/{len(results)} checks passed")
if failed:
    print("FAILURES:")
    for ok, n, d in results:
        if not ok: print(f"  - {n}: {d}")
    sys.exit(1)
print("ALL CHECKS PASSED")
