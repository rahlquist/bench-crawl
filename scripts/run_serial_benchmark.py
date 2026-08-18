#!/usr/bin/env python3
"""Run exactly one native benchmark at a time on Wimpy."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/home/rahlquist/bench-crawl")
MODEL = "qwen3-8-27b-ud-iq2-m"
BASE = "http://wimpy.home.lan:8080/v1"


def run(name: str, command: list[str], cwd: Path, output: Path, timeout: int = 2400) -> int:
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(json.dumps({
        "benchmark": name,
        "model": MODEL,
        "base_url": BASE,
        "cwd": str(cwd),
        "command": command,
        "timeout_s": timeout,
        "started_at": time.time(),
    }, indent=2))
    env = os.environ.copy()
    env.update({
        "OPENAI_API_KEY": "none",
        "OPENAI_KEY": "none",
        "OPENAI_API_BASE": BASE,
        "OPENAI_BASE_URL": BASE,
        "PYTHONUNBUFFERED": "1",
    })
    with (output / "run.log").open("w") as log:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = 124
    (output / "exit.json").write_text(
        json.dumps({"returncode": rc, "finished_at": time.time()}, indent=2)
    )
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "benchmark",
        choices=["livecodebench", "terminalbench", "taubench", "swebench_pro", "deepswe"],
    )
    ap.add_argument("--task", default="")
    args = ap.parse_args()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = ROOT / "results" / "serial" / f"{args.benchmark}_{MODEL}_{stamp}"

    if args.benchmark == "livecodebench":
        cwd = ROOT / "LiveCodeBench"
        command = [
            sys.executable,
            "-m",
            "lcb_runner.runner.main",
            "--model",
            MODEL,
            "--scenario",
            "codegeneration",
            "--release_version",
            "release_v2",
            "--custom_output_file",
            str(out / "lcb.json"),
            "--evaluate",
            "--n",
            "1",
            "--codegen_n",
            "1",
            "--start_date",
            "2023-05-07",
            "--end_date",
            "2023-05-07",
        ]
    elif args.benchmark == "terminalbench":
        cwd = ROOT
        command = [
            "harbor",
            "run",
            "-d",
            "terminal-bench/terminal-bench@latest",
            "--agent",
            "terminus-2",
            "--model",
            f"openai/{MODEL}",
            "--n-concurrent",
            "1",
            "--jobs-dir",
            str(out),
        ]
        if args.task:
            command += ["--include-task-name", args.task]
        else:
            command += ["--n-tasks", "1"]
    elif args.benchmark == "taubench":
        cwd = ROOT / "tau2-bench"
        command = [
            str(cwd / ".venv-tau2/bin/tau2"),
            "run",
            "--domain",
            "banking_knowledge",
            "--agent-llm",
            f"openai/{MODEL}",
            "--user-llm",
            f"openai/{MODEL}",
            "--agent",
            "llm_agent",
            "--user",
            "user_simulator",
            "--task-ids",
            "task_001",
            "--max-concurrency",
            "1",
            "--save-to",
            str(out / "banking"),
        ]
    elif args.benchmark == "swebench_pro":
        cwd = ROOT / "SWE-bench_Pro-os"
        command = [
            sys.executable,
            str(cwd / "swe_bench_pro_eval.py"),
            "--raw_sample_path",
            str(cwd / "swe_bench_pro_subset.csv"),
            "--patch_path",
            str(out / "patches.json"),
            "--output_dir",
            str(out / "eval"),
            "--dockerhub_username",
            "jefzda",
            "--scripts_dir",
            str(cwd / "run_scripts"),
            "--num_workers",
            "1",
        ]
    else:
        cwd = ROOT
        command = [
            "pier",
            "run",
            "-p",
            str(ROOT / "deep-swe/tasks"),
            "--agent",
            "mini-swe-agent",
            "--model",
            f"openai/{MODEL}",
            "--jobs-dir",
            str(out),
        ]

    timeout = 5400 if args.benchmark == "deepswe" else 2400
    return run(args.benchmark, command, cwd, out, timeout=timeout)


if __name__ == "__main__":
    raise SystemExit(main())
