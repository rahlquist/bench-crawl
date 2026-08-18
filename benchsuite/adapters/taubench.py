"""τ²-bench banking via the official ``tau2`` CLI."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .base import AdapterResult, BenchmarkAdapter


class TauBenchAdapter(BenchmarkAdapter):
    name = "taubench"
    category = "tool-use"
    description = "Official τ²-bench tool-agent-user interaction (banking)"

    def prereqs(self) -> list[tuple[str, str | None]]:
        return [
            (f"tau2-bench checkout at {self.bench_cfg.get('repo', 'tau2-bench')}", None),
            ("official tau2 CLI", None),
        ]

    def build_env(self, model: str, resolved_model: str) -> dict:
        # tau-bench uses the OpenAI provider; point it at our endpoint.
        return {
            "OPENAI_API_BASE": self.cfg.base_url,
            "OPENAI_BASE_URL": self.cfg.base_url,
            "OPENAI_API_KEY": self.cfg.api_key or "none",
        }

    @property
    def run_cwd(self) -> Path:
        configured_repo = Path(self.bench_cfg.get("repo", "tau2-bench"))
        return configured_repo if configured_repo.is_absolute() else self.project_root / configured_repo

    def extra_preflight_failures(self) -> list[str]:
        configured_repo = Path(self.bench_cfg.get("repo", "tau2-bench"))
        repo = configured_repo if configured_repo.is_absolute() else self.project_root / configured_repo
        failures = []
        if not repo.is_dir():
            failures.append(f"repository not found: {repo}")
        if self._tau2_executable(repo) is None:
            failures.append(
                "official tau2 CLI not found; run `uv sync` in the tau2-bench checkout"
            )
        return failures

    @staticmethod
    def _tau2_executable(repo: Path) -> Path | None:
        for candidate in (
            repo / ".venv-tau2" / "bin" / "tau2",
            repo / ".venv" / "bin" / "tau2",
        ):
            if candidate.is_file():
                return candidate
        return None

    def _save_to(self, resolved_model: str) -> str:
        configured = self.bench_cfg.get("save_to")
        if configured:
            return str(configured)
        safe_model = re.sub(r"[^A-Za-z0-9._-]+", "-", resolved_model).strip("-._")
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        return f"benchsuite_{safe_model}_{stamp}"

    def build_command(self, model: str, resolved_model: str) -> list[str]:
        configured_repo = Path(self.bench_cfg.get("repo", "tau2-bench"))
        repo = configured_repo if configured_repo.is_absolute() else self.project_root / configured_repo
        executable = self._tau2_executable(repo)
        if executable is None:
            # Let the command fail with a precise executable error if build_command
            # is called before preflight; preflight reports the actionable cause.
            executable = repo / ".venv" / "bin" / "tau2"

        env_name = self.bench_cfg.get("env", "banking_knowledge")
        retrieval = self.bench_cfg.get("retrieval_config", "golden_retrieval")
        self._active_save_to = self._save_to(resolved_model)
        cmd = [
            str(executable),
            "run",
            "--domain", env_name,
            "--retrieval-config", retrieval,
            "--agent-llm", f"openai/{resolved_model}",
            "--user-llm", f"openai/{resolved_model}",
            "--agent", self.bench_cfg.get("agent_strategy", "llm_agent"),
            "--user", self.bench_cfg.get("user_strategy", "user_simulator"),
            "--max-concurrency", str(self.bench_cfg.get("max_concurrency", 1)),
            "--max-retries", str(self.bench_cfg.get("max_retries", 0)),
            "--timeout", str(self.bench_cfg.get("task_timeout", self.cfg.timeout_s)),
            "--verbose-logs",
            "--save-to", self._active_save_to,
        ]
        task_ids = self.bench_cfg.get("task_ids", [])
        if task_ids:
            cmd += ["--task-ids", *[str(task_id) for task_id in task_ids]]
        elif self.bench_cfg.get("num_tasks"):
            cmd += ["--num-tasks", str(self.bench_cfg["num_tasks"])]
        return cmd

    def parse(self, out_dir: Path, log: str) -> AdapterResult:
        configured_repo = Path(self.bench_cfg.get("repo", "tau2-bench"))
        repo = configured_repo if configured_repo.is_absolute() else self.project_root / configured_repo
        save_to = getattr(self, "_active_save_to", self.bench_cfg.get("save_to", ""))
        target = repo / "data" / "simulations" / str(save_to) / "results.json"
        if not target.exists():
            return AdapterResult(
                benchmark=self.name,
                status="failed",
                error=f"no official tau2 results.json at {target}",
                detail={"log_tail": log[-2000:]},
            )

        detail = json.loads(target.read_text())
        simulations = detail.get("simulations") or []
        if not simulations:
            return AdapterResult(
                benchmark=self.name,
                status="failed",
                error="official tau2 produced no simulations",
                detail=detail,
            )
        infra = []
        for simulation in simulations:
            info = simulation.get("info") or {}
            if simulation.get("termination_reason") == "infrastructure_error" or info.get("error"):
                infra.append(info.get("error") or simulation.get("termination_reason"))
        if infra:
            return AdapterResult(
                benchmark=self.name,
                status="failed",
                error="official tau2 simulation infrastructure error",
                detail={"errors": infra, "results": detail},
            )
        rewards = [
            simulation.get("reward_info", {}).get("reward")
            for simulation in simulations
            if simulation.get("reward_info") is not None
        ]
        if len(rewards) != len(simulations):
            return AdapterResult(
                benchmark=self.name,
                status="failed",
                error="official tau2 simulation has no reward result",
                detail=detail,
            )
        return AdapterResult(
            benchmark=self.name,
            status="ok",
            metric_name="average_reward",
            metric_value=sum(float(reward) for reward in rewards) / len(rewards),
            detail=detail,
        )
