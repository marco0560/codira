# Local corpus benchmark recovery

Both analyzer-style and local stress suites use the tracked developer launcher
`scripts/run_test_material_benchmarks.py`. It accepts their existing local manifest
schema. Local manifests and corpus checkouts remain untracked; no corpus is
indexed without `--run`. Run commands from the isolated fixes checkout with its
own `uv` environment. Corpus revisions, local model assets and Graphviz must
already be available; execution is offline. Prepared configurations preserve
original model paths and documentation routes.

A failed source does not discard successful structural indexing. A usable
partial index supports structural symbol, reference, graph and audit reads.
Their receipts carry `index_coverage`, `comparison_group=partial_coverage`, and
sample `partial_timing_valid`; `timing_valid` stays false for complete-index
comparisons. Index failures retain their failed paths, reasons, original stdout,
stderr and each attempt receipt. Unusable indexes exclude dependent stages.
Failed embedding population excludes embedding-dependent queries while structural
queries continue. An embeddings-only pass does not retry structural failures.

Partial sources are not automatically excluded or repeatedly retried. Incremental
and scheduler index probes are withheld after deterministic analysis failure.
Stress family reads request partial coverage explicitly; strict family validation
and reindex probes are withheld when a member is partial. Foreground daemon
reconciliation reuses unchanged failure snapshots. Graphviz render timeouts apply
to both suites and terminate only the launcher's owned process groups.

`summary.json` separates complete-index and partial-coverage cohorts. Partial
stages do not appear as command failures. `execution_complete` means the launcher
finished; `complete` and `coverage_complete` stay false if coverage is partial or
required stages were excluded. Exit 1 indicates a command failure; exit 2
indicates usable partial coverage. Read the stage receipts and exclusions before
interpreting any timing. Successful operational execution is not a semantic
retrieval-quality grade.

## New plan after runner or runtime changes

Changes to runner, runtime, manifest, configuration or timeout controls require a
new immutable identity. Existing `--resume` is allowed only if their digests match.
Do not copy completed stages from another identity. From the isolated checkout,
set these named placeholders to existing inputs and a fresh durable destination:

```bash
SOURCE_CHECKOUT=/path/to/original/codira
ORIGINAL_RUN=/path/to/original/run
PLAN_DIR="$PWD/.artifacts/benchmarks/test-material/recovery-analyzer-style-r1"
uv run python scripts/run_test_material_benchmarks.py "$SOURCE_CHECKOUT/benchmarks/performance/test-material-20261010/analyzer-style.local.json" --prepare-recovery "$ORIGINAL_RUN" --recovery-dir "$PLAN_DIR"
uv run python scripts/run_test_material_benchmarks.py "$PLAN_DIR/manifest.json"
uv run python scripts/run_test_material_benchmarks.py "$PLAN_DIR/manifest.json" --run --run-id analyzer-style-recovery-r1
```

The first two commands only prepare and validate. Preparation copies configuration,
failure receipts and retained raw outputs, links their digests to the original
identity, selects this checkout's runtime and a new artifact root, and refuses
existing destination directories. The original run remains intact. Use a finished
or operator-paused original run to freeze a coherent evidence snapshot. Recovery
runs rebuild their own indexes once; they do not resume the older runtime's index.

## Explicit fixture exclusion

An operator may intentionally narrow the source scope. Prepare a different plan,
with a repository label, analyzer name and exact repo-relative path:

```bash
EXCLUSION_PLAN_DIR="$PWD/.artifacts/benchmarks/test-material/recovery-excluded-r1"
uv run python scripts/run_test_material_benchmarks.py "$SOURCE_CHECKOUT/benchmarks/performance/test-material-20261010/analyzer-style.local.json" --prepare-recovery "$ORIGINAL_RUN" --recovery-dir "$EXCLUSION_PLAN_DIR" --exclude-file cpp-llvm-project:python:llvm/utils/lit/tests/shtest-encoding.py
uv run python scripts/run_test_material_benchmarks.py "$EXCLUSION_PLAN_DIR/manifest.json" --run --run-id analyzer-style-excluded-r1
```

This adds only the selected analyzer's `exclude_paths`, retaining prior filters.
It records the exclusion and original failures in recovery provenance. It does
not repair the fixture, suppress other coverage gaps, or make an excluded scope
comparable to the original full corpus. For source corrections, use a new pinned
corpus revision and manifest identity with a link to the retained original run;
never edit a running corpus checkout or silently alter the original pinned revision.

## Stress preparation and resume

For a stress suite without an existing run, clone its plan without exclusions:

```bash
STRESS_PLAN_DIR="$PWD/.artifacts/benchmarks/test-material/stress-fixed-r1"
uv run python scripts/run_test_material_benchmarks.py "$SOURCE_CHECKOUT/benchmarks/performance/test-material-20261010/local-stress.local.json" --prepare-plan --recovery-dir "$STRESS_PLAN_DIR"
uv run python scripts/run_test_material_benchmarks.py "$STRESS_PLAN_DIR/manifest.json" --run --run-id stress-fixed-r1
```

If stress already has evidence, use `--prepare-recovery STRESS_ORIGINAL_RUN` instead
of `--prepare-plan`; exclusion recovery uses the same options in either suite.
Use Ctrl-C to interrupt an operator-run launcher: it retains an interrupted attempt
and stops only its own descendants. Resume with the identical original command
and `--resume`:

```bash
uv run python scripts/run_test_material_benchmarks.py "$PLAN_DIR/manifest.json" --run --run-id analyzer-style-recovery-r1 --resume
```

Interrupted stages resume automatically. Completed partial stages retain their
partial classifications even with `--retry-failed`; unchanged deterministic source
failures are not retried by that flag. Failed command stages can be explicitly
retried with `--resume --retry-failed`, retaining prior attempts. Exclusion changes
always require another prepared plan and run identity.
