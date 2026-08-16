"""Pre-execution validation for a Bench Crawl run."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import Config
from .endpoint import EndpointStatus, check_endpoint


@dataclass
class PreflightBenchmark:
    benchmark: str
    status: str  # ready | blocked
    prerequisites: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


@dataclass
class PreflightReport:
    ok: bool
    model: str
    base_url: str
    endpoint_status: str
    endpoint_error: str | None
    resolved_model: str | None
    benchmarks: dict[str, PreflightBenchmark]

    @property
    def blocked(self) -> list[str]:
        return [name for name, item in self.benchmarks.items() if item.status == "blocked"]

    def to_dict(self) -> dict:
        return asdict(self)


def _benchmark_preflight(name: str, cfg: Config) -> PreflightBenchmark:
    from . import core

    if name not in core.ADAPTERS:
        return PreflightBenchmark(name, "blocked", failures=["unknown benchmark adapter"])
    adapter = core.ADAPTERS[name](cfg, cfg.benchmarks.get(name, {}), cfg.results_dir)
    prerequisites: list[str] = []
    failures: list[str] = []
    for label, binary in adapter.prereqs():
        if binary and shutil.which(binary) is None:
            failures.append(f"missing executable: {binary}")
            prerequisites.append(f"{label} [MISSING]")
        else:
            prerequisites.append(label)
    extra_failures = adapter.extra_preflight_failures()
    failures.extend(extra_failures)
    prerequisites.extend(extra_failures)
    return PreflightBenchmark(
        benchmark=name,
        status="ready" if not failures else "blocked",
        prerequisites=prerequisites,
        failures=failures,
    )


def preflight(names: list[str], cfg: Config) -> PreflightReport:
    endpoint: EndpointStatus = check_endpoint(cfg.base_url, cfg.api_key)
    resolved = cfg.model if not endpoint.reachable else None
    if endpoint.reachable:
        hits = [mid for mid in endpoint.model_ids if cfg.model == mid or cfg.model in mid]
        resolved = hits[0] if hits else None
    endpoint_failures: list[str] = []
    if not endpoint.reachable:
        endpoint_failures.append(endpoint.error or "endpoint unreachable")
    elif not resolved:
        endpoint_failures.append(f"model not exposed by endpoint: {cfg.model}")

    items = {name: _benchmark_preflight(name, cfg) for name in names}
    if endpoint_failures:
        for item in items.values():
            item.status = "blocked"
            item.failures = endpoint_failures + item.failures

    return PreflightReport(
        ok=not endpoint_failures and all(item.status == "ready" for item in items.values()),
        model=cfg.model,
        base_url=cfg.base_url,
        endpoint_status="ready" if endpoint.reachable else "blocked",
        endpoint_error="; ".join(endpoint_failures) or None,
        resolved_model=resolved,
        benchmarks=items,
    )


def write_preflight(cfg: Config, report: PreflightReport) -> tuple[Path, Path]:
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    json_path = cfg.results_dir / "preflight.json"
    md_path = cfg.results_dir / "preflight.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2))

    lines = ["# Bench Crawl Pre-Flight Report", "", f"- **Model:** `{report.model}`",
             f"- **Endpoint:** `{report.base_url}`",
             f"- **Endpoint status:** `{report.endpoint_status}`",
             f"- **Resolved model:** `{report.resolved_model or 'none'}`", ""]
    if report.endpoint_error:
        lines += [f"**Endpoint failure:** `{report.endpoint_error}`", ""]
    lines += ["| Benchmark | Status | Prerequisites | Failures |", "|---|---|---|---|"]
    for name, item in report.benchmarks.items():
        lines.append(f"| {name} | {item.status} | {'; '.join(item.prerequisites) or '-'} | {'; '.join(item.failures) or '-'} |")
    lines += ["", f"**Ready:** {sum(i.status == 'ready' for i in report.benchmarks.values())}",
              f"**Blocked:** {len(report.blocked)}", ""]
    md_path.write_text("\n".join(lines))
    return json_path, md_path
