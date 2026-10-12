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
`analyzer_name=c`, and all have **zero indexed symbols**. The C analyzer accepts
`.h`; the C++ analyzer currently does not. Both analyzers set
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
counting a successful parse alone. This routing change is a proposal, not an
implemented change in this follow-up.

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
