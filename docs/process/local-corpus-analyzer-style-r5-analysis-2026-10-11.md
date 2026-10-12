# Analyzer-style campaign r5: results and root causes

Date: 2026-10-11. Scope: **`analyzer-style-20261010-r5` only**.

The campaign finished executing, but did not establish a SQLite/DuckDB comparison.
Every DuckDB registration failed before indexing. SQLite indexed 35 of the 36
repositories, with one fatal CPython parser error. Three architecture commands
hit their 300-second limit. The run also exposes remaining Go symbol identity
bugs and a severe context-query SQL bottleneck.

This report is an analysis, not a repair or a new campaign. No retained campaign
files were rewritten, no corpus checkout was changed, and no campaign was rerun.
Focused parser and read-only SQL diagnostics are separate from campaign timings.

## Evidence and identity

Primary evidence directory:
`.artifacts/benchmarks/test-material/analyzer-style/analyzer-style-20261010-r5/` (local, ignored evidence).
Read its `identity.json`, `manifest.json`, `summary.json`, numbered stage attempt
receipts, original stdout/stderr, final index generations, and architecture artifacts
together. Derived evidence is retained separately under
`.artifacts/analysis/analyzer-style-r5-20261011/` (local, ignored evidence).

- Recorded core commit: `c3f959853f59b2cc167209c13625034d5dd66da9`.
- Recorded Codira distribution: `2.4.1.post1.dev5`; Go/Rust/TypeScript analyzers
  `2.0.1`; SQLite and DuckDB structural backend distributions `2.0.0`.
- Recorded machine: Intel Core i7-8700K, 12 logical CPUs, Gentoo Linux
  `6.18.54-gentoo-dist-bin`, glibc 2.43, Python 3.13.13 built with Clang 22.1.3.
- Plan: 36 repositories, SQLite and DuckDB structural profiles, embeddings
  disabled, 11 analyzer families and seven explicitly routed documentation styles.
  `extended=false`: family, daemon, installer, embedding, and extended MCP stress
  coverage were outside this campaign.
- Current launcher digest matches the recorded launcher. The original manifest
  digest and all 72 configuration digests still match the receipt. All 36 current
  corpus HEADs match their pinned revisions. This verifies revision identity, not
  independently frozen dirty-working-tree content; the runner did not retain a
  per-file source snapshot for every successful source.
- Identity/summary filesystem timestamps span 2026-10-10 20:31:52 UTC to
  2026-10-11 00:58:02 UTC, approximately 4 h 26 min 10 s. Summed serial sample
  durations are 15,967.42 seconds, approximately 4 h 26 min 7 s. The filesystem
  interval is an approximation, not a separately recorded timing measurement.

The recorded version is reported as received; it is not inferred from today's
Git tags or the cached MCP process. That MCP process still held an older runtime,
so source navigation was refreshed through the repository CLI before inspection.

There is a version-provenance inconsistency, separate from the command failures.
The current release metadata advanced to `2.4.3` at commit `c982b8b` during analysis;
tracked core, analyzer, and launcher implementations remain identical to r5.
The runtime fingerprint includes the ignored generated `src/codira/_version.py`.
Reconstructing that file in memory with version `2.4.2` and commit ID `g9f18df003`
reproduces r5's exact aggregate core source digest, whereas its installed
distribution receipt reports `2.4.1.post1.dev5`. The generated version and installed
metadata were therefore out of sync. This does not establish different algorithm
code or explain the failures, but it prevents treating the distribution version
alone as a sufficient runtime identity. Synchronize and record both before a new
campaign; regenerated version metadata also changes freshness/resume fingerprints.
The reconstruction and Git comparisons are retained in `runtime-source-drift.json`.

## Outcome accounting

`execution_complete=true`, `complete=false`, `coverage_complete=false`.

| Stage status | Count | Interpretation |
| --- | ---: | --- |
| passed | 74 | Two discovery stages and 72 SQLite workspace/config prerequisites |
| partial | 387 | Queryable results or index measurements with incomplete coverage |
| partial_empty | 92 | Legitimate empty results under incomplete coverage |
| failed | 73 | 36 DuckDB registrations, 36 downstream config commands, one CPython index |
| timeout | 3 | Architecture commands exceeded 300 seconds |
| excluded | 40 | 36 DuckDB query groups, one CPython query group, three incremental probes |
| **Total** | **669** | **1,287 measured process samples** |

