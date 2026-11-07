# Analyzer main-r1: exit 2 investigation

The analyzer benchmark completed its execution plan with **zero failed stages
and zero command timeouts**. Its exit code **2** reports usable partial coverage.
The operational acceptance target was met; complete repository analysis and
semantic correctness were not established.

## Run and retained evidence

The reviewed run is
`.artifacts/benchmarks/test-material/main-verification-20261016-r1/analyzers/runs/main-r1/`.
Its launch receipt is `analyzers/launches/20261017T002619987567064.exit`, relative
to the same preparation directory, and contains `2`. The final summary records
`execution_complete=true`, `complete=false`, and `coverage_complete=false`.
The source commit is `91c4e07a3c25e72ee7c3346899f92e551037bf5e`, with installed
and generated Codira versions both `2.4.7.post1.dev1`. SQLite backend 2.0.3,
DuckDB backend 2.0.5, and C++ analyzer 2.0.1 are recorded in the identity.

The run used Python 3.13.13 on the recorded Intel Core i7-8700K host, with 12
logical CPUs and Gentoo Linux 6.18.54. Embeddings were disabled. The whole
architecture-command limit was 300 seconds; optional SVG layout had 180 seconds.

The derived analysis, input SHA-256 digests, comparisons, exact source failures,
and per-repository coverage counts are retained in
`.artifacts/analysis/analyzer-main-r1-20261017/analysis-receipt.json`.
Analysis read completed JSON/log/artifact files; it did not open databases,
rerun stages, refresh indexes, change runtime/configuration, or touch the running
stress campaign. Evidence digests were checked again after reading.

## Accounting and why the launcher returned 2

| Outcome | Stages |
| --- | ---: |
| Passed setup/prerequisites | 146 |
| Usable partial, with results | 828 |
| Usable partial, empty result | 164 |
| Excluded | 6 |
| Failed or command timeout | 0 |
| **Total** | **1,144** |

There are 1,138 measured stages and 2,458 process samples. All 72 repository/backend
indexes are usable: each backend indexed 134,395 of 134,400 selected files across
36 repositories, with five source failures. These are the same files counted
once per backend, not ten different failed sources.

`campaign_exit_status` in `scripts/run_test_material_benchmarks.py` returns 1
for failed commands, 2 when any stage has partial coverage, and otherwise 0.
This run takes the partial-coverage branch. Coverage gaps propagate their label
to dependent queries, even when the individual command exits successfully.
The 992 repository measurement stages are all in the partial-coverage cohort;
the complete-index cohort contains only the 146 prerequisites.

Of the process samples, 2,118 exited 0 and 340 exited 1. Every exit-1 sample is
classified `partial_empty`, the supported no-match outcome. None is a hidden
failed stage. Empty graph/reference/audit selections remain operational evidence,
not proof that all relevant relationships or documentation findings were found.

## The five failed files are unchanged negative fixtures

| Repository | Repo-relative source | Retained diagnosis |
| --- | --- | --- |
| Django | `tests/test_runner_apps/tagged/tests_syntax_error.py` | Deliberate `1syntax_error` statement |
| CPython | `Lib/test/tokenizedata/bad_coding.py` | Invalid encoding cookie `uft-8` |
| CPython | `Lib/test/tokenizedata/bad_coding2.py` | Encoding/BOM problem |
| CPython | `Lib/test/tokenizedata/badsyntax_pep3120.py` | Invalid or missing encoding declaration |
| LLVM | `llvm/utils/lit/tests/shtest-encoding.py` | Invalid UTF-8 byte sequence |

Both backends retain the same five paths and diagnoses as analyzer-style r7.
No new source-failure path appears. The
[earlier investigation](local-corpus-analyzer-style-r7-followup-2026-10-12.md)
records their negative-fixture context. Their successful neighbouring files
remain queryable.

The six exclusions are incremental indexing for Django, CPython, and LLVM on
each backend. Their reason is `unchanged deterministic failures are not
automatically retried`. No repository query group was excluded. Retrying these
unchanged fixtures is not a recovery action; excluding them would change the
benchmark scope and require another explicitly scoped run identity.

## Remaining coverage and rendering limitations

Each backend's coverage outputs contain 35,540 issue rows:

| Category | Current | R7 |
| --- | ---: | ---: |
| Parser diagnostics | 25,762 | 32,286 |
| Unsupported file/content combinations | 9,767 | 9,767 |
| Python target-version diagnostics | 6 | 6 |
| Failed-source rows | 5 | 5 |
| **Total coverage output rows** | **35,540** | **42,064** |

This comparison counts the complete `cov` result lists, including five
failed-source rows. The earlier report's 42,059 issue figure excluded those five
rows; the figures should not be compared without that distinction.
LLVM still contributes 22,692 parser diagnostics. Unsupported content and parser
recovery are real limits of measured analysis coverage; these warnings must not
all be dismissed as deliberate test fixtures. Fewer diagnostics do not by
themselves prove recovered symbols and relationships are correct.

