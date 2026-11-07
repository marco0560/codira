# C caller-header context and record-prefix recovery

The dedicated fix branch adds explicit contained header context to the C analyzer.
It recovers declaration annotations and function specifiers, plus source-backed
plain data-field prefixes in records. C data fields are outside the emitted
artifact model; their original written bytes still supply source signatures.
Nested types, constants, arrays, function fields, expressions, conflicting
alternatives, undefinitions and late definitions remain outside this projection.
Recovery requires a wholly clean final tree.

Logical C analyzer version is **16**, distribution **2.0.6**, official bundle
**2.0.38**, and installer **2.0.5**. The installer catalog is regenerated from its
generator. Header bytes, failed lookups, selected paths, search/context order,
symlink targets and configuration participate in incremental identity. Context
headers are opt-in and must remain inside the indexed repository. No compiler or
build command runs during analysis, and conditional branches are not selected.

## Profiles and complete original-file measurement

The complete source-hash-checked cohort has **416 previously open historical C
files**: the union of the pending CPython object-layout and PostgreSQL export
annotation marker groups, including four PostgreSQL Python-layout consumers.
Token overlap selects the cohort; it does not establish a causal recovery.

Profiles are relative to each unchanged repository root:

| Repository | `include_search_paths` | `preinclude_headers` |
| --- | --- | --- |
| CPython | `['Include', 'Include/internal']` | `['Include/Python.h']` |
| PostgreSQL | `['src/include']` | `['src/include/postgres.h']` |

An original C15 source copy from parent commit `bb8da5b` provides the baseline.
The three actual public-analyzer measurements are:

| Analyzer/profile | Clean parses | Partial parses | Exceptions |
| --- | ---: | ---: | ---: |
| C15 defaults | 16 | 400 | 0 |
| C16 defaults | 16 | 400 | 0 |
| C16 explicit caller/include context | 270 | 146 | 0 |

This is **254 new configured parser recoveries**, with no new default-profile
recoveries in this cohort. Implementation and analysis context intentionally
differ from the baseline. This is not a clean default full-benchmark claim.
Complete canonical artifacts and configured dependency identities are retained.

Earlier bounded probes justify this scope: header lookup plus annotation recovery
alone recovered **0 additional files in 15**, adding function specifiers and
record-prefix handling recovered **1**, and explicit caller context recovered
**22 additional originals in a 40-file spread**. Those probes are not population
estimates or admissions.

## Independent native evidence

Native checks use Clang **22**, explicit **C17** host contexts, separately
configured CPython/PostgreSQL build directories, and PostgreSQL's source-declared
`generated-headers` target. The original source repositories are not configured or
built in place. PostgreSQL's configured `CPPFLAGS` supplies `-D_GNU_SOURCE`.

An independent native frontend can select the original target file within an
actual consumer translation unit. Clinic headers use their recorded original C
consumer when present; other headers use an explicit caller wrapper, including
public CPython wrappers for internal `Include/cpython` headers. Both main-file
and included-target checks match complete unfiltered native AST comparisons.
A target not parsed by its consumer fails explicitly. No product artifact selects
native declarations, and this tool is used only for QA.

The corrected complete native batch accepts **348**, rejects **68**, and has
**zero timeouts**. One target is absent in its selected consumer. Rejections include
missing optional/project headers, platform SDKs and mismatched consumer roles;
they do not establish malformed or future source.

The first native batch rejected all 416 because the QA command omitted the
compiler resource directory. Its output is retained. Focused retained-command
checks identified that issue, then PostgreSQL's required configured preprocessor
flag. The corrected commands pass both smoke cases before the fresh native batch
runs. These are QA setup failures, not product defects.

Of the 270 configured-clean files, **226** also pass native compilation and receive
complete comparison. The unchanged R4 comparison qualifies **62**. Its C typedef
name-line helper can incorrectly select an earlier struct tag instead of the
trailing alias declarator. The C-only R5 extension uses the native declaration
range and literal alias location, requiring the product's declaration start and
normalized written signature to match that exact source declaration. It does not
change callable, parameter, call, prototype or other type comparisons.