There were 553 operationally queryable/passed stages, 76 failed/timed-out commands,
and 40 exclusions. These numbers are execution accounting, not semantic accuracy.
The summary's `complete_index` cohort has 74 entries, all discovery/setup commands;
it contains **no complete-coverage indexing or dependent query measurements**.
Its `partial_coverage` cohort has 482 entries, including the three timeouts; use
sample status and `partial_timing_valid` before selecting usable measurements.

Across the 35 completed SQLite indexes, 130,862 files were indexed and six selected
files failed. CPython's fatal attempt supplied no usable successful-file summary,
so it is excluded from those file totals. All completed indexes had coverage
issues: 31,433 parser-recovery diagnostics, 9,733 unsupported-file coverage issues,
and six Python target-version diagnostics. These are 41,172 coverage issues,
separate from the six failed files. C and C++ account for 30,983 partial-analysis
status rows; many LLVM test inputs and macro-dependent sources are not standalone
translation units. That explains a substantial share of the gaps, but does not
prove each parser recovery harmless or every emitted symbol accurate.

The 92 empty stages comprise 14 audits, 26 outgoing references, 34 incoming
references, nine calls, and nine call-tree outputs. Empty results remain
partial-coverage observations; they do not prove repository-wide absence or
complete documentation compliance.

## Root cause 1: all DuckDB setup failed in the shared registry

**Confirmed runner topology error; not evidence that DuckDB indexing is broken.**

