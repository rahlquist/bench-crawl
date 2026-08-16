"""Aggregate benchmark results into a single human-readable report."""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from .adapters.base import AdapterResult


def _metric_cell(r: AdapterResult) -> str:
    if r.metric_name and r.metric_value is not None:
        return f"{r.metric_name}={r.metric_value:.4f}"
    return "-"


def render_markdown(results: dict[str, AdapterResult], model: str, base_url: str) -> str:
    lines = []
    lines.append("# Model Benchmark Suite Report")
    lines.append("")
    lines.append(f"- **Model:** `{model}`")
    lines.append(f"- **Endpoint:** `{base_url}`")
    lines.append(f"- **Generated:** {datetime.datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Benchmark | Category | Status | Metric |")
    lines.append("|---|---|---|---|")
    for name in sorted(results):
        r = results[name]
        lines.append(f"| {name} | {getattr(r, 'category', '') or ''} | {r.status} | {_metric_cell(r)} |")
    lines.append("")
    lines.append("## Detail")
    lines.append("")
    for name in sorted(results):
        r = results[name]
        lines.append(f"### {name} — {r.status}")
        if r.error:
            lines.append(f"**error:** `{r.error}`")
        if r.metric_name and r.metric_value is not None:
            lines.append(f"- **{r.metric_name}:** {r.metric_value:.4f}")
        if r.detail:
            lines.append(f"```json\n{json.dumps(r.detail, indent=2, default=str)}\n```")
        if r.output_dir:
            lines.append(f"- log/output: `{r.output_dir}`")
        lines.append("")
    return "\n".join(lines)


def write_report(cfg, results: dict[str, AdapterResult]) -> Path:
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    md = render_markdown(results, cfg.model, cfg.base_url)
    path = cfg.results_dir / "report.md"
    path.write_text(md)
    return path
