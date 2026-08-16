"""Configuration loading for benchsuite."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    base_url: str
    api_key: str
    model: str
    timeout_s: int
    results_dir: Path
    env: dict = field(default_factory=dict)
    benchmarks: dict = field(default_factory=dict)

    @property
    def enabled_benchmarks(self) -> list[str]:
        return [k for k, v in self.benchmarks.items() if v.get("enabled", True)]


def _resolve_project_root() -> Path:
    # config.toml sits at the repo root, one level above the benchsuite package.
    here = Path(__file__).resolve().parent
    return here.parent


def load_config(path: str | os.PathLike | None = None) -> Config:
    root = Path(path).resolve() if path else _resolve_project_root()
    cfg_path = Path(path) if path else root / "config.toml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"config not found: {cfg_path}")

    with open(cfg_path, "rb") as fh:
        data = tomllib.load(fh)

    default = data.get("default", {})
    env = dict(default.get("env", {}))
    benchmarks = data.get("benchmarks", {})

    # Overlay explicit api_key / base_url / model from the environment if set.
    env_key = os.environ.get("BENCHSUITE_API_KEY")
    env_base = os.environ.get("BENCHSUITE_BASE_URL")
    env_model = os.environ.get("BENCHSUITE_MODEL")

    api_key = env_key if env_key is not None else default.get("api_key", "")
    base_url = env_base if env_base is not None else default.get("base_url", "")
    model = env_model if env_model is not None else default.get("model", "")

    return Config(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_s=int(default.get("timeout_s", 7200)),
        results_dir=root / default.get("results_dir", "results"),
        env=env,
        benchmarks=benchmarks,
    )


def model_for_benchmark(cfg: Config, bench_cfg: dict) -> str:
    """Per-benchmark model override, else the default."""
    return bench_cfg.get("model") or cfg.model
