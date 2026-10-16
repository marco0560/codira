# Analyzer-style campaign r6: results and remaining root causes

Date: 2026-10-11. Scope: **`analyzer-style-20261010-r6`**. Comparison with r5 is
limited to matching SQLite stages; the r5 DuckDB registrations never succeeded.

R6 completed execution and substantially improved on r5. SQLite produced a usable
index for all 36 repositories; DuckDB produced 33. All workspace registrations
succeeded. The remaining command failures are three DuckDB CSV imports and three
architecture timeouts. The report does not treat partial coverage or empty
responses as proof of repository-wide completeness or semantic correctness.
No benchmark campaign was rerun, resumed, edited, or automatically excluded.

## Evidence and controls

- Immutable run: `.artifacts/benchmarks/test-material/analyzer-style/analyzer-style-20261010-r6/` (local, ignored evidence).
- Derived analysis: `.artifacts/analysis/analyzer-style-r6-20261011/` (local, ignored evidence).
- Historical comparison: [r5 report](local-corpus-analyzer-style-r5-analysis-2026-10-11.md)
  and its original stage receipts.
- Recorded commit `5b2cdc320d32e91ea6f7c41e6a68eee6b83e310e`, Codira `2.4.4`;
  installed and generated versions agree. Python analyzer `2.0.1`, Go `2.0.2`,
  SQLite and DuckDB backends `2.0.1`. R6 predates the NumPy audit-parser fix in
  `0484fd1`; its NumPy distribution was `2.0.0` and implementation revision `1`.
  Current main includes that fix and the subsequent `2.4.5` release.
- Intel Core i7-8700K, 12 logical CPUs, Gentoo Linux `6.18.54`, glibc 2.43,
  Python 3.13.13. Structural-only profiles, embeddings disabled, `extended=false`.
- Manifest and all 72 config digests still match; all 36 current corpus HEADs
  match their recorded revisions. Dirty source content was not independently
  frozen per file, so HEAD matching alone is not a full source-content guarantee.
- The recorded launcher digest matches the launcher at the recorded Git commit.
  Today's launcher differs because the later CI fix added a docstring section.
- Backend comparisons below use matching commands and repositories with usable
  measurements on both sides. All 33 paired full indexes have equal successful
  file counts. Backend failure time is excluded from successful-speed comparisons.
- Both benchmark profiles ran serially on one workstation. Filesystem caching,
  background work and fixed profile order can influence small differences.
  The manifest's cold/warm labels do not establish separate controlled cache
  states: this execution launches repeated fresh CLI processes, without a
  dedicated cold-cache reset or warm daemon experiment.

## What the campaign measured

1,108 recorded stages produced 2,397 process samples. Summed sample time was
**7,366.85 seconds (2 h 2 min 47 s)**. The approximate identity-to-summary
filesystem interval was 7,371.59 seconds; it is not an independent timer.

| Status | Stages | Meaning |
| --- | ---: | --- |
| passed | 146 | Discovery and workspace/config prerequisites |
| partial | 769 | Usable indexing/query measurements with incomplete coverage |
| partial_empty | 180 | Empty results under incomplete coverage |
| failed | 3 | DuckDB full-index persistence errors |
| timeout | 3 | Architecture commands stopped at 300 seconds |
| excluded | 7 | Three unusable-index query groups and four incremental retries |
| **Total** | **1,108** | **1,095 operationally usable stages** |

`execution_complete=true`; `complete=false`, `coverage_complete=false`.
The runner finished its work, but some capabilities failed and coverage remains
incomplete. The `complete_index` comparison group contains 146 setup/discovery
stages only; it does not contain complete-coverage repository measurements.

| Backend | Usable repository indexes | Successfully indexed files | Failed files within usable indexes |
| --- | ---: | ---: | ---: |
| SQLite | 36 / 36 | 134,395 | 5 |
| DuckDB | 33 / 36 | 53,540 | 1 |

These file totals cover different populations. DuckDB's failed CPython, Vue/core
and LLVM campaigns must not be counted as zero-file successful indexes.

SQLite retained 42,059 coverage issues: 32,286 parser-recovery diagnostics,
9,767 unsupported-file issues and six Python target-version diagnostics. LLVM
accounts for 29,205 of the parser-recovery diagnostics. Test fragments,
macro-dependent translation units and unsupported YAML/images/config formats
explain many gaps; this does not certify every recovered symbol as correct.
`partial=false` in file-failure metadata can coexist with `complete=false` when
all attempted supported files succeeded but analyzer coverage is incomplete.

