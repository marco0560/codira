# Local corpus benchmark recovery

Both analyzer-style and local stress suites use the tracked developer launcher
`scripts/run_test_material_benchmarks.py`. It accepts their existing local manifest
schema. Local manifests and corpus checkouts remain untracked; no corpus is
indexed without `--run`. Run commands from the isolated fixes checkout with its
own `uv` environment. Corpus revisions, local model assets and Graphviz must
already be available; execution is offline. Prepared configurations preserve
original model paths and documentation routes.

Stage outcomes are prefixed with the current test number and planned tests still
to run, followed by the local date/time and UTC offset, for example
`[17; 342; 2026-10-12 14:30:45+02:00] sqlite-structural/python-django/arch passed`.
The timestamp is captured when each stage outcome is printed.
One test means one stage measurement, including all its repeated samples; a stress
MCP probe groups its tool calls into one stage. Numbers restart at one for each
launch and resume counts exclude retained checkpoints. The remaining count excludes
the displayed test and shrinks as missing prerequisites or symbol discoveries
remove conditional tests. Exclusions use `[skip; N; date time+offset]` and do not advance
the test number. Both local suites use this same progress output. Terminal descriptions retain the
machine status and explain it, for example `partial (failed files=0; coverage
incomplete)` or `partial_empty (no matches; failed files=1; coverage incomplete)`.
These are coverage labels, not command errors. Known coverage counts describe
reported scope; unknown counts are omitted. Failures show a compact retained
cause, and optional SVG omissions are reported separately.

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
Coverage gaps from unsupported files or parser recovery remain partial-coverage
measurements, but do not suppress these index probes when no source attempt failed.
Stress family reads request partial coverage explicitly; strict family validation
and reindex probes are withheld when a member is partial. Foreground daemon
reconciliation reuses unchanged failure snapshots. Both suites pass an explicit
`--svg-timeout-seconds` (default 180) to Codira. The independent runner
`--architecture-timeout-seconds` (default 300) bounds the whole architecture
command. Zero disables the corresponding limit only; an outer deadline may
interrupt rendering sooner. Both values appear in plan/provenance and participate
in resume identity. Outer timeouts terminate only the launcher's owned process
groups. Per-sample renderer manifests retain optional SVG omissions and phase
timings separately from successful mandatory reports.

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

### Backend profile registries

The local runner gives each backend profile its own workspace registry under
`<run>/registry/<profile-id>`. This permits the same canonical corpus root to be
measured with SQLite and DuckDB while preserving root uniqueness within each
registry. CLI and MCP stages use their profile registry; family and daemon stages
use the primary profile registry. Failed workspace registration retains its
original attempt and excludes dependent configuration and queries.

This applies to both analyzer-style and stress manifests, which share the runner.
Existing runs retain their original registry layout and failure evidence. After
this runner change, create a new run ID rather than resuming an old run with
changed code.

### Traversal failures and interrupted publication

Source-specific `RecursionError` failures are retained alongside syntax and
encoding failures, including their paths, while successful files remain usable.
Unexpected fatal errors and operator interruptions finalize the generation as
`failed`; readers must not treat it as a completed or partial publication. The
last successful generation number remains recorded for diagnosis. Correct the
cause and explicitly run `codira index` to recover; an interrupted generation
is not evidence of usable results.

### Source-anchor context queries

Source-anchor matching materializes matching persisted lines first and resolves
class/function enclosing ranges in batches. Literal path restrictions apply
before the deterministic 128-row cap; unrelated files cannot consume that cap.
The logical query is shared by SQLite and DuckDB and preserves independent anchor
counts and nested enclosing symbols. Its SQL diagnostic timing is distinct from
end-to-end context latency; a new operator-run campaign is still required to
measure the complete context pipeline after this change.

### Architecture extraction and SVG layout

SQLite and DuckDB implement the optional `BulkArchitectureBackend` contract.
Architecture inventory, imports, calls and callable references require four bulk
reads from one connection and omit unused per-symbol graph metrics. Backends
without the extension use the established relation APIs through one shared
connection. Cycle detection is iterative, including graphs deeper than Python's
recursion limit. Import destinations are resolved by looking up successively
shorter dotted prefixes in the indexed module set, preserving the longest match
without scanning every module for each import. The logical schema and backend
schema revisions are unchanged.

`codira arch --no-svg` writes the mandatory DOT, Markdown, dependencies, hotspots,
violations and manifest without layout. By default optional SVG rendering has a
180-second timeout; `--svg-timeout-seconds SECONDS` changes it, and `0` explicitly
permits unbounded layout. Timeout terminates the owned renderer process group,
removes its incomplete SVG, and retains a warning and the mandatory report. A
missing renderer or failed layout also leaves mandatory artifacts usable.

The manifest records extraction, policy, artifact-writing and SVG durations
separately. Compare extraction and layout separately; an optional SVG warning is
not a failed structural report. The campaign's whole-command safety timeout still
bounds extraction and report construction. A whole-command timeout remains
censored measurement data. These changes do not qualify r5 or establish complete
coverage. Use a new operator-run identity after merging the fixes.

### Command errors, memory measurements and version provenance

