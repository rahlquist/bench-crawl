#!/usr/bin/env bash
# Install benchsuite itself (editable) into a venv. Does NOT install the heavy
# per-benchmark harnesses — see scripts/setup-harnesses.sh for those.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
    echo "creating .venv ..."
    uv venv
fi
echo "installing benchsuite (editable) ..."
uv pip install -e .

echo
echo "done. Run:  . .venv/bin/activate && benchsuite --help"
