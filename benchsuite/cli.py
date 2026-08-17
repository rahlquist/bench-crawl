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

    # Cooperative cancellation handle, flipped by a SIGINT handler so Ctrl-C
    # requests a cancel between benchmarks. Mirrors SerialWorkflow.cancel:
    # in-flight benchmarks are NOT mid-run interrupted (synchronous design).
    class _CancelHandle:
        def __init__(self):
            self._set = False
        def is_set(self):
            return self._set
        def set(self):
            if not self._set:
                self._set = True
                print("\nCtrl-C received: requesting cancel after the current "
                      "benchmark finishes (in-flight benchmarks are not "
                      "interrupted).", file=sys.stderr)
    cancel = _CancelHandle()
    def _sigint(_signum, _frame):
        cancel.set()
    import signal as _signal
    _old_handler = _signal.signal(_signal.SIGINT, _sigint) if hasattr(_signal, "SIGINT") else None

    from .preflight import preflight, write_preflight
    from .execution_contract import Dependency

    pf = preflight(names, cfg)
    preflight_paths = write_preflight(cfg, pf)
    print(f"preflight: {preflight_paths[1]}")
    if not pf.ok:
        print(f"preflight blocked: {len(pf.blocked)} benchmark(s)")

    # Build the dependency list from the config (benchmarks may declare
    # `after = [...]` prerequisites). These feed DependencyScheduler so a
    # failed/skipped/cancelled prerequisite runtime-blocks its dependents.
    deps = []
    for name in names:
        after = cfg.benchmarks.get(name, {}).get("after")
        if after:
            prereqs = tuple(after) if isinstance(after, (list, tuple)) else (after,)
            deps.append(Dependency(benchmark=name, prerequisites=tuple(prereqs)))

    store_path = cfg.results_dir / "run.json"
    results = core.run_benchmarks(
        names, cfg, pf,
        deps=deps,
        store_path=store_path,
        cancel_handle=cancel,
    )

    if _old_handler is not None:
        try:
            _signal.signal(_signal.SIGINT, _old_handler)
        except Exception:
            pass

    from .report import write_all_reports

    rpath, csv_path = write_all_reports(cfg, results)
    print(f"report: {rpath}")
    print(f"raw:    {cfg.results_dir / 'latest.json'}")
    print(f"csv:    {csv_path}")
    print(f"run snapshot (resume): {store_path}")
    for name in sorted(results):
        r = results[name]
        metric = f" {r.metric_name}={r.metric_value:.4f}" if r.metric_value is not None else ""
        print(f"  {name:20s} {r.status}{metric}")
    if cancel.is_set():
        print("run cancelled; remaining benchmarks were skipped.", file=sys.stderr)
        return 130
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
    from .report import write_all_reports

    rpath, csv_path = write_all_reports(cfg, results)
    print(f"report: {rpath}")
    print(f"csv:    {csv_path}")
    return 0


def cmd_preflight(args) -> int:
    cfg = load_config(args.config)
    names = args.benchmarks or cfg.enabled_benchmarks
    from .preflight import preflight, write_preflight

    report = preflight(names, cfg)
    paths = write_preflight(cfg, report)
    print(f"preflight: {paths[1]}")
    print(f"raw:       {paths[0]}")
    print(f"ready:     {sum(item.status == 'ready' for item in report.benchmarks.values())}")
    print(f"blocked:   {len(report.blocked)}")
    for name, item in report.benchmarks.items():
        suffix = f" — {'; '.join(item.failures)}" if item.failures else ""
        print(f"  {name:20s} {item.status}{suffix}")
    return 0 if report.ok else 1


def cmd_install(args) -> int:
    from .install import build_install_plan, execute_install_plan, format_plan

    plan = build_install_plan()
    if not args.execute:
        print(format_plan(plan))
        return 0
    print("Installing benchmark harnesses and repositories...")
    summary = execute_install_plan(plan, execute=True)
    for name, status in summary.items():
        print(f"  {name:20s} {status}")
    return 0 if all(status in {"installed", "already-present", "skipped"} for status in summary.values()) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="benchsuite",
        description="Run multiple model benchmark harnesses against one OpenAI-compatible endpoint.")
    parser.add_argument("--config", default=None, help="path to config.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list available benchmarks")
    p_preflight = sub.add_parser("preflight", help="validate endpoint and prerequisites without running benchmarks")
    p_preflight.add_argument("benchmarks", nargs="*", help="benchmark names to validate")
    p_install = sub.add_parser("install", help="show or execute installation plan for all benchmarks")
    p_install.add_argument("--all", action="store_true", help="include all benchmark adapters")
    p_install.add_argument("--execute", action="store_true", help="execute the installation plan; default is dry-run")
    p_check = sub.add_parser("check", help="verify endpoint + prerequisites")
    p_check.add_argument("--model", default=None, help="model id to look up")
    p_run = sub.add_parser("run", help="run benchmarks (default: all enabled)")
    p_run.add_argument("benchmarks", nargs="*", help="benchmark names to run")
    sub.add_parser("report", help="regenerate report from last run")

    args = parser.parse_args(argv)
    dispatch = {"list": cmd_list, "check": cmd_check, "preflight": cmd_preflight, "install": cmd_install, "run": cmd_run, "report": cmd_report}
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
