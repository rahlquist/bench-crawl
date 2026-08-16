"""benchsuite CLI entrypoint."""
from __future__ import annotations

import argparse
import json
import shutil
import sys

from . import core
from .config import load_config
from .endpoint import check_endpoint


def _which(binary: str) -> str | None:
    return shutil.which(binary)


def cmd_list(_args) -> int:
    for name in core.list_adapters():
        cls = core.ADAPTERS[name]
        print(f"{name:20s} [{cls.category}]  {cls.description}")
    return 0


def cmd_check(args) -> int:
    cfg = load_config(args.config)
    st = check_endpoint(cfg.base_url, cfg.api_key)
    if not st.reachable:
        print(f"ENDPOINT UNREACHABLE: {cfg.base_url}")
        print(f"  error: {st.error}")
        return 1
    print(f"endpoint OK: {cfg.base_url} ({len(st.model_ids)} models exposed)")
    want = args.model or cfg.model
    if want:
        hits = [m for m in st.model_ids if want in m]
        if hits:
            print(f"  configured model '{want}' -> {hits}")
        else:
            print(f"  WARNING: configured model '{want}' not found on endpoint")
    # prerequisites
    print("\nprerequisites:")
    for name in core.list_adapters():
        cls = core.ADAPTERS[name]
        ad = cls(cfg, cfg.benchmarks.get(name, {}), cfg.results_dir)
        pr = ad.prereqs()
        ok = ad.prereqs_satisfied()
        # mark missing binaries
        labels = []
        for label, binary in pr:
            if binary and _which(binary) is None:
                labels.append(f"{label} [MISSING]")
            else:
                labels.append(label)
        status = "OK" if ok else "MISSING"
        print(f"  [{status:7s}] {name:20s} {'; '.join(labels) if labels else 'no external deps'}")
    return 0


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    names = args.benchmarks or cfg.enabled_benchmarks
    # Explicit names are honored; the default run uses only enabled entries.
    if args.benchmarks:
        for name in names:
            if name not in core.ADAPTERS:
                print(f"unknown benchmark: {name}", file=sys.stderr)
                return 2
    results = core.run_benchmarks(names, cfg)
    from .report import write_report

    rpath = write_report(cfg, results)
    print(f"report: {rpath}")
    print(f"raw:    {cfg.results_dir / 'latest.json'}")
    for name in sorted(results):
        r = results[name]
        metric = f" {r.metric_name}={r.metric_value:.4f}" if r.metric_value is not None else ""
        print(f"  {name:20s} {r.status}{metric}")
    return 0


def cmd_report(args) -> int:
    cfg = load_config(args.config)
    raw = cfg.results_dir / "latest.json"
    if not raw.exists():
        print(f"no results found at {raw}; run `benchsuite run` first")
        return 1
    data = json.loads(raw.read_text())
    from .adapters.base import AdapterResult

    results = {k: AdapterResult(**v) for k, v in data["benchmarks"].items()}
    from .report import write_report

    rpath = write_report(cfg, results)
    print(f"report: {rpath}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="benchsuite",
        description="Run multiple model benchmark harnesses against one OpenAI-compatible endpoint.")
    parser.add_argument("--config", default=None, help="path to config.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list available benchmarks")
    p_check = sub.add_parser("check", help="verify endpoint + prerequisites")
    p_check.add_argument("--model", default=None, help="model id to look up")
    p_run = sub.add_parser("run", help="run benchmarks (default: all enabled)")
    p_run.add_argument("benchmarks", nargs="*", help="benchmark names to run")
    sub.add_parser("report", help="regenerate report from last run")

    args = parser.parse_args(argv)
    dispatch = {"list": cmd_list, "check": cmd_check, "run": cmd_run, "report": cmd_report}
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
