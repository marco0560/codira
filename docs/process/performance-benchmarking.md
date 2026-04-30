# Performance Benchmarking

Codira performance measurements are developer-facing tooling. They must not
change normal CLI behavior or make timing values part of the test contract.

## Tools

Required system tools:

- `hyperfine` for command-level timing

Python development extras:

- `pyinstrument` for optional profile reports
- `snakeviz` for optional local inspection of `.prof` files

`psutil` and `hyperfine` are treated as system-level tools in this repository,
not Python development dependencies.

## Artifact Layout

Benchmark artifacts are written under:

```text
.artifacts/benchmarks/<run-id>/
```

Saved JSON artifacts include:

- UTC run timestamp
- Codira version
- Git commit ID
- active analyzer/backend plugin inventory
- manifest path when applicable
- availability of `hyperfine`, `pyinstrument`, and `snakeviz`

Profile artifacts are written under:

```text
.artifacts/benchmarks/<run-id>/profiles/
```

Codira index state for campaign commands is isolated from each target
repository and written under:

```text
.artifacts/benchmarks/<run-id>/indexes/<category-label>/
```

The campaign runner passes this directory through `--output-dir` for `index`
and `ctx` commands.

## Manifest Format

The campaign runner expects a JSON manifest:

```json
{
  "repositories": [
    {
      "label": "codira",
      "category": "small",
      "path": "/path/to/codira",
      "query": "schema migration logic",
      "modes": ["cold", "warm", "partial_change"]
    },
    {
      "label": "fontshow",
      "category": "medium",
      "path": "/path/to/fontshow"
    },
    {
      "label": "texlive",
      "category": "large",
      "path": "/path/to/texlive"
    }
  ]
}
```

Each repository entry requires:

- `label`
- `category`
- `path`

Optional fields:

- `query`, defaulting to `schema migration logic`
- `modes`, defaulting to `cold`, `warm`, and `partial_change`

Missing repository paths fail fast before commands are run.

## Campaign Command

Inspect the planned commands without executing:

```bash
python scripts/benchmark_campaign.py benchmarks.json --dry-run
```

Run a campaign:

```bash
python scripts/benchmark_campaign.py benchmarks.json --runs 10 --warmup 2
```

Use a stable run identifier when comparing artifacts:

```bash
python scripts/benchmark_campaign.py benchmarks.json --run-id 20260430-baseline
```

## Plugin Requirements

Benchmark metadata depends on each analyzer and backend exposing stable plugin
identity through the normal Codira plugin registry.

First-party analyzer/backend plugins must provide:

- stable plugin name
- stable provider distribution name
- implementation version
- deterministic discovery globs for analyzers
- deterministic loading status through `codira plugins --json`

The first-party plugin set included in benchmark metadata tests is:

- `codira-analyzer-python`
- `codira-analyzer-json`
- `codira-analyzer-c`
- `codira-analyzer-bash`
- `codira-backend-sqlite`

New first-party analyzer or backend packages must update the shared benchmark
plugin provider list and its tests.

## Validation Policy

Automated tests validate parser behavior, dry-run command construction,
manifest loading, metadata shape, and first-party plugin coverage. They do not
assert exact timing values.

Performance campaigns are manual developer workflows. Normal CI should validate
the scripts without running noisy wall-clock benchmark gates.
