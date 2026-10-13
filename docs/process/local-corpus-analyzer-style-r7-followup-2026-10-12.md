# Analyzer-style r7: completed-run report and root-cause follow-up

Date: 2026-10-12. Completed campaign: `analyzer-style-20261010-r7`.

The latest completed campaign is analyzer-style r7. The newer stress campaign
`local-stress-20261010-r1` was still running during this inspection, performing
SQLite ONNX embeddings for Twenty. Its `summary.json` is a checkpoint containing
only `results` and `complete=false`, without the final `execution_complete`
marker. Its checkpoint must not be treated as a completed stress-suite result.
No campaign was launched, resumed, modified, or stopped for this investigation.

## Results

| Measurement | R7 result |
| --- | ---: |
| Repositories / structural backend profiles | 36 / 2 |
| Usable indexes | 72 / 72 |
| Stages / process samples | 1,144 / 2,458 |
| Failed commands / outer timeouts | 0 / 0 |
| Partial / partial-empty stages | 800 / 192 |
| Exclusions | 6 incremental-index stages |
| Indexed / attempted files, per backend | 134,395 / 134,400 |
| Required architecture report sets | 72 / 72 |
| Optional SVGs | 64 / 72 |
| Summed process sample time | 7,429.47 seconds |

Discovery/configuration prerequisites account for 146 passed stages. All 992
repository measurements remain in the partial-coverage comparison group.
`execution_complete=true` means the campaign finished its execution plan;
`coverage_complete=false` means it did not establish complete repository analysis.
Five individual analysis failures recur on each backend. Dependent queries ran;
entire repository query groups were not excluded.

R7 used Codira 2.4.6, DuckDB backend 2.0.2, Python 3.13.13, and an Intel
Core i7-8700K with 12 logical CPUs. Embeddings were disabled. Manifest and
configuration controls match r6, while the SVG budget increased from 30 to
60 seconds. Profile ordering and OS caches were not randomized or reset.
This suite supplies workload measurements, not retrieval-quality grades.

## Root causes

### Individual Python failures are intentional fixtures

Django's `tests_syntax_error.py` is explicitly imported by a test expecting a
`SyntaxError`. CPython's three failed files are used by tests for bad encoding
cookies and invalid UTF-8. LLVM's `shtest-encoding.py` explicitly contains bytes
that cannot be decoded in line mode. Its comment-only contents can pass native
`compile(bytes, ...)`, while `tokenize.open` and Codira correctly reject the
invalid UTF-8 text. Thus it would be inaccurate to say all five fail native
compilation, or to classify LLVM's fixture as a Python analyzer implementation
error from that difference alone.

The focused diagnostic compared native compilation, `tokenize.open`, and the
Python analyzer without executing source code. It found no valid-source Python
parser defect warranting a patch. Retain these failures; automatic byte
replacement or exclusions would change what the experiment measures.

### C++ header routing causes real missing symbols

Coverage responses contain 42,059 issues per backend: 32,286 parser diagnostics,
9,767 unsupported-file issues, and six Python target-version diagnostics.
LLVM contributes 29,205 parser issues. Only 11,422 of those paths contain a
`test`, `tests`, or `unittests` component; warnings cannot all be dismissed as
negative test fixtures. Even that path classification does not determine intent.

All **13,262 LLVM `.h` files with recovery warnings** were persisted with
`analyzer_name=c`, and all have **zero indexed symbols**. In r7, the C analyzer accepted
`.h` while the C++ analyzer did not. Both analyzers set
`index_symbols=not root_node.has_error`, so a recovered parse is not a guarantee
that symbols remain available.

A direct witness is `bolt/include/bolt/Core/AddressMap.h`: the recorded C parse
reports errors at C++ constructs such as `std::`, has no indexed symbols or
documentation, and the same bytes parse without errors under the installed C++
grammar. This establishes a routing defect for that file. The census does not
prove that all 13,262 headers are C++, or that rerouting would resolve every
warning. Other production files may depend on macros or unsupported grammar.
LLVM's selected Doxygen witness, `bolt/include/bolt/Core/DebugData.h`, is also
routed to C and has zero symbols and documentation in the retained index.
Its empty audit therefore cannot establish Doxygen rule coverage.

Recommended correction: make header language routing explicit and deterministic,
using declared language/path controls and evidence from neighbouring compilation
units or build metadata for ambiguous `.h` files. Preserve genuine C headers.
Test mixed C/C++ repositories, header-only projects, ambiguity, and compatibility
with analyzer discovery/freshness. Do not simply assign every `.h` file to C++.
Validate symbol and documentation recovery with known declarations, rather than
counting a successful parse alone. The original r7 campaign predates this repair; the implementation and recovered
witnesses are described below.

