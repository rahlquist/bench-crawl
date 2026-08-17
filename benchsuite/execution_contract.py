"""Persistent serial benchmark execution state and dependency gating."""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path
from typing import Any
import json, os, tempfile, time

class RunState(str, Enum):
    QUEUED='queued'; RUNNING='running'; CANCELLING='cancelling'; COMPLETED='completed'; FAILED='failed'; CANCELLED='cancelled'
class BenchmarkState(str, Enum):
    QUEUED='queued'; BLOCKED='blocked'; RUNNING='running'; SUCCEEDED='succeeded'; FAILED='failed'; TIMED_OUT='timed_out'; CANCELLED='cancelled'; SKIPPED='skipped'
TERMINAL_BENCHMARK_STATES=frozenset({BenchmarkState.BLOCKED,BenchmarkState.SUCCEEDED,BenchmarkState.FAILED,BenchmarkState.TIMED_OUT,BenchmarkState.CANCELLED,BenchmarkState.SKIPPED})

@dataclass(frozen=True)
class Dependency:
    benchmark: str; prerequisites: tuple[str,...]=()
@dataclass
class BenchmarkSnapshot:
    name: str; state: BenchmarkState=BenchmarkState.QUEUED; started_at: float|None=None; ended_at: float|None=None; elapsed_s: float=0.0; progress: float|None=None; stdout: str=''; stderr: str=''; exit_code: int|None=None; error: str|None=None
    def transition(self, new):
        allowed={BenchmarkState.QUEUED:{BenchmarkState.RUNNING,BenchmarkState.BLOCKED,BenchmarkState.SKIPPED,BenchmarkState.CANCELLED},BenchmarkState.RUNNING:{BenchmarkState.SUCCEEDED,BenchmarkState.FAILED,BenchmarkState.TIMED_OUT,BenchmarkState.CANCELLED}}
        if new not in allowed.get(self.state,set()): raise ValueError(f'invalid benchmark transition: {self.state} -> {new}')
        self.state=new
@dataclass
class RunSnapshot:
    run_id: str; benchmarks: list[BenchmarkSnapshot]; state: RunState=RunState.QUEUED; active: str|None=None; cancel_requested: bool=False; created_at: float|None=None; ended_at: float|None=None; version: int=0; metadata: dict[str,Any]=field(default_factory=dict)

def snapshot_dict(run):
    d=asdict(run); d['state']=run.state.value
    for b in d['benchmarks']: b['state']=b['state'].value
    return d
def load_snapshot(d):
    bs=[BenchmarkSnapshot(**{**x,'state':BenchmarkState(x['state'])}) for x in d['benchmarks']]
    return RunSnapshot(**{**d,'state':RunState(d['state']),'benchmarks':bs})
class SnapshotStore:
    def __init__(self,path): self.path=Path(path)
    def save(self,run):
        run.version+=1; self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(dir=self.path.parent,prefix='.run-',text=True)
        try:
            with os.fdopen(fd,'w') as f: json.dump(snapshot_dict(run),f); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    def load(self):
        return load_snapshot(json.loads(self.path.read_text()))
class DependencyScheduler:
    def __init__(self,run,deps,store=None): self.run=run; self.deps={d.benchmark:d for d in deps}; self.store=store
    def next(self):
        states={b.name:b.state for b in self.run.benchmarks}
        for b in self.run.benchmarks:
            if b.state is not BenchmarkState.QUEUED: continue
            d=self.deps.get(b.name); ps=d.prerequisites if d else ()
            if any(states.get(p) in TERMINAL_BENCHMARK_STATES-{BenchmarkState.SUCCEEDED} for p in ps):
                b.transition(BenchmarkState.BLOCKED); b.error='prerequisite did not succeed'; self._save(); continue
            if all(states.get(p) is BenchmarkState.SUCCEEDED for p in ps): return b
        return None
    def _save(self):
        if self.store: self.store.save(self.run)
    def mark(self,name,state,error=None):
        b=next(x for x in self.run.benchmarks if x.name==name); b.transition(state); b.error=error; self._save()

def request_cancel(run):
    if run.state in {RunState.COMPLETED,RunState.FAILED,RunState.CANCELLED}: return False
    run.cancel_requested=True; run.state=RunState.CANCELLING; return True

def recover(run):
    if run.active:
        b=next(x for x in run.benchmarks if x.name==run.active)
        if b.state is BenchmarkState.RUNNING: b.state=BenchmarkState.FAILED; b.error='interrupted'
        run.active=None; run.state=RunState.FAILED
    return run

__all__=['RunState','BenchmarkState','Dependency','BenchmarkSnapshot','RunSnapshot','SnapshotStore','DependencyScheduler','request_cancel','recover','snapshot_dict','load_snapshot']
