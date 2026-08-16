"""Aggregate benchmark results into a single human-readable report."""
from __future__ import annotations

import csv
import datetime
import json
import re
from pathlib import Path

from .adapters.base import AdapterResult


def _flatten_detail(value, prefix="detail"):
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            out.update(_flatten_detail(child, f"{prefix}_{key}"))
        return out
    if isinstance(value, (list, tuple)):
        return {prefix: json.dumps(value, ensure_ascii=False, default=str)}
    return {prefix: "" if value is None else str(value)}


def _safe_model_name(model: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-._")
    return safe or "unknown-model"


def _categories() -> dict[str, str]:
    try:
        from . import core
        return {name: cls.category for name, cls in core.ADAPTERS.items()}
    except ImportError:
        return {}


def write_csv(cfg, results: dict[str, AdapterResult]) -> Path:
    """Write one detailed CSV row per benchmark, including raw detail JSON."""
    cfg.results_dir.mkdir(parents=True, exist_ok=True)
    categories = _categories()
    rows = []
    for name in sorted(results):
        result = results[name]
        row = {
            "benchmark": name,
            "category": categories.get(name, ""),
            "status": result.status,
            "metric_name": result.metric_name or "",
            "score": "" if result.metric_value is None else str(result.metric_value),
            "error": result.error or "",
            "output_dir": result.output_dir or "",
            "detail_json": json.dumps(result.detail, ensure_ascii=False, default=str),
        }
        row.update(_flatten_detail(result.detail))
        rows.append(row)
    fields = ["benchmark", "category", "status", "metric_name", "score", "error", "output_dir", "detail_json"]
    fields.extend(sorted({key for row in rows for key in row if key.startswith("detail_") and key != "detail_json"}))
    path = cfg.results_dir / f"benchmark-results-{_safe_model_name(cfg.model)}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _metric_cell(r: AdapterResult) -> str:
    if r.metric_name and r.metric_value is not None:
        return f"{r.metric_name}={r.metric_value:.4f}"
    return "-"


def render_markdown(results: dict[str, AdapterResult], model: str, base_url: str) -> str:
    try:
        from . import core
        categories = {name: cls.category for name, cls in core.ADAPTERS.items()}
    except ImportError:
        categories = {}
    lines = []
    lines.append("# Model Benchmark Suite Report")
    lines.append("")
    lines.append(f"- **Model:** `{model}`")
    lines.append(f"- **Endpoint:** `{base_url}`")
    lines.append(f"- **Generated:** {datetime.datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    scored = {name: r for name, r in results.items() if r.metric_name and r.metric_value is not None}
    lines.append("## Ending Results")
    lines.append("")
    lines.append(f"- **Scored benchmarks:** {len(scored)}")
    lines.append(f"- **Completed benchmarks:** {sum(r.status == 'ok' for r in results.values())}")
    lines.append(f"- **Blocked or unavailable:** {sum(r.status in {'blocked', 'not_run', 'failed'} for r in results.values())}")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Benchmark | Category | Status | Score metric | Score | Notes |")
    lines.append("|---|---|---|---|---:|---|")
    for name in sorted(results):
        r = results[name]
        score = f"{r.metric_value:.4f}" if r.metric_value is not None else "-"
        notes = r.error or ("score produced" if r.metric_value is not None else "no score produced")
        category = categories.get(name, getattr(r, "category", "")) or ""
        lines.append(f"| {name} | {category} | {r.status} | {r.metric_name or '-'} | {score} | {notes} |")
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


def write_all_reports(cfg, results: dict[str, AdapterResult]) -> tuple[Path, Path]:
    return write_report(cfg, results), write_csv(cfg, results)
