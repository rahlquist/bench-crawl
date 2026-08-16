# Bench Crawl

Bench Crawl is a stand-alone orchestrator for evaluating language models and agents across heterogeneous benchmarks through a common OpenAI-compatible endpoint.

It does **not** replace the official benchmark implementations. It provides one CLI, one configuration surface, consistent run directories, captured logs, and a normalized report.

> **Status:** early-stage evaluation infrastructure. Benchmark harnesses, datasets, containers, and hosted services remain separate dependencies.

## Included benchmarks

| Adapter | Capability | Official runner | Local execution |
|---|---|---|---|
| `mmlu` | General knowledge and reasoning | [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness) | API endpoint |
| `livecodebench` | Contamination-resistant code generation | [LiveCodeBench](https://github.com/livecodebench/livecodebench) | API endpoint |
| `deepswe` | Long-horizon software engineering | [DeepSWE / Pier](https://github.com/datacurve-ai/deep-swe) | Sandboxed agent |
| `terminalbench` | Terminal-based agent work | [Harbor / Terminal-Bench](https://github.com/harbor-framework/terminal-bench) | Docker or Modal |
| `swebench_pro` | Professional repository issue resolution | [SWE-bench Pro](https://github.com/scaleapi/SWE-bench_Pro-os) | Docker-based |
| `taubench` | Tool-agent-user interaction | [τ-bench](https://github.com/sierra-research/tau-bench) | Local simulation |
| `foodtruck` | Sequential business decisions | [FoodTruck Bench](https://foodtruckbench.com/) | Hosted submission only |

The metrics remain separate. Bench Crawl intentionally does not invent a universal aggregate score for benchmarks that measure different capabilities.

## Why this project exists

These evaluations are fundamentally different:

- MMLU is multiple-choice log-likelihood evaluation.
- LiveCodeBench evaluates executable code-generation solutions.
- DeepSWE, SWE-bench Pro, and Terminal-Bench evaluate agents modifying code or operating terminals.
- τ-bench evaluates stateful tool use with a user simulator.
- FoodTruck evaluates sequential business decisions over a 30-day simulation.

Bench Crawl connects the official runners to one endpoint and produces a consistent operational record without pretending that the underlying tasks are equivalent.

## Requirements

- Linux or macOS recommended.
- Python 3.11+.
- [uv](https://docs.astral.sh/uv/) recommended.
- An OpenAI-compatible endpoint: llama.cpp/llama-swap, vLLM, or a compatible hosted gateway.
- Docker and/or Modal for sandboxed benchmarks.
- The individual harness dependencies for the benchmarks you intend to run.

## Installation

```bash
git clone https://github.com/rahlquist/bench-crawl.git
cd bench-crawl
./scripts/setup.sh
source .venv/bin/activate
benchsuite list
```

The base installation is deliberately small. It does not install every external harness, because those dependencies are large and often platform-specific.

See the documented commands in:

```bash
./scripts/setup-harnesses.sh
```

## Configuration

Copy the public example and edit it:

```bash
cp config.example.toml config.toml
$EDITOR config.toml
```

Minimal configuration:

```toml
[default]
base_url = "http://localhost:8080/v1"
api_key = ""
model = "your-model-id"
timeout_s = 7200
results_dir = "results"

[default.env]
OPENAI_API_KEY = ""
OPENAI_BASE_URL = "http://localhost:8080/v1"
OPENAI_API_BASE = "http://localhost:8080/v1"

[benchmarks.mmlu]
enabled = true
num_fewshot = 5
subset = ""
batch_size = 1
tokenizer = "matching/huggingface-tokenizer"
```

`config.toml` is ignored by Git. It is intended for machine-specific endpoints and settings.

Connection settings can also be overridden for one invocation or one shell:

```bash
BENCHSUITE_BASE_URL=http://localhost:8080/v1 \
BENCHSUITE_MODEL=your-model-id \
benchsuite check
```

Supported overrides:

| Variable | Purpose |
|---|---|
| `BENCHSUITE_BASE_URL` | OpenAI-compatible base URL |
| `BENCHSUITE_MODEL` | Model identifier exposed by the endpoint |
| `BENCHSUITE_API_KEY` | Optional API key |

## Usage

```bash
benchsuite list
benchsuite check
benchsuite run mmlu
benchsuite run mmlu livecodebench
benchsuite run
benchsuite report
```

`benchsuite run` with no benchmark names runs adapters whose configuration has `enabled = true`. Explicit benchmark names are honored even if their config has `enabled = false`.

Use another configuration file with the global option:

```bash
benchsuite --config /path/to/config.toml check
benchsuite --config /path/to/config.toml run mmlu
```

## Outputs

```text
results/
├── latest.json
├── report.md
├── mmlu/<run-id>/harness.log
├── livecodebench/<run-id>/harness.log
└── ...
```

- `latest.json`: normalized machine-readable results.
- `report.md`: human-readable summary.
- `benchmark-results-<model>.csv`: one detailed row per benchmark, named with the model identifier.
- `<benchmark>/<run-id>/harness.log`: combined stdout and stderr.
- Official harness output remains alongside the relevant run when the harness supports it.

Generated results are excluded from Git.

The CSV contains stable benchmark/status/metric/score/error fields, flattened scalar fields from each adapter's detail payload, and the complete nested `detail_json` payload. It is generated after `benchsuite run` and by `benchsuite report`.

## Benchmark notes

### MMLU

MMLU requires log-likelihood scoring, so the adapter uses lm-eval's `local-completions` model rather than chat completions. The evaluator also needs a compatible tokenizer to calculate request lengths:

```toml
[benchmarks.mmlu]
enabled = true
tasks = "mmlu_abstract_algebra"
num_fewshot = 0
subset = "mmlu_abstract_algebra"
limit = 1
tokenizer = "matching/huggingface-tokenizer"
```

Set the tokenizer to a compatible Hugging Face tokenizer for the served model. The endpoint must expose a functional `/v1/completions` API.

### LiveCodeBench

The adapter invokes the official `lcb_runner` and supports a pinned release such as `release_v2`. Keep the release fixed for comparisons.

### DeepSWE

DeepSWE uses Pier and Harbor-compatible task directories. Clone the benchmark separately and set `tasks_dir`. The agent works in isolated environments and the verifier artifacts determine the result.

### Terminal-Bench

Terminal-Bench is driven through Harbor. Harbor execution may use Docker or Modal depending on the installed environment and command-line version.

### SWE-bench Pro

SWE-bench Pro requires its repository, evaluation scripts, Docker, and benchmark-specific images/data. Public, held-out, and commercial subsets have different access conditions.

### τ-bench Banking

The τ-bench adapter invokes `run.py` with `env = "banking"`, the OpenAI provider, and the configured endpoint.

### FoodTruck Bench

FoodTruck Bench is not locally executable. Its methodology states that the simulation engine, system prompt, and demand model are closed source. The adapter therefore creates a submission bundle under `results/foodtruck/` and reports `hosted_submission_required`; it cannot produce an official local score.

## Architecture

```text
config.toml
    │
    ▼
benchsuite CLI
    │
    ├── endpoint discovery and model resolution
    ├── adapter registry
    ├── official harness subprocess
    ├── run logs and artifacts
    └── normalized JSON + Markdown report
```

An adapter extends `BenchmarkAdapter` and implements:

- `prereqs()` — external requirements shown by `benchsuite check`;
- `build_command()` — official harness command;
- `build_env()` — endpoint/provider environment variables;
- `parse()` — official output to normalized `AdapterResult`.

Register new adapters in `benchsuite/adapters/__init__.py`.

## Development

```bash
uv venv
uv pip install -e .
.venv/bin/python -m compileall -q benchsuite
.venv/bin/benchsuite list
.venv/bin/benchsuite check
git diff --check
```

The GitHub Actions workflow performs source-level validation without requiring model access, benchmark datasets, or external sandboxes.

## Reproducibility

For meaningful comparisons:

- Pin benchmark and harness versions.
- Record model ID, quantization, server version, sampling parameters, and hardware.
- Keep endpoint settings constant where the benchmark permits it.
- Separate infrastructure failures from model failures.
- Preserve raw logs and official result artifacts.
- Do not compare scores from different benchmark releases as if they were identical.
- Follow each benchmark's license, data-use terms, and submission rules.

## Security and privacy

Never commit API keys, endpoint credentials, private dataset paths, model weights, or raw logs containing sensitive prompts. The repository ignores local configuration, results, benchmark checkouts, virtual environments, and model artifacts.

Sanitize endpoint hostnames and private paths before publishing result reports.

## Roadmap

- Versioned result schemas per adapter.
- Mocked parser tests for every adapter.
- Resource-aware parallel scheduling.
- Benchmark and harness version manifests.
- Rich HTML reports and comparison charts.
- Retry and infrastructure-failure classification.
- Hosted-result import for FoodTruck submissions.

## License

Bench Crawl is released under the MIT License. The individual benchmarks and harnesses retain their own licenses and attribution requirements. Bench Crawl does not redistribute their datasets.

## Attribution

Bench Crawl is an independent orchestration project. Benchmark names and project names belong to their respective authors and maintainers.

## Contributing

Pull requests should include focused changes, documentation updates, and reproducible validation. Do not include benchmark data, model weights, credentials, or private endpoint details.

For bug reports, include the sanitized command, benchmark name, harness version, Python version, operating system, and relevant log excerpt.

## Initial release contents

```text
README.md
LICENSE
pyproject.toml
config.example.toml
benchsuite/
scripts/
.github/workflows/ci.yml
.env.example
.gitignore
```

Start small: install, configure one model, run one smoke task, inspect the raw output, then scale to the full suite.

Bench Crawl is deliberately a thin operational layer. The official benchmark harness remains the authority for task execution and scoring.

## Citation

If you use Bench Crawl in research or published comparisons, record the repository commit, configuration, model/server details, benchmark versions, execution environment, raw artifacts, and infrastructure failures.

```text
Bench Crawl: a unified orchestrator for heterogeneous language-model benchmarks.
https://github.com/rahlquist/bench-crawl
```

## Contact

Use the repository issue tracker for reproducible bugs and documentation improvements. Never include credentials or private benchmark data in an issue.

## End-to-end example

```bash
./scripts/setup.sh
cp config.example.toml config.toml
# Edit config.toml with the endpoint and model.
source .venv/bin/activate
benchsuite check
benchsuite run mmlu
less results/report.md
```

## Stable CLI surface

```text
benchsuite list
benchsuite check
benchsuite run [benchmark ...]
benchsuite report
```

The public repository should remain source-only: datasets, model files, generated reports, and local environment files belong outside Git.

## Maintainer checklist

- Keep adapter claims aligned with the actual official harness interfaces.
- Document tested harness versions when changing commands.
- Never commit local endpoint details.
- Never fabricate or manually edit benchmark scores.
- Keep external benchmark attribution current.

Bench Crawl makes heterogeneous model benchmarking repeatable without pretending the benchmarks measure the same thing.

## Appendix: terminology

- **Adapter:** Bench Crawl code invoking and parsing one official harness.
- **Harness:** The benchmark's own runner and evaluator.
- **Endpoint:** An OpenAI-compatible model server.
- **Run artifact:** Logs and outputs from one execution.
- **Hosted-only:** A benchmark that cannot be reproduced locally from public components.

## Appendix: expected excluded files

```text
config.toml
results/
.venv/
benchmark checkouts
model files
credentials
```

## Appendix: result contract

A successful adapter run should leave a run directory, a combined log, the official result artifact, a normalized entry in `latest.json`, and a row in `report.md`. Hosted-only adapters must state their limitation explicitly.

## Final note

Scores are not interchangeable. Bench Crawl keeps them separate on purpose.

Thank you for using Bench Crawl.
