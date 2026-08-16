"""Install plans for the external benchmark harnesses.

The installer is intentionally explicit. It defaults to a dry-run and only
executes when the caller passes --execute.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class InstallItem:
    name: str
    kind: str  # package | tool | repository | hosted
    commands: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    notes: str = ""


def build_install_plan() -> list[InstallItem]:
    return [
        InstallItem(
            "mmlu", "package",
            (("uv", "pip", "install", "lm-eval[api]"),),
            "Installs lm-evaluation-harness with API support.",
        ),
        InstallItem(
            "livecodebench", "repository",
            (
                ("git", "clone", "https://github.com/LiveCodeBench/LiveCodeBench.git", "LiveCodeBench"),
                ("uv", "pip", "install", "-e", "LiveCodeBench"),
            ),
            "The official project is installed from its repository; there is no PyPI package named livecodebench.",
        ),
        InstallItem(
            "deepswe", "tool+repository",
            (
                ("uv", "tool", "install", "datacurve-pier"),
                ("git", "clone", "https://github.com/datacurve-ai/deep-swe", "deep-swe"),
            ),
            "Requires Docker/Harbor-compatible execution for actual runs.",
        ),
        InstallItem(
            "terminalbench", "tool",
            (("uv", "tool", "install", "harbor[docker]"),),
            "Use harbor[modal] instead when running in Modal.",
        ),
        InstallItem(
            "swebench_pro", "repository",
            (("git", "clone", "https://github.com/scaleapi/SWE-bench_Pro-os", "SWE-bench_Pro-os"),),
            "Requires Docker and any benchmark-specific images/data access.",
        ),
        InstallItem(
            "taubench", "repository",
            (("git", "clone", "https://github.com/sierra-research/tau-bench", "tau-bench"),),
            "Installs the repository only; Python dependencies may be required separately.",
        ),
        InstallItem(
            "foodtruck", "hosted", notes="Closed-source hosted benchmark; no local installer exists.",
        ),
    ]


def format_plan(plan: list[InstallItem]) -> str:
    lines = ["Bench Crawl benchmark installation plan (DRY RUN)", ""]
    for item in plan:
        lines.append(f"[{item.name}] {item.kind}")
        if item.commands:
            for command in item.commands:
                lines.append(f"  $ {' '.join(command)}")
        else:
            lines.append("  hosted-only: no local command")
        if item.notes:
            lines.append(f"  note: {item.notes}")
    lines.append("")
    lines.append("No changes made. Re-run with --execute to run these commands.")
    return "\n".join(lines)


def _command_allowed(command: tuple[str, ...], cwd: Path) -> tuple[str, ...]:
    """Skip clone commands when their destination already exists."""
    if len(command) >= 4 and command[:2] == ("git", "clone"):
        destination = cwd / command[-1]
        if destination.exists():
            return ()
    return command


def execute_install_plan(plan: list[InstallItem], execute: bool = False, cwd: Path | None = None) -> dict[str, str]:
    if not execute:
        return {item.name: "dry-run" for item in plan}
    root = cwd or Path.cwd()
    summary: dict[str, str] = {}
    for item in plan:
        if item.kind == "hosted":
            summary[item.name] = "skipped"
            continue
        try:
            commands_run = 0
            for command in item.commands:
                actual = _command_allowed(command, root)
                if not actual:
                    continue
                subprocess.run(actual, cwd=root, check=True)
                commands_run += 1
            summary[item.name] = "installed" if commands_run else "already-present"
        except (OSError, subprocess.CalledProcessError) as exc:
            summary[item.name] = f"failed: {exc}"
    return summary


def install_all(execute: bool = False, cwd: Path | None = None) -> tuple[list[InstallItem], dict[str, str]]:
    plan = build_install_plan()
    return plan, execute_install_plan(plan, execute=execute, cwd=cwd)
