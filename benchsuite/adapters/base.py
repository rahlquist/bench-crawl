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
            timeout_s: int = 7200, log_path: Path | None = None) -> subprocess.CompletedProcess:
    """Run a harness command, capturing stdout+stderr to a log file.

    The child is launched in its own process group (start_new_session) so that a
    timeout kills the entire group -- including any grandchildren the harness
    spawns -- instead of leaving orphaned processes behind.
    """
    import os
    import signal

    full_env = dict(os.environ)
    full_env.update(env)
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        cmd,
        env=full_env,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        # Kill the whole process group so grandchildren are reaped too.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, Exception):
            # Already gone, or pgid unavailable; best-effort cleanup.
            proc.kill()
        try:
            out, err = proc.communicate(timeout=5)
        except Exception:
            out, err = "", ""
    if timed_out:
        if log_path:
            log_path.write_text((out or "") + "\n[TIMEOUT]")
        raise subprocess.TimeoutExpired(cmd, timeout_s, output=out, stderr=err)
    if log_path:
        log_path.write_text((out or "") + "\n--- STDERR ---\n" + (err or ""))
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