Workspace resolution uses the same CLI error boundary as command execution.
Requests for JSON receive `status=error` with an error type and original message;
stderr retains a controlled diagnosis. Nonzero commands with missing/malformed
JSON remain command failures with their exit status and stderr diagnosis; the
output-contract error is recorded separately. The original stdout/stderr and
attempt history remain intact. Malformed output from an otherwise successful
process is still an output-contract failure.

On Linux and macOS the runner collects per-command peak RSS using exact-child
`wait4` resource accounting without requiring `/usr/bin/time`. macOS byte counts
are normalized to KiB. Linux resource accounting includes pre-exec startup memory
and the maximum of waited descendants; this is not simultaneous process-tree
memory. Compare matching collector, units, startup environment and coverage
cohorts. It does not use the launcher's accumulated child high-water mark. Linux
GNU time remains a fallback; otherwise RSS is explicitly unavailable. Timed-out
or interrupted resource collection remains unavailable, with a reason. Every
command sample records collector, scope, units and availability; exclude missing
RSS values from memory comparisons rather than interpreting them as zero.

The immutable identity includes measurement capabilities and both installed and
build-generated Codira versions. A known version disagreement rejects campaign
admission; run `uv sync --offline` in the selected checkout and choose a fresh
identity. Preserved source/configuration digests still determine identity and
resume compatibility; a version label alone does not establish runtime parity.


### Native acceleration and retained MCP diagnostics

Campaign identity records actual FAISS native compile and SIMD dispatch facts.
Unknown optional diagnostic fields remain unknown; a Python binding's module
name is insufficient to determine acceleration. Each MCP attempt retains server
stderr in `mcp.stderr`, linked from its result receipt. Routine INFO messages are
kept out of terminal progress, while actual tool errors remain failed results
and retain structured responses. Inspect the linked stderr for diagnosis.


## Integrated stress corrections and embedding diagnostics

The dedicated findings checkout incorporates validated symbol inventory/graph
aliases, C/C++ header routing, bounded SVG rendering and DuckDB inventory query
repairs. Distribution pins currently align SQLite 2.0.3, DuckDB 2.0.5, C++ 2.0.1,
FAISS similarity index 2.0.1 and official bundle 2.0.13. Installer catalog checks
verify generated header/backend options. These changes do not amend existing
campaign results or prove repository-wide coverage. Performance claims in the
[earlier findings report](../process/local-corpus-analyzer-style-r7-followup-2026-10-12.md)
retain their original source and workload limitations.

Deferred population now checkpoints bounded owned batches, preserves caller
transaction control and repairs derived artifacts on explicit empty-queue retry.
The [embedding recovery guide](pending-embedding-recovery.md) gives profiling
commands, units and transaction limitations. Set `CODIRA_EMBEDDING_PROFILE_DIR`
to a fresh durable evidence directory when launching an operator-run suite to
retain native phase journals. Each invocation chooses a unique filename;
ordinary runs leave profiling disabled. Retain these journals with campaign
attempt evidence and interpret them alongside structural coverage cohorts.

For recovery of the first stress run, use the corrected checkout after the
original run has finished or been operator-paused. These commands prepare a
new identity and preserve the original evidence; they are operator-run:

```bash
SOURCE_CHECKOUT=/home/marco/Personalia/Progetti/Software/Python/codira
ORIGINAL_RUN="$SOURCE_CHECKOUT/.artifacts/benchmarks/test-material/local-stress/local-stress-20261010-r1"
STRESS_PLAN_DIR="$PWD/.artifacts/benchmarks/test-material/recovery-stress-r2"
uv sync --offline --extra docs
uv run --offline --no-sync python scripts/run_test_material_benchmarks.py "$SOURCE_CHECKOUT/benchmarks/performance/test-material-20261010/local-stress.local.json" --prepare-recovery "$ORIGINAL_RUN" --recovery-dir "$STRESS_PLAN_DIR"
uv run --offline --no-sync python scripts/run_test_material_benchmarks.py "$STRESS_PLAN_DIR/manifest.json"
CODIRA_EMBEDDING_PROFILE_DIR="$STRESS_PLAN_DIR/embedding-profiles" uv run --offline --no-sync python scripts/run_test_material_benchmarks.py "$STRESS_PLAN_DIR/manifest.json" --run --run-id local-stress-fixed-r2 --svg-timeout-seconds 180 --architecture-timeout-seconds 300
```

Expected preparation output names the new manifest; the dry plan lists the
selected profiles and independent rendering controls. A changed runner/runtime
cannot resume the original identity. Resume the new run only with its identical
command plus `--resume`; do not copy stage checkpoints from another run. Optional
SVG omissions, structural coverage gaps and command failures remain separate.


### Conditional skips and resume counters

Every newly omitted conditional test prints `[skip; pending; timestamp]` and its
prerequisite reason, including MCP CLI evidence when no symbol identity was
discovered. Group exclusions print each pending child once; skips do not advance
the measured-test ordinal. Repeated exclusions do not print or decrement again.
Retained resume checkpoints are removed silently from the invocation's initial
inventory; they are not new skipped tests or new measurements. Missing
prerequisites remain distinct from failed commands. Timestamp formatting and
these rules are shared by the analyzer-style and stress runners.