## What the earlier fixes demonstrably improved

All 72 workspace registrations and 72 config validations now succeed, resolving
r5's cross-backend registry conflict. CPython now yields a usable SQLite index
instead of aborting the campaign on its malformed encoding fixtures. Failed
files remain visible, and supported dependent queries run against usable indexes.

For identical VictoriaMetrics `ctx` arguments, mean time dropped from
**3,687.10 s to 4.293 s**, an observed **858.8x** reduction. Prometheus changed
from 16.451 s to 1.273 s. These are workload observations, not a general speedup
claim or proof that retrieved context is semantically equivalent. The SQLite
profile's summed process time fell from 15,940.07 s in r5 to 3,827.16 s in r6;
coverage and available commands changed, so this aggregate is not a controlled
single-variable comparison. R6 also ran the DuckDB profile, absent from r5.

Read-only checks of all four Go SQLite symbol indexes found **zero duplicated
stable identifiers**: chi 653 symbols, Helm 5,029, Prometheus 17,127, and
VictoriaMetrics 242,094. This supports the earlier Go identity repair for this
corpus; it is not a universal uniqueness proof.

## Remaining failure 1: DuckDB CSV transport

| Repository | Full-index failure time | Failure |
| --- | ---: | --- |
| TypeScript Vue/core | 3.72 s | Unterminated quote while importing call records |
| CPython | 65.07 s | Misparsed call record produces an empty `lineno` |
| LLVM | 883.13 s | CSV parser reaches an invalid state |

All three tracebacks converge on
`duckdb_artifact_persistence._flush_call_record_rows`. The writer uses Python's
`csv.writer`, which emits comma-separated fields and doubled quote escaping.
The reader supplies column types and a null sentinel but leaves delimiter,
quoting, escaping and newline interpretation to DuckDB's automatic detection.
The retained errors explicitly show incompatible inferred dialects, including
an empty quote character for CPython and an empty escape character for Vue/core.
CPython's quoted expression `opcodes.split(',')` then shifts field boundaries;
the reported integer conversion is a downstream symptom, not evidence that
an ordinary line number exceeds the schema's integer capacity.

A bounded synthetic diagnostic used Codira's actual writer with 25,000 and
100,000 ordinary rows followed by one comma-containing call expression. DuckDB
`1.5.2` failed both automatic reads; an explicit dialect loaded all 25,001 and
100,001 rows, respectively. The engine version matches the recorded commit's
lockfile; the campaign receipt did not independently inventory that engine.
This reproduces the transport failure mechanism without indexing any repository.
The LLVM-specific complete payload was not retained: the helper deletes its
temporary CSV in `finally`. Its exact byte-level trigger therefore remains
unproven, although its failure path and inferred dialect match this defect class.