All 36 retained registration stderr files say that the canonical repository root
is already registered by its SQLite workspace. `Campaign.__init__` sets one
`XDG_CONFIG_HOME=<run>/registry` for both profiles. `Campaign.repository` then tries
to register the same corpus root under a second profile-specific workspace name.
Different state directories do not satisfy the registry's root uniqueness rule.
[`WorkspaceRegistry.add` and `_reject_root_conflict`](https://github.com/marco0560/codira/blob/f2936cab8456ff27f5c2dae248bbabd15b69f2c0/src/codira/workspace_registry.py)
explicitly reject that second canonical root.

Each rejected registration was followed by `config --workspace ... validate` anyway.
Those 36 config failures say “Workspace is not registered”. They are consequences
of the first failure, not 36 independent invalid configurations. The runner's
“malformed JSON output” classification obscures the actual stderr cause.
Furthermore, [`cli.main`](https://github.com/marco0560/codira/blob/f2936cab8456ff27f5c2dae248bbabd15b69f2c0/src/codira/cli.py) resolves the workspace before
entering its dispatch exception handler, so that resolution failure emits a raw
traceback instead of a consistent command error envelope.

**Repair direction:** keep the root uniqueness contract and isolate registries per
backend profile, consistently propagating that environment to CLI, MCP, and family
operations. Check registration before launching its dependent config command.
Add a real two-profile/same-repository registration regression, not only mocked
successful prerequisites. Wrap workspace resolution in the CLI error boundary.

**Interpretation:** no DuckDB index or query stage ran. The backend comparison is
unqualified, regardless of the presence of DuckDB in the manifest or plugin list.

## Root cause 2: CPython crashes in recursive syntax normalization

**Confirmed Python analyzer defect plus an indexing exception/publication defect.**

The original command exited 2 after 24.10 seconds, with empty stdout and
`[codira] RecursionError: maximum recursion depth exceeded`. The runner consequently
reported malformed JSON and excluded the dependent queries. It could not retain
a failed source path from that output.

A focused reproduction on the pinned source
`Lib/test/test_traceback.py` identifies the cause. Its assignment at line 4993
links `a0` through `a800` to `None`. The Tree-sitter tree has depth 808 and reports
no grammar error. The package-owned
[`syntax._normalized_node`](https://github.com/marco0560/codira/blob/f2936cab8456ff27f5c2dae248bbabd15b69f2c0/packages/codira-analyzer-python/src/codira_analyzer_python/syntax.py)
recursively constructs each child tuple using a generator. Those nested Python
frames exceed the default stack limit. Direct analysis of this one file reproduces
`RecursionError` at that function; the complete traceback is retained in
`cpython-python-recursion-reproduction.json`.

This is valid source exposing a traversal limit, not the LLVM encoding fixture
or a database uniqueness violation. A separate iterative depth check on C headers
found very deep preprocessor trees, but a focused C analyzer probe succeeded;
those observations do not explain the campaign's fatal exception.

[`indexer._analyze_index_task`](https://github.com/marco0560/codira/blob/f2936cab8456ff27f5c2dae248bbabd15b69f2c0/src/codira/indexer.py) normalizes `SyntaxError`,
`UnicodeDecodeError`, and `ValueError`, but not `RecursionError`. It therefore escapes
the worker and aborts the indexing call. `index_repo` wrote an `updating` marker
before invoking the unlocked operation but has no enclosing failure transition
for this exceptional path. The retained CPython generation remains
`state=updating`, `last_successful_generation=0`, with no published file count.
That index is correctly unusable for readers; the publication lifecycle is the
additional defect.

**Repair direction:** normalize syntax trees iteratively and test deep valid
assignments through the real analyzer and indexer. Give source-specific traversal
failures a retained per-file path and diagnosis when recoverable. Ensure unexpected
fatal indexing exceptions leave an explicit failed generation rather than a
permanent in-progress marker. Do not simply raise the process recursion limit or
silently label the interrupted index usable.

## Root cause 3: four VictoriaMetrics files still have duplicate Go IDs

**Confirmed Go extraction/identity defects; the database safeguard is working.**

Four valid Go files failed the pre-persistence duplicate-ID check:

| File | Reproduced defect |
| --- | --- |
| `app/vmalert/datasource/client_prom.go` | Grouped constant names include comma tokens; multiple declarations get a name and stable-ID suffix of `,` |
| `lib/storage/inmemory_part_timing_test.go` | Local `rows` and `r` inside distinct function literals receive file-level variable IDs |
| `lib/storage/merge_timing_test.go` | Local `rows`, `r`, and `mps` in different function literals collide at file scope |
| `vendor/go.opentelemetry.io/otel/sdk/metric/internal/observ/instrumentation.go` | Two local constants `n` inside callbacks collide, and are classified using the enclosing top-level variable declaration's kind |

Direct `GoAnalyzer.analyze_file` calls reproduce seven duplicated ID keys across
these four files. In
[`GoAnalyzer.analyze_file`](https://github.com/marco0560/codira/blob/f2936cab8456ff27f5c2dae248bbabd15b69f2c0/packages/codira-analyzer-go/src/codira_analyzer_go/__init__.py),
`children_by_field_name("name")` is consumed without filtering punctuation nodes.
The recursive `_descendants` walk of a top-level variable initializer also enters
function literal bodies, then assigns their nested declarations the outer
file/name ID and outer declaration kind.

The earlier blank-identifier and repeated-`init` fixes are present in the recorded
`2.0.1` analyzer, but do not cover these cases. No Rust or TypeScript duplicate-ID
failure was reported in r5.

**Repair direction:** accept actual identifier nodes, limit top-level declaration
traversal to its declared scope, and encode lexical ownership for local symbols
if the analyzer intentionally emits them. Test grouped names and distinct
function-literal scopes. Merely loosening SQL uniqueness or giving comma symbols
arbitrary suffixes would persist incorrect facts and conceal the extraction bug.

## Expected partial failures: Django and LLVM test fixtures

These two retained failures are expected fixture behavior, distinct from the
product defects above:

- Django: `tests/test_runner_apps/tagged/tests_syntax_error.py` contains intentionally
  invalid Python. Its own `tests/test_runner/test_discover_runner.py` exercises that
  module as a syntax-error fixture. Codira indexed 3,729 files and retained this one
  `SyntaxError`.
- LLVM: `llvm/utils/lit/tests/shtest-encoding.py` explicitly contains a string that
  cannot be decoded in line mode. It contains an invalid UTF-8 byte sequence.
  Codira indexed 76,748 files and retained this one `UnicodeDecodeError`.

Django, VictoriaMetrics, and LLVM all ended with **ready, partial generation 1**;
their failed counts are 1, 4, and 1. The runner withheld exactly those three
incremental-index probes, while supported dependent queries continued. No sample
stderr contained an automatic-index freshness warning. This is evidence that
unchanged failed files did not cause repeated automatic indexing in r5.

Keep these failures visible. Operator exclusions are an optional scope change,
not a silent repair, and require a new manifest/run identity with provenance.

## Performance root: VictoriaMetrics context spends an hour per invocation

Recorded times for query `AddAcceptEncodingGzip`:

| Context format | Wall seconds | Minutes |
| --- | ---: | ---: |
| JSON | 3,687.10 | 61.45 |
| Prompt | 3,694.97 | 61.58 |
| Explain | 3,702.31 | 61.71 |

Together these consume 11,084.39 seconds, **69.42%** of all sample time. Embeddings
were disabled. The output is operationally successful and partial; it has no
semantic quality oracle. The runner picked this vendor function from its bounded
symbol inventory, so it is not a representative application task selected by a
human or a retrieval-quality dataset.

A confirmed expensive query is in
[`task_anchors.source_candidates`](https://github.com/marco0560/codira/blob/f2936cab8456ff27f5c2dae248bbabd15b69f2c0/src/codira/query/task_anchors.py), called
unconditionally by context orchestration when the query supplies source anchors.
The retained VictoriaMetrics index has 242,059 symbol rows, 2,032,292 persisted
source lines, 91,718 functions, and 15,892 classes. `EXPLAIN QUERY PLAN` for the exact
query shows a symbol scan, a source-line join, and correlated class/function
end-range subqueries. The anchor predicate uses a leading-wildcard case-insensitive
match. `ORDER BY ... LIMIT 128` caps output, not all upstream work.

Read-only diagnostic, on the retained index, with a five-second limit per SQL query:

- Original SQL: still running at five seconds; interrupted by its own SQLite
  progress callback.
- Same enclosing-symbol lookup after materializing the matching source lines
  first: three rows in 1.65 seconds.

This confirms a poor query plan and a strong repair candidate. It is **not** a
measured end-to-end speedup and does not prove that this one query accounts for
all 61 minutes; no original per-phase profile was recorded. The original explain
output does retain source-anchor support for the same target symbols.

**Repair direction:** filter source hits before correlating them with enclosing
symbols, use indexed/batched range resolution, and test result equivalence and
backend portability. Bound work as well as returned row count. Retain query-phase
profiles in a new run; a formatting change or embedding switch does not address
this SQL cost.

## Architecture timeouts have two different causes

All three timeouts occurred at the configured 300-second whole-command limit.
The receipt's generic “architecture rendering exceeded limit” wording cannot by
itself distinguish extraction from SVG layout.

### Django: optional SVG layout

The run retained `architecture.dot`, `architecture.md`, `dependencies.json`,
`hotspots.json`, and `violations.json`, but no SVG or final manifest. The graph has
3,041 modules and 8,075 dependencies. The artifact ordering in
[`write_architecture_artifacts`](https://github.com/marco0560/codira/blob/f2936cab8456ff27f5c2dae248bbabd15b69f2c0/src/codira/architecture_report.py) writes those
mandatory files before calling `_render_svg`, then writes the manifest afterward.
This localizes the interruption to the SVG interval; the existing `_render_svg`
subprocess has no product-level timeout. Graphviz layout complexity is the likely
underlying bottleneck; no retained Graphviz stack profile establishes the exact
layout subroutine. The whole-command timeout prevented an unbounded campaign stall,
but turned an optional SVG operation into a failed report measurement.

### Twenty and LLVM: extraction before artifact publication

Neither command created architecture artifacts. The indexes contain 97,730 and
447,744 symbol rows, respectively. Inspection and bounded read-only probes expose
work performed before writing a report:

1. [`SqliteBackend.symbol_inventory`](https://github.com/marco0560/codira/blob/f2936cab8456ff27f5c2dae248bbabd15b69f2c0/packages/codira-backend-sqlite/src/codira_backend_sqlite/__init__.py)
   computes four relation-count queries per retained inventory symbol, even though
   architecture extraction does not use those inventory metric fields.
2. [`build_architecture_model_from_index`](https://github.com/marco0560/codira/blob/f2936cab8456ff27f5c2dae248bbabd15b69f2c0/src/codira/architecture.py) then
   issues imports per module and two additional relation lookups per non-module
   inventory item. In the actual CLI call no shared connection is supplied, so
   those relation methods open and close their own connections repeatedly.
3. A ten-second probe with an explicit read-only shared connection counted
   **391,537 SQL calls** for Twenty, including 390,112 metric queries, before being
   interrupted during extraction. LLVM counted **1,558,197 SQL calls**, almost all
   inventory metric queries, and had not completed extraction at the limit.

These probes confirm N+1 query amplification. They do not reproduce the full
300-second commands or prove an exact percentage split among inventory, relation
lookup, aggregation, and policy analysis. They show why blaming Graphviz for both
of these timeouts would be unsupported.

**Repair direction:** bulk inventory/metric aggregation and backend-neutral batch
relation extraction with a shared read session; avoid unused metric queries.
Separate extraction and SVG phase timings. Give optional SVG rendering an explicit
bound or operator-controlled omission, retaining completed mandatory artifacts and
a consistent warning/manifest when SVG cannot finish. Keep the campaign safety
limit until the phases are measured separately.

## SQLite measurements, with coverage limitations

Seconds below are recorded full-index sample times or medians of the available
query/incremental samples. Full indexing is one sample per repository; query
repetition counts vary by manifest. There are no cross-backend ratios and no
confidence intervals for single-sample rows. Repository size buckets use catalog
whole-repository LOC, not analyzer-specific LOC or documentation volume.

| Repository | Indexed files | Failed files | Full index s | Incremental s | Context JSON s | Architecture s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| markdown-dataset-json-examples | 2 | 0 | 1.46 | 0.93 | 0.54 | 0.62 |
| c-inih | 20 | 0 | 1.90 | 0.83 | 0.59 | 1.02 |
| python-commonmark-spec | 9 | 0 | 1.48 | 0.83 | 0.48 | 0.82 |
| rust-anyhow | 38 | 0 | 2.03 | 0.89 | 0.59 | 1.12 |
| shell-official-images | 140 | 0 | 2.54 | 1.26 | 0.64 | 1.02 |
| json-config | 62 | 0 | 2.21 | 0.89 | 0.62 | 1.07 |
| go-chi | 90 | 0 | 2.43 | 0.94 | 0.48 | 1.37 |
| javascript-picomatch | 69 | 0 | 2.29 | 0.90 | 0.70 | 1.02 |
| python-requests | 51 | 0 | 2.47 | 0.94 | 0.62 | 1.57 |
| javascript-koa | 98 | 0 | 2.54 | 0.99 | 0.61 | 1.22 |
| shell-nvm | 21 | 0 | 2.85 | 1.54 | 0.58 | 0.87 |
| javascript-express | 146 | 0 | 2.07 | 1.04 | 0.62 | 1.57 |
| shell-bash-it | 357 | 0 | 2.87 | 1.49 | 0.77 | 2.07 |
| python-click | 134 | 0 | 2.95 | 0.99 | 0.72 | 2.17 |
| c-zlib | 86 | 0 | 2.52 | 1.14 | 0.66 | 0.87 |
| rust-ripgrep | 135 | 0 | 3.07 | 1.15 | 0.74 | 3.32 |
| cpp-fmt | 92 | 0 | 2.75 | 0.92 | 1.16 | 0.97 |
| python-pytest | 253 | 0 | 6.03 | 1.88 | 0.89 | 23.57 |
| cpp-Catch2 | 496 | 0 | 3.41 | 1.73 | 0.74 | 2.07 |
| go-helm | 669 | 0 | 7.10 | 4.49 | 2.54 | 4.88 |
| typescript-core | 578 | 0 | 4.50 | 2.04 | 1.20 | 27.97 |
| typescript-nest | 2046 | 0 | 9.11 | 5.01 | 1.30 | 57.78 |
| markdown-rfcs | 658 | 0 | 2.95 | 1.67 | 0.69 | 0.87 |
| javascript-pdf-js | 517 | 0 | 9.42 | 4.06 | 0.89 | 8.38 |
| c-redis | 954 | 0 | 6.99 | 3.60 | 0.91 | 5.58 |
| go-prometheus | 1089 | 0 | 10.81 | 3.25 | 16.42 | 15.40 |
| python-django | 3729 | 1 | 34.23 | withheld | 1.88 | timeout (300 s) |
| rust-bevy | 2083 | 0 | 17.83 | 5.56 | 1.07 | 35.13 |
| c-postgres | 2601 | 0 | 20.82 | 12.93 | 1.79 | 12.89 |
| rust-zed | 2302 | 0 | 34.53 | 7.15 | 1.36 | 61.59 |
| go-VictoriaMetrics | 6796 | 4 | 58.64 | withheld | 3687.10 | 245.42 |
| python-cpython | fatal | unknown | 24.10 | — | — | — |
| typescript-twenty | 26092 | 0 | 114.65 | 78.17 | 7.30 | timeout (300 s) |
| json-schemastore | 1616 | 0 | 19.76 | 10.57 | 2.27 | 65.39 |
| cpp-llvm-project | 76748 | 1 | 544.79 | withheld | 24.94 | timeout (300 s) |
| json-cldr-json | 85 | 0 | 63.93 | 63.25 | 15.50 | 16.60 |

All indexing and dependent-query values in this table have incomplete coverage.
For CPython, the “full index” duration is a fatal attempt, not valid indexing
throughput. A timeout is censored data, not a completed 300-second report. Rows
labelled “withheld” intentionally do not measure retrying known failed sources.
CLDR is explicitly a large negative JSON corpus; its discovery cost divided by
only the accepted files is not a fair analyzer throughput comparison.

## Measurement gaps and validation limits

- Every one of the 1,287 samples has `peak_rss_kib=null`. The runner only measures
  RSS when `/usr/bin/time` exists. That executable is absent on the analysis host,
  matching its fallback behavior; the run did not record a separate timer-capability
  receipt. There is no evidence for a memory usage or memory exhaustion claim.
- No per-phase context/extraction/layout profiles were recorded. SQL probes are
  bounded diagnostics, not replacements for end-to-end campaign measurements.
- No retrieval relevance, reference recall, documentation compliance, or task-success
  oracle was run. Documentation routes identify syntax witnesses; fourteen empty
  audits do not certify all seven styles across all repository sizes.
- Static relations and omitted-file coverage remain incomplete even where command
  exit codes are zero. Partial empty references cannot establish repository-wide
  absence. Raw complete/partial cohort labels alone cannot select comparable data.
- No indexing/query command was launched against the retained campaign workspaces
  during this analysis. SQL connections used `mode=ro&immutable=1`. Diagnostics
  inspected individual source files and stopped their own SQL work at fixed limits.
- No implementation code was changed. A full repository code-validation gate was
  not rerun for this report; validation here consists of receipt accounting,
  digest/revision checks, focused analyzer reproductions, SQL query plans, and
  bounded read-only extraction probes.

## Recommended repair order and acceptance checks

| Priority | Change | Required proof before another broad campaign |
| --- | --- | --- |
| 1 | Profile-isolated registries and dependency gating | Same physical corpus root can be benchmarked under both profiles without violating one-registry root uniqueness; no config stage after failed registration |
| 1 | Iterative Python normalization and fatal-generation finalization | Deep valid assignment indexes successfully; injected unrecoverable failures leave explicit failed state; expected per-file failures retain successful files and paths |
| 1 | Go declaration node/scope correction | All four pinned files produce unique valid IDs before backend persistence; grouped commas are not symbols and nested declarations retain correct ownership/kind |
| 2 | Source-anchor SQL plan | Retained-query result equivalence, indexed/batched resolution, and bounded-cost regression on representative large data; separate backend checks |
| 2 | Bulk architecture extraction and bounded optional SVG | Query-count regression, shared session, phase timings, and mandatory report artifacts retained when SVG times out |
| 3 | Error and instrumentation contracts | Workspace resolution produces a controlled error; runner reports the root stderr cause and timer availability explicitly |

Use small focused fixtures and offline validation before a new operator-run
campaign. Fixing the runner, runtime, configuration, or exclusions requires a
**new immutable run identity**. Preserve r5; neither overwrite it nor resume it
with changed code. SQLite partial observations remain useful diagnostic evidence,
but the DuckDB comparison, memory comparison, full-coverage claims, and semantic
quality claims are not qualified by this run.
