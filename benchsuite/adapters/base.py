"""Base adapter interface for benchmark harnesses."""
from __future__ import annotations

import abc
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config


@dataclass
class AdapterResult:
    benchmark: str
    status: str  # ok | failed | skipped | not_run
    metric_name: str | None = None
    metric_value: float | None = None
    detail: dict = field(default_factory=dict)
    output_dir: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "benchmark": self.benchmark,
            "status": self.status,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "detail": self.detail,
            "output_dir": self.output_dir,
            "error": self.error,
        }


class BenchmarkAdapter(abc.ABC):
    """One benchmark. Each adapter knows how to:
    - verify its prerequisites are installed (prereqs())
    - assemble the command + env to run the official harness (command()/env())
    - parse the harness's output into a normalized AdapterResult (parse())
    """

    name: str = ""
    category: str = ""
    description: str = ""

    def __init__(self, cfg: Config, bench_cfg: dict, results_dir: Path):
        self.cfg = cfg
        self.bench_cfg = bench_cfg
        self.results_dir = results_dir
        self.project_root = Path(__file__).resolve().parents[2]

    # -- prerequisites -----------------------------------------------------
    def prereqs(self) -> list[tuple[str, str | None]]:
        """Return [(human_readable_label, executable_to_check_or_None), ...].

        The second element is a binary name probed with shutil.which, or None
        when there is no installable command to check (e.g. hosted-only).
        """
        return []

    def prereqs_satisfied(self) -> bool:
        import shutil

        for _label, binary in self.prereqs():
            if binary and shutil.which(binary) is None:
                return False
        return True

    def extra_preflight_failures(self) -> list[str]:
        """Return adapter-specific dependency failures beyond executables."""
        return []

    # -- execution ---------------------------------------------------------
    @abc.abstractmethod
    def build_command(self, model: str, resolved_model: str) -> list[str]:
        """Return argv for the harness subprocess."""

    def build_env(self, model: str, resolved_model: str) -> dict:
        """Return env vars. Base cfg.env is auto-included by the runner."""
        return {}

    def run_id(self, model: str) -> str:
        import datetime

        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{self.name}-{model}-{ts}"

    # -- result parsing ----------------------------------------------------
    @abc.abstractmethod
    def parse(self, out_dir: Path, log: str) -> AdapterResult:
        """Turn harness output into a normalized result."""

    def make_outdir(self, run_id: str) -> Path:
        d = self.results_dir / self.name / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d


def run_cmd(cmd: list[str], env: dict, cwd: Path | None = None,
            timeout_s: int = 7200, log_path: Path | None = None,
            stream_to=None, cancel_callback=None) -> subprocess.CompletedProcess:
    """Run a harness command, capturing stdout+stderr to a log file.

    The child is launched in its own process group (start_new_session) so that a
    timeout kills the entire group -- including any grandchildren the harness
    spawns -- instead of leaving orphaned processes behind.

    The harness's stdout/stderr are streamed line-by-line to ``stream_to`` (a
    file-like object, defaulting to ``sys.stderr``) in addition to being written
    to ``log_path``. This is what makes the serial run visibly live: an operator
    watching the console sees each benchmark's harness output as it happens,
    not only the post-run ``harness.log``.

    If ``cancel_callback`` is provided it is polled between output lines; when it
    returns truthy the child's process group is killed (SIGKILL) and the call
    raises ``subprocess.TimeoutExpired`` marked with a cancellation reason.
    """
    import os
    import select
    import signal
    import sys
    import time

    full_env = dict(os.environ)
    full_env.update(env)
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    sink = stream_to if stream_to is not None else sys.stderr

    proc = subprocess.Popen(
        cmd,
        env=full_env,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    out_chunks: list[str] = []
    cancelled = False
    timed_out = False
    poller = select.poll()
    assert proc.stdout is not None
    poller.register(proc.stdout, select.POLLIN)
    deadline = None if timeout_s is None else (time.monotonic() + timeout_s)
    try:
        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            # Honor a cooperative cancel even while the child is silent.
            if cancel_callback is not None and cancel_callback():
                cancelled = True
                break
            if remaining is not None and remaining <= 0:
                timed_out = True
                break
            # Wait up to 0.25s for output so the deadline/cancel are checked
            # promptly even when the child produces no output.
            events = poller.poll(250 if remaining is None else min(250, remaining * 1000))
            if not events:
                continue
            line = proc.stdout.readline()
            if not line:
                # EOF: drain whatever remains, then stop.
                rest = proc.stdout.read()
                if rest:
                    out_chunks.append(rest)
                    try:
                        sink.write(rest)
                        sink.flush()
                    except Exception:
                        pass
                break
            out_chunks.append(line)
            try:
                sink.write(line)
                sink.flush()
            except Exception:
                # Sink (e.g. a closed terminal) is best-effort; never let a
                # write failure mask the benchmark's real outcome.
                pass
            if log_path:
                try:
                    with open(log_path, "a") as lf:
                        lf.write(line)
                except Exception:
                    pass
    except subprocess.TimeoutExpired:
        # Should not be raised here (we poll the deadline), but guard anyway.
        timed_out = True
    except Exception:
        timed_out = True

    if cancelled or timed_out:
        # Kill the whole process group so grandchildren are reaped too.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, Exception):
            # Already gone, or pgid unavailable; best-effort cleanup.
            proc.kill()
        try:
            _rest, _ = proc.communicate(timeout=5)
            out_chunks.append(_rest or "")
        except Exception:
            pass

    out = "".join(out_chunks)
    if cancelled:
        if log_path:
            try:
                with open(log_path, "a") as lf:
                    lf.write("\n[CANCELLED]\n")
            except Exception:
                pass
        raise subprocess.TimeoutExpired(cmd, timeout_s, output=out, stderr="")
    if timed_out:
        if log_path:
            try:
                with open(log_path, "a") as lf:
                    lf.write("\n[TIMEOUT]\n")
            except Exception:
                pass
        raise subprocess.TimeoutExpired(cmd, timeout_s, output=out, stderr="")
    if log_path:
        log_path.write_text(out)
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    return subprocess.CompletedProcess(cmd, proc.returncode, out, "")
