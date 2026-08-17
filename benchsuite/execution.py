"""Serial, recoverable execution workflow used by the CLI and API."""
from __future__ import annotations
from collections.abc import Callable, Mapping
from pathlib import Path
from .execution_contract import *

# Translate a live AdapterResult.status vocabulary into BenchmarkState. The
# adapter layer uses 'ok'/'failed'/'blocked'/'not_run'; the B0 contract uses
# 'succeeded'/'failed'/'blocked'/'skipped'. Unknown statuses map to FAILED so a
# silent contract drift does not masquerade as success.
BENCHMARK_STATE_FROM_ADAPTER_STATUS={
    'ok': BenchmarkState.SUCCEEDED,
    'succeeded': BenchmarkState.SUCCEEDED,
    'passed': BenchmarkState.SUCCEEDED,
    'failed': BenchmarkState.FAILED,
    'error': BenchmarkState.FAILED,
    'blocked': BenchmarkState.BLOCKED,
    'not_run': BenchmarkState.SKIPPED,
    'skipped': BenchmarkState.SKIPPED,
    'cancelled': BenchmarkState.CANCELLED,
    'timed_out': BenchmarkState.TIMED_OUT,
}

class SerialWorkflow:
    def __init__(self, run: RunSnapshot, dependencies=(), store: SnapshotStore|None=None,
                 execute: Callable[[str], object]|None=None, on_event: Callable[[dict],None]|None=None):
        self.run, self.store, self.execute, self.on_event = run, store, execute, on_event
        self.scheduler=DependencyScheduler(run, dependencies, store)
    def _save(self):
        if self.store: self.store.save(self.run)
    def _event(self, kind, benchmark=None, **value):
        event={'kind':kind,'benchmark':benchmark,**value}
        if self.on_event: self.on_event(event)
    def cancel(self):
        changed=request_cancel(self.run); self._save(); self._event('cancel_requested')
        return changed
    def run_all(self):
        self.run.state=RunState.RUNNING; self._save()
        while True:
            b=self.scheduler.next()
            if b is None: break
            if self.run.cancel_requested:
                b.transition(BenchmarkState.CANCELLED); self._save(); continue
            self.run.active=b.name; b.transition(BenchmarkState.RUNNING); b.started_at=__import__('time').time(); self._save(); self._event('started',b.name)
            try:
                result=self.execute(b.name) if self.execute else None
                # Map a live AdapterResult (status/error) or a contract-shaped
                # result (state/failure_reason) to a BenchmarkState. Guarding
                # both shapes avoids silently treating every live result as
                # SUCCEEDED (AdapterResult has no .state attribute). The live
                # AdapterResult uses status 'ok' for success -- not 'succeeded'.
                status=getattr(result,'status',None)
                if status is not None:
                    st=BENCHMARK_STATE_FROM_ADAPTER_STATUS.get(status, BenchmarkState.FAILED)
                else:
                    raw=getattr(result,'state',BenchmarkState.SUCCEEDED)
                    st=BenchmarkState(raw) if isinstance(raw,str) else raw
                state=st
                b.stdout=getattr(result,'stdout',''); b.stderr=getattr(result,'stderr','')
                b.exit_code=getattr(result,'exit_code',None)
                b.error=getattr(result,'error',None) or getattr(result,'failure_reason',None)
            except Exception as exc:
                state=BenchmarkState.FAILED; b.error=str(exc)
            b.ended_at=__import__('time').time(); b.elapsed_s=b.ended_at-b.started_at; b.transition(state); self.run.active=None; self._save(); self._event('finished',b.name,state=state.value)
        self.run.active=None; self.run.ended_at=__import__('time').time(); self.run.state=RunState.CANCELLED if self.run.cancel_requested else (RunState.FAILED if any(b.state in {BenchmarkState.FAILED,BenchmarkState.TIMED_OUT} for b in self.run.benchmarks) else RunState.COMPLETED); self._save(); return self.run

def make_run(run_id, names, dependencies=()):
    return RunSnapshot(run_id=run_id, benchmarks=[BenchmarkSnapshot(n) for n in names], created_at=__import__('time').time())

__all__=['SerialWorkflow','make_run']