Unsupported files include YAML, generic JSON, SQL and build formats. Coverage
also scans configured/default roots rather than every repository path. CLDR's
85 indexed files do not represent its millions of lines of generic JSON data:
the JSON analyzer claims particular schema/package/release families. Broader
coverage would require expanding analyzer contracts and/or coverage roots.
`partial=false` for failed selected files can coexist with `complete=false`
for these broader gaps.
The six Python compatibility warnings are distinct from parser failure: pytest's
root declares Python >=3.10 while one integration file uses a 3.12 type alias;
LLVM declares >=3.8 while five files use 3.10 pattern matching. A minimum for
one project does not necessarily describe every auxiliary script. Review
per-path target declarations rather than changing the host interpreter or
raising the entire project's minimum to suppress warnings.

### Empty graph probes include an identity defect

Some chosen functions are leaves, but some empty results were wrong: pytest's
`__call__` corresponds to stored `FastFilesCompleter.__call__` edges, and chi's
`Add` corresponds to `(s *RouteParams).Add`. Inventory names/counters and graph
lookups disagreed about owner qualification. The harness chooses from the first
100 inventory rows without requiring a known edge, so empty results also cannot
prove that an entire repository lacks relationships.

The isolated findings branch now uses canonical method identities in both
backend inventories and resolves short-name graph aliases when exact relations
are absent. Existing exact matches take precedence; defining-file identity and
module/path filters remain significant. Six Python/Go regression cases cover
both backends, CLI and direct MCP adapter behavior. These are post-r7 fixes;
the campaign's original outputs have not been replaced or retroactively graded.
Known-edge benchmark selection remains a separate proposed improvement.

### SVG limits explain eight absent optional outputs

Django, VictoriaMetrics, Twenty and LLVM reached the 60-second Graphviz limit on
both backends. All required reports completed. The findings branch raises the
default to 180 seconds while retaining bounded cleanup and explicit overrides.
This does not establish that all eight huge graphs will finish within three
minutes; smaller subsystem graphs remain a practical option.

### DuckDB overhead has several distinct contributors

| LLVM full indexing | SQLite | DuckDB |
| --- | ---: | ---: |
| Time | 538.19 s | 810.75 s |
| Peak RSS | 3.57 GiB | 14.06 GiB |

Across all 36 repositories the median DuckDB/SQLite full-index ratio is 1.144;
context is 1.104 and incremental indexing 1.047. CLI startup and freshness checks
are included, so these are not isolated database-engine ratios. RSS is maximum
lifetime process RSS including waited descendants, not simultaneous process-tree
memory. No retained result proves an out-of-memory failure.

Read-only inspection of the retained LLVM DuckDB index with DuckDB 1.5.2 found
1,689,550 raw calls and 1,034,688 derived edges. `EXPLAIN` for a 100-symbol
inventory request shows whole-table scans and grouping of calls and references
before joining the limited symbols. Reducing the requested output therefore
does not bound the graph aggregation work.