[DuckDB's CSV documentation](https://github.com/duckdb/duckdb-web/blob/main/docs/current/data/csv/overview.md),
retrieved through Context7, confirms that explicit delimiter/quote/escape options
bypass detection of those parameters. Repair should enforce the writer's dialect
or use typed Arrow transport, with lossless tests for commas, quotes, multiline
values and nulls. Skipping rows would discard relationships and invalidate the
index. Preserve failed transport evidence in future attempts.

The failed LLVM attempt reached 13,277,016 KiB (about 12.66 GiB) peak RSS, versus
3,744,676 KiB (3.57 GiB) for successful SQLite LLVM indexing. This is a
maximum-lifetime-process/descendant measurement, not simultaneous process-tree
RSS. It is not an apples-to-apples memory-efficiency ratio for successful indexes.
No retained failure indicates out-of-memory termination.

## Remaining failure 2: architecture extraction complexity

Twenty times out on both backends, and LLVM times out on SQLite. Each command
reaches the runner's 300-second limit with empty stdout/stderr and no report
artifacts. These failures happen before the artifact writer creates its output.
They are distinct from Graphviz's now-bounded rendering time.

`architecture._resolve_import_destination` scans the entire module-name set for
every import to find a matching longest prefix. Snapshot aggregation calls it
once for each import. The retained SQLite indexes contain:

| Repository | Unique inventory modules | Imports | Implied module/import comparisons |
| --- | ---: | ---: | ---: |
| Twenty | 25,590 | 132,575 | 3,392,594,250 |
| LLVM | 45,747 | 137,655 | 6,297,303,285 |

A read-only sample of 200 imports took 0.462 s for Twenty and 0.847 s for LLVM
using the existing resolver. Simple dotted-prefix set lookup produced identical
results for these samples in approximately 0.00011 s. Linear extrapolation of
only the original resolver gives approximately 306 s and 583 s, before SQL,
model aggregation or output work. These are diagnostic estimates, not full
architecture measurements or universal equivalence tests. They establish a
concrete common-layer bottleneck consistent with the campaign timeouts;
retained per-phase traces are insufficient to apportion every timed-out second.

66 architecture artifact sets were produced; 60 include SVG. Six final manifests
(Django, Nest and VictoriaMetrics on each backend) retain mandatory DOT/Markdown/
JSON artifacts while reporting Graphviz's 30-second timeout. Those are usable
reports with missing optional SVG, not failed architecture extraction.

## Backend timing comparison

Ratio is DuckDB / SQLite, using the median of per-repository mean-time ratios.
Values above one indicate slower DuckDB measurements. All are partial coverage.

| Operation | Matched repositories | Median ratio |
| --- | ---: | ---: |
| index-full | 33 | 1.154 |
| index-incremental | 32 | 0.977 |
| ctx | 33 | 1.107 |
| sym | 32 | 1.001 |
| calls | 32 | 0.969 |
| refs | 32 | 1.094 |
| arch | 32 | 1.004 |

For successful full indexes the ratio is 1.154 (about 15% slower DuckDB); context
queries are about 11% slower. Other operations are close to parity. Process
startup and freshness work are included, often dominating small queries; three
repetitions and one fixed-order host campaign are insufficient to rank marginal
backend differences confidently. The largest failed repositories are omitted
from this table, so it cannot establish a backend choice for huge workloads.

## Empty results, documentation and exclusions

The 180 empty stages comprise 28 audits, 51 outgoing reference queries, 67
incoming reference queries, 17 calls and 17 call-tree outputs. Every measured
incoming-reference stage is empty. The harness selects a first callable from
its bounded inventory instead of choosing a source-verified positive graph
example. Empty responses therefore neither prove a reference bug nor qualify
that graph capability. Positive known-target controls are needed.

SQLite audits returned 749 findings across 22 repositories; 14 returned none.
These are returned diagnostics, not a grade of documentation quality. R6 still
used the pre-fix NumPy parser, which can reject valid grouped parameters, and
all audit measurements carry incomplete coverage. Do not retroactively present
those findings as validated by the newly merged NumPy fix, or empty audits as
repository-wide compliance.

Four incremental probes were explicitly skipped because unchanged deterministic
analysis failures should not be retried automatically: Django on both backends,
and CPython/LLVM on SQLite. Queries still ran for these usable indexes. The
other three exclusions are whole query groups following unusable DuckDB indexes.
The five unique failed source files are intentionally invalid encoding/syntax
fixtures, not grounds for silently excluding source from a campaign. A recovered
campaign must retain the original evidence and use a new identity for changed
exclusions; this report has not changed any configuration or attempted recovery.

Embeddings, vector/similarity stores, semantic retrieval grades, family routing,
MCP transport, warm-daemon operation and installer/platform services remain
outside this structural analyzer-style campaign. Seven routed documentation
style witnesses and size categories do not prove every style/size combination;
manifest gaps remain explicit.

## Follow-up and validation

Priority 1 is lossless DuckDB call-record transport. Priority 2 is indexed
architecture import-prefix lookup. Before a new performance comparison, use
source-verified positive context/graph targets, freeze relevant source state and
record complete dependency provenance. Requalify the three failed DuckDB indexes
and timed-out architecture cases after repairs; repeat campaigns only under
operator control. No implementation changes were made during this analysis.

Validation here consisted of manifest/config/revision parity checks, raw stage
accounting, read-only SQLite inventory queries, two bounded synthetic CSV
reproductions and bounded architecture-resolver diagnostics. Campaign files were
not modified. Detailed arithmetic, provenance and raw diagnostic output are in
the ignored analysis directory. There is no new full repository-gate claim for
this documentation-only analysis.

## CI worktree closeout

The merged `fix/ci-recurring-failures` worktree was removed after verifying clean
source status and main ancestry. Eighteen original evidence files were copied to
`.artifacts/analysis/ci-recurring-20261011/` and SHA-256 verified. Its audit index,
generated runtime metadata, coverage receipt and installed-package inventory
were retained there too. The approximately 8 GB managed environment and derived
caches were retired. The branch reference and unrelated benchmark-findings
worktree were retained. No campaign artifacts were deleted.