R5 qualifies **93 originals**, including all previous 62, with **zero qualification
regressions**: **66 PostgreSQL** and **27 CPython** files. Their checked fields match
**25 definitions, 1,057 callables, 1,032 prototype parameter lists, 27 lexical call
sites and 305 named-type identities**. **92** are new configured parser recoveries; **one** already parsed
cleanly under C15 and now receives independent qualification. The other compared
records remain held, notably for parameter identity, lexical call-site, declaration
and type mismatches. Groups overlap. Repeated `Py_UNUSED` and `PG_FUNCTION_ARGS`
parameter mismatches are retained for the next correction batch.

Qualification checks source-owned callable identities/method kinds/name lines,
parameter names, lexical call-site sets, named types and represented prototype
redeclaration chains. Typedef source-range/signature matching proves the alias
name-line mapping. Data fields, constants, complete function signatures,
visibility/attributes, ABI/runtime and original project-harness equivalence remain
outside this qualification. No valid call or declaration is removed to fit a
reference limitation.

## Validation and nonregression

The C suite passes **137 tests**, and the combined C, bundle, installer, contract
and benchmark-runner surface passes **228**. Tests cover original signatures,
UTF-8 byte positions, CRLF, leading annotations/BOM, conditional signature views,
source availability, invalidating directives, safe field scope, path confinement,
transitive includes/cycles, lookup precedence and actual SQLite invalidation when
header bytes change at fixed mtime.

Three actual C17 macro-context controls qualify; seven deliberately wrong-artifact
controls remain rejected. Two actual typedef controls plus seven altered metadata
controls validate the R5 extension. The previously verified **188 historical C
files retain complete canonical artifact equality** between C15 and C16 defaults,
with no parser failures or exceptions; their previous qualification scopes remain
unchanged.

The inexpensive preflight passes all eight checks. The full gate passes **2,214
tests with 3 skipped**, **87%** coverage and a fresh **853-file index** without
failures or coverage issues. Semgrep runs outside the sandbox. The first preflight
findings required an explicit parser-factory re-export and exception documentation;
the failed check record is retained. The leading-annotation regression also found
and corrected the translation-unit byte-zero signature boundary.

## Ledger and durable evidence

Commit `bdfc777` records the implementation and source-bound validation.
The authoritative ledger is now **v26: 2,152 verified fixes, 453 separated files
and 23,157 open paths**, or **10.11% accounted**, up from **9.75%**. Admission adds
only the **93** source-bound, native-qualified originals; the 254 parser recoveries
are not counted as 254 verified fixes. Remaining historical ownership is **5,804 C**
and **17,353 C++** files. The complete objective remains open, and all separated
language/version/repository records remain unchanged.

All evidence below is under
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `c-header-context-production-r1/`: complete 416-file three-profile replay.
- `c-header-context-native-r1/`: failed resource-directory setup, retained intact.
- `c-native-resource-smoke-r1/`, `c-native-resource-smoke-r2/`: focused diagnosis
  and corrected compiler resource/preprocessor checks.
- `cpython-native-context-r1/`, `postgres-native-context-r1/`,
  `postgres-native-generated-headers-r1.log/.exit`: isolated native contexts.
- `native-target-source-dump-tool-r1/`, `native-target-dump-controls-r1/`: target
  selection utility, build recipe, full-reference parity and absence rejection.
- `c-header-context-native-r2/`: all corrected native captures and consumers.
- `c-header-context-grading-r1/`, `c-header-context-grading-r2/`: complete retained
  R4 and C-only R5 comparisons, including held records.
- `c_header_native_oracle_r5.py`, `c-typedef-oracle-controls-r1/`: exact typedef
  source-proof extension and controls.
- `c-header-context-native-controls-r2/`: actual C16/native macro-context controls.
- `c-qualified-c16-r1/`: all 188 previous complete-artifact comparisons.
- `c-header-context-focused-r4.log/.exit`, `c-header-context-focused-r5.log/.exit`,
  `c-header-context-quality-r2.log/.exit`: focused validation and final preflight.
- `c-header-context-validation-receipt-r1.json`: full gate and source binding.

- `classification-v26.jsonl`, `classification-v26.csv`,
  `classification-summary-v26.json`, `admit_c_header_context_r1.py`,
  `c-header-context-admission-r1.json`: complete ledger, separated groups, generator
  and source/native/payload/configuration-bound admission receipt.