Both backends fetch raw graph records and deduplicate in Python. DuckDB
additionally sorts and materializes Arrow columns before bulk insertion,
overlapping representations of the graph. Each derived graph table has six
indexes. Official DuckDB documentation also describes ART index memory as
registered but not evictable through ordinary buffer management. These mechanisms
are plausible contributors to the peak, not a measured allocation of its
14.06 GiB: r7 retained no phase-level memory profile. See official DuckDB documentation on
[index memory](https://github.com/duckdb/duckdb-web/blob/main/docs/current/guides/performance/indexing.md)
and [memory-limit boundaries](https://github.com/duckdb/duckdb-web/blob/main/docs/current/configuration/pragmas.md),
retrieved through Context7.

Proposed optimization order:

1. Restrict graph-counter aggregates to the already selected canonical symbol
   identities. Verify counters and incoming/outgoing semantics on both backends.
2. Stream graph rebuild inputs and bounded Arrow batches, avoiding retained raw
   lists plus whole-result sorted lists and column copies. Preserve transaction
   atomicity and deduplication, including null/external target identities.
3. Measure index build/maintenance separately; keep correctness-enforcing unique
   indexes and remove or defer secondary indexes only where plans demonstrate
   redundancy. Add configurable memory/thread limits without promising that a
   database buffer limit caps Python or Arrow allocations.
4. Collect phase timings, process RSS and DuckDB memory tags in a new,
   operator-run experiment before claiming a performance improvement. Do not
   infer those allocations from the campaign's final RSS alone.

Repeated file discovery also costs time outside SQL. JSON content acceptance can
read candidate documents before rejecting unsupported families, which is a
plausible contributor to CLDR's slow queries despite its small selected index.
Phase attribution requires a dedicated profile; it is not established here.

## Evidence and delivered changes

Immutable campaign and previous comparison report:

- Primary checkout `.artifacts/benchmarks/test-material/analyzer-style/analyzer-style-20261010-r7/`.
- Primary checkout `docs/process/local-corpus-analyzer-style-r7-analysis-2026-10-11.md`.
- Primary checkout `.artifacts/analysis/analyzer-style-r7-20261011/analysis-receipt.json`.
- New read-only diagnostics in the primary checkout
  `.artifacts/analysis/benchmark-r7-followup-20261012/`: `coverage-breakdown.json`,
  `header-routing.json`, `header-census.json`, `target-version-issues.json`,
  `duckdb-plan.json`, and source/diagnostic digests in `analysis-receipt.json`.
- Findings worktree `.artifacts/analysis/benchmark-r7-followup-20261012/python-fixtures.json`.

Findings branch was rebased onto current main before edits. Separate commits:
`210eadc` (method identities), `d6c1d11` (180-second SVG default), and
`b497edc` (documented suppression location shifted by the contract documentation).
The primary checkout and running stress environment were not changed by these
fixes. No merge or push is claimed.

Focused validation: 116 tests passed; quality preflight passed. The initial full
gate stopped on the stale documented suppression line; that line was corrected
and its two focused policy tests passed. The second full gate ran 1,583 tests: 1,582 passed and one bundle dependency
assertion retained old backend versions; three tests were skipped. The assertion
was aligned with the actual updated pins in `c5acad4`, and its focused test and
replacement quality preflight passed. The corrected full gate passed: 1,583 tests passed, three skipped, 86% total
coverage, and fresh indexing reported 757 indexed files, zero failures and
zero coverage issues. Its exit status was zero. The durable validation receipt
is findings-worktree `.artifacts/validation/benchmark-r7-fixes-20261011/validation-receipt.json`;
failed gate logs are retained for provenance. The examined successful gate's
temporary log, status file and completed session are cleaned up under the
repository validation policy.

## Implementation follow-up (2026-10-13)

The coverage repair adds optional analyzer path ranking; C++ header inference
and explicit `header_language` controls remain in the plugin. C headers without
C++ evidence retain their previous routing. Real LLVM validation exposed a
second cause: C++ declaration traversal skipped entire header guards. Conditional
wrappers are now traversed without flattening namespace, class or function
scopes; imports, methods and documentation survive guards. Both preprocessor
branches remain static source evidence rather than evaluated build results.

The existing method-identity repair is retained and its SQLite/DuckDB regressions
are rerun with the header tests. DuckDB measurements use a frozen `4272334`
backend source archive and separate worker processes; graph writes use owned
copies of the retained LLVM index. They do not rewrite the r7 campaign.

### Rejected streaming prototype

Transaction-local physical-rowid paging with 16,384-row pages retained identical
LLVM graph signatures, but its first comparison took 36.62 seconds versus
27.78 seconds for the original rebuild (+31.8%). Peak worker RSS decreased from
2,530,832 to 2,037,128 KiB (-19.5%). The slower paging implementation is removed;
a memory benefit alone does not satisfy the requested no-degradation condition.
Native connection Arrow readers also stop after another execute on that same
connection, so interleaving such a reader with stage inserts is not safe.
A transaction-local native snapshot with bounded independent Arrow reads was
also tested below.

The independent uncompressed Parquet spool also preserved both LLVM graph
signatures, but took 38.03 seconds (+36.9%) and peaked at 2,115,500 KiB (-16.4%).
It is removed too. The original graph rebuild is restored; no slower streaming
implementation is retained. Its rejected source and test are preserved with the
measurement receipts. Batching adds native deduplication, repeated Arrow import
and/or snapshot costs that must be eliminated before this approach is viable.


### Retained inventory optimization and resource controls

Three alternating pairs on the frozen LLVM index returned identical 100-row
inventories, including every incoming/outgoing counter. The baseline median was
54.86 seconds; the candidate median was 0.346 seconds (about 159 times faster).
The first pilot was 56.02 versus 0.417 seconds. This baseline is the **post-r7**
backend source `4272334`, including the canonical method-identity repair; it is
not the original r7 backend 2.0.2. The repair had introduced an expensive
conditional join between all symbols and method owners. The optimization joins
owners only for method rows, and restricts graph aggregation to the selected
canonical identities. Counts still include relations to symbols outside the
returned limit or path prefix. SQLite/DuckDB regressions check limits and prefixes
against the full inventory as well as independently asserted known counters.

Optional `[plugins.backend-duckdb]` `memory_limit` and `threads` controls apply
to initialization and cached read/write connections. Omission retains engine
defaults; changing them closes this backend's cached handles. Native DuckDB
validates size units, and failed opening does not cache a broken connection.
These controls do not cap Python/Arrow/process RSS and are not a speedup claim.
Backend distribution 2.0.4 and official bundle 2.0.11 carry aligned dependency
pins. Installer 2.0.1 carries the regenerated catalog for both new header and
resource options. Physical schema 25 remains unchanged after the rejected layout experiment.

### Rejected secondary-index layout

Removing the ten non-unique graph indexes, while retaining both identity
uniqueness constraints, reduced the three-pair rebuild median from 27.09 to
23.92 seconds (11.7%). Peak RSS remained approximately 2.4 GiB. Full
`EXCEPT ALL` comparisons in both directions found zero different rows in either
graph table, beyond the matching count/hash signatures. An extra single-column
caller-name index did not change the inspected scan plan.

However, repeated incoming-call queries increased from 43.55 to 45.01 ms for a
ten-target group (+3.35%). Outgoing calls improved in that repeat, and unresolved
aggregation improved in the initial comparison. With the requested
no-degradation rule, the complete layout change was conservatively reverted;
the original secondary indexes and schema are retained. Concurrent operator
stress work prevents definitive attribution of these small query differences,
but the evidence does not justify claiming every query improved. The faster
rebuild alone was insufficient for acceptance.

### Interpretation and reproduction

Measurements and exact package-source snapshots are retained in the findings
worktree `.artifacts/benchmarks/backend/duckdb-r7-optimizations-20261012-r1/`.
`measurement-summary.json` records repeated pairs and evidence digests;
`index-layout-equivalence-and-queries.json` records complete graph equivalence;
`index-layout-point-queries-repeat.json` retains query timings and plans.
Rejected streaming source/tests and database copies remain in the same folder.
All graph writes used owned copies; the original r7 campaign remains unchanged.
Operator stress embeddings continued concurrently, and some focused checks
overlapped samples. These are paired component observations, not an idle-host
performance qualification. RSS covers each worker's lifetime through the timed
operation; the graph replay excludes parsing, full indexing and CLI startup.
No improvement to the original 810.75-second / 14.06-GiB full-index result is
established, and no entire benchmark campaign was launched.

From the findings worktree, an operator can repeat one native inventory sample
with a **new output name** (existing evidence is never overwritten):

```bash
uv run --offline --no-sync python \
.artifacts/benchmarks/backend/duckdb-r7-optimizations-20261012-r1/worker.py \
--variant candidate --operation inventory --limit 100 \
--source /home/marco/Personalia/Progetti/Software/Python/codira/.artifacts/benchmarks/test-material/analyzer-style/analyzer-style-20261010-r7/indexes/duckdb-structural-cpp-llvm-project/.codira/index.duckdb \
--repository-root /home/marco/Personalia/Progetti/_Third-Party/Test_material_codira/cpp/llvm-project \
--output .artifacts/benchmarks/backend/duckdb-r7-optimizations-20261012-r1/operator-inventory-new-01.json
```

Use `--variant baseline` with another new output name for the frozen baseline;
`--operation graph` rebuilds a new owned database copy and retains it beside its
receipt. A failed attempt's outputs remain evidence: choose a new name rather
than deleting or replacing them. Wait until the operator stress run finishes
before a controlled performance comparison. Resources, host load, output limit,
prefix and code snapshots must accompany interpretation.

Final real-header evidence is retained under
`.artifacts/analysis/header-routing-20261012/`: direct analysis recovers three
classes and five methods from AddressMap, and 17 classes, five free functions
and 98 documentation artifacts from DebugData. The original routing-only and
nested-discovery attempts are retained. `llvm-persisted-witnesses-isolated.json`
uses independent disposable source roots and proves the two files produce 176
inventory entries in total on each structural backend, with zero failures. This repairs
known positive witnesses; it does not prove all 13,262 warned headers are C++ or
resolve macro-dependent syntax and unsupported-file coverage.


### Completion validation

Coverage repair: `af5c5f3`; existing graph identity repair: `210eadc`; retained
DuckDB optimization, budgets, installer catalog and aligned distribution pins:
`dd7bc43`. All are on `fix/benchmark-findings`; no merge or push was performed.

Focused validation passed 83 backend/graph/header/bundle tests and 36
installer/resource/contract tests. The final quality preflight passed fresh
indexing, Ruff, formatting, root and package typing, 21 Semgrep rules, and the
documentation audit. Frozen benchmark history reported no missing revisions.
The first completion gate found generated installer catalog drift (1,625 tests
passed, one failed, three skipped); it was regenerated through
`scripts/generate_installer_catalog.py`, with installer 2.0.1 and its root pin
aligned. The corrected required full gate passed: **1,626 passed, three skipped,
86% coverage, exit zero**. Its fresh index covered 760 tracked files with zero
analysis failures and zero coverage issues.

The durable completion receipt is
`.artifacts/validation/duckdb-r7-optimizations-20261013/validation-receipt.json`;
preflight attempts and the failed gate log are retained. The examined successful
gate's temporary session, log, status and launcher are cleaned under the
repository policy after their result and digest are recorded. The primary
checkout, original campaigns and operator benchmark processes were preserved.