All **72/72 mandatory architecture report sets** exist. **70/72 optional SVGs**
exist, compared with 64/72 in r7. Only Django, on both backends, exceeded the
180-second Graphviz layout budget. Mandatory DOT, Markdown, dependency, hotspot,
and violation files survived, and both commands exited successfully. This is a
remaining optional-layout scalability limit, not a whole-command timeout.
LLVM now produces its SVG on both backends. The increased SVG budget is part of
this comparison and prevents attributing every recovered SVG to faster code.

## Comparison with r7 and timing interpretation

All 36 pinned corpus revisions and all 72 configuration-file contents match r7.
Runtime/plugins changed, and the SVG budget increased from the earlier 60-second
limit to 180 seconds. Host load and cache states were not controlled.

Empty stages decreased from 192 to 164: 28 formerly empty graph/reference stages
now return results. Target identities and sometimes selected symbols changed;
for example pytest now probes `FastFilesCompleter.__call__` rather than the
unqualified `__call__`. This is useful observed recovery, not a fixed-target
semantic evaluation of every graph result.

Summed process sample time was **8,281.96 seconds (2 h 18 min 2 s)**, versus
7,429.47 seconds in r7, an 11.5% increase. Architecture samples alone added
933.90 seconds; full-index samples decreased by 111.86 seconds. More time spent
on bounded rendering with a larger budget is a changed workload control.
Across paired stages, median current/r7 mean-time ratios are 0.993 for full
indexing, 0.981 for context, and 0.986 for architecture. These descriptive
figures do not establish a general speedup or an uncontrolled regression.

## Detailed coverage follow-up

The 25,762 parser issue rows are 25,762 distinct file paths per backend.
Of these, 25,686 report Tree-sitter recovery and 76 report error syntax.
Their concentration is LLVM 22,692, PostgreSQL 1,157, CPython 853, Twenty 373,
Redis 352, Catch2 156, and 179 across other repositories. Extensions are led by
12,354 `.cpp`, 7,729 `.h`, 4,635 `.c`, and 456 `.hpp` files. The CPython repository
count includes C implementation files; it is not 853 failed Python modules.

These are not merely cosmetic warnings. C, C++, and TypeScript analyzers return
`index_symbols=false` when the parsed root has errors. Their partial status
withholds module, class, function, declaration, import, and documentation
categories, and the backend honors that flag. The source file can therefore
count as successfully processed while lacking searchable symbol artifacts.

Three small direct analyzer probes confirm this behavior without indexing or
persistence. `inih/cpp/INIReader.cpp` extracts 18 functions but withholds symbol
indexing. `INIReader.h` extracts two declarations and also withholds indexing.
Twenty's `SettingsCardContentBase.tsx` extracts five declarations with the same
restriction. Their source digests and exact returned flags/categories are in
`direct-parser-witnesses.json` under the derived analysis directory. These probes
use default analyzer configuration and are not a replay of every campaign
routing choice or an independent semantic oracle. Macros, preprocessor branches,
grammar limits, and intentionally malformed tests require separate attribution;
the warning text alone does not establish the cause for each file. Production
paths including LLVM's `bolt/include/bolt/Core/BinaryContext.h` and PostgreSQL's
`contrib/amcheck/verify_heapam.c` occur in the recorded diagnostic list.

The 9,767 unsupported rows are also distinct paths. Their common reason is
`no registered analyzer accepts this file type/content combination`. Leading
types include YAML/YML 2,480, JSON 2,050, expected-output `.out` files 614,
translation `.po` files 515, `.link` files 459, SQL 458, Perl 341, and TOML 270.
Unsupported files are concentrated in PostgreSQL 3,003, SchemaStore 2,796,
Helm 845, Redis 712, and PDF.js 711. These are coverage-scope exclusions rather
than parser crashes. The counts describe the recorded coverage scope, not every
file in the original repositories.

The JSON plugin intentionally recognizes schemas, npm package manifests,
semantic-release configuration, and conservative generic manifests rather than
arbitrary JSON. Of SchemaStore's 1,553 unsupported JSON files, 1,029 are under
`src/test`, 507 under `src/negative_test`, and 17 under `src/schemas`.
All 17 schema-directory files are parseable objects containing only `$ref`,
including `block.json`, `renovate.json`, and `semgrep.json`. That shape does not
satisfy the current schema recognizer's marker rules. This is a specific
reference-wrapper recognition boundary to review, rather than grounds for
treating every unsupported JSON file as broken input or enabling generic JSON
indexing indiscriminately. Detailed counts and source hashes are retained in
`coverage-detail-summary.json`; the complete issue list is in
`coverage-issue-detail.json` in the derived analysis directory.

## Disposition

No new command failure, timeout, or failed source path was found to repair.
Keep the original failure and coverage evidence; do not retry simply to obtain
exit 0. Complete coverage would require separate analyzer/coverage work and a
declared corpus scope. Django's optional SVG remains bounded and incomplete.

This investigation made no implementation change and launched no tests or
benchmark work. At the time, the report was left uncommitted while stress ran,
so its recorded source revision and resume identity remained unchanged. Stress
execution and semantic/task-success results remain outside this analyzer verdict.
