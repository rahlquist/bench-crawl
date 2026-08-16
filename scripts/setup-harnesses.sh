#!/usr/bin/env bash
# Install the external harnesses benchsuite drives. Each is opt-in; run the
# lines for the benchmarks you actually use. All are OpenAI-compatible, so the
# same endpoint (config.toml [default].env) serves all of them.
set -euo pipefail

echo "== MMLU (lm-evaluation-harness) =="
# python -m pip install lm_eval   # heavy (torch); or use the provided venv below

echo "== LiveCodeBench (lcb_runner) =="
# python -m pip install livecodebench

echo "== DeepSWE (pier) =="
# uv tool install datacurve-pier
# git clone https://github.com/datacurve-ai/deep-swe

echo "== Terminal-Bench v2 (Harbor) =="
# uv tool install 'harbor[docker]'    # or harbor[modal] for cloud sandboxes
# The terminal-bench dataset is pulled by harbor at run time.

echo "== SWE-bench Pro (Scale) =="
# git clone https://github.com/scaleapi/SWE-bench_Pro-os
# cd SWE-bench_Pro-os && pip install -e . && cd ..

echo "== tau-bench =="
# git clone https://github.com/sierra-research/tau-bench
# cd tau-bench && pip install -r requirements.txt && cd ..

echo "== FoodTruck =="
echo "No local harness (closed source). Submit via results/foodtruck/*.json."

echo
echo "All harnesses are optional. benchsuite check shows what's installed."
