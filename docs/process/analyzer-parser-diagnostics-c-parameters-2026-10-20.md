# C parameter identities and source macro-call qualification

The dedicated fix worktree now admits **46 additional original files: six
PostgreSQL and forty CPython files**. Ledger v27 contains **2,198 verified fixes,
453 separated files and 23,111 open files**: **10.29% accounted for**. The remaining
languages are C (5,758 files) and C++ (17,353 files). The full correction objective
remains open; this is not a clean bill for the original benchmark.

The source fix is commit `a3982b0` on `fix/analyzer-parser-diagnostics`. Main remains
at `91c4e07`. No merge, push, release publication or original-campaign mutation was
performed. The malformed/future-syntax classifications and their language,
version and repository groups remain unchanged; see the [separation report](analyzer-parser-diagnostics-verify-prefixes-2026-10-19.md)
and the complete grouped `classification-summary-v27.json` evidence.

## Shared production fix

C17 recovers parameter names from captured source/header macro definitions. Plain
object parameters such as PostgreSQL's `PG_FUNCTION_ARGS` recover `fcinfo`.
Compatible single-identifier wrappers such as CPython's `Py_UNUSED(name)` recover
`_unused_name`, including pointer declarators, token pasting, GNU attributes and
MS pragma alternatives. Every captured alternative must agree. Conflicting
replacements, undefinitions, macro-dependent identities, larger expressions and
unsupported wrappers retain the original extraction result.

Definitions respect their source/include availability boundary. Runtime analysis
selects no conditional branch and invokes no compiler. Original signatures,
function positions and call records remain unchanged. Logical C analyzer version
17, distribution 2.0.7 and official bundle 2.0.39 invalidate stale analysis and
keep installation pins aligned; the configuration schema is unchanged.

The complete 416-file historical cohort was replayed with the same explicit
profiles as the [preceding header-context phase](analyzer-parser-diagnostics-c-header-context-2026-10-19.md):

| Repository root | Include roots | Preincluded header |
| --- | --- | --- |
| CPython | `Include`, `Include/internal` | `Include/Python.h` |
| PostgreSQL | `src/include` | `src/include/postgres.h` |

Configured parsing remains clean for **270 files**, with no exceptions. Compared
with retained C16 configured artifacts, **160 files change only parameter names,
covering 1,179 parameter lists**. This phase does not claim an increase in parser
recovery over C16 or a fresh default-profile benchmark. All 188 earlier qualified
C artifacts retain complete byte-for-byte payload equality under their unchanged
default profiles.

## Independent call-reference correction

The previous compiled-AST reference did not consistently represent the analyzer's
source call graph: it lost written macro invocations whose replacements were
noncalls, and could invent a call at an object macro such as `errno` without
written parentheses. Controls also exposed a nested alias being attributed to its
macro definition instead of the function body. Removing the analyzer's valid
source calls would have concealed these reference defects.

The C-only R9 reference combines the retained Clang AST with independently
captured Clang preprocessor events. It requires exact original macro-name bytes,
source-file ownership, native function-body ranges, declaration-binding checks and
the accepted compiler/consumer/profile. Ordinary call-shaped tokens inside macro
arguments that lack native coverage remain an explicit limitation. Directive
conditions and inactive-branch differences are not silently accepted.

Across **226 configured-clean, native-accepted originals**, all non-call R5 issue
lists and comparison counts remain identical. Parameter mismatches fall from 70
to zero; lexical call mismatches fall from 110 to 60. The groups overlap with
other held issues: 24 files have unmapped declarations, 18 have named-type
mismatches and 14 have definition mismatches. Native acceptance and parser
cleanliness alone do not qualify these files.

The corrected reference qualifies **139 files**, retaining every one of the
previous reference's 95 qualifications. The existing ledger already admitted 93;
the remaining **46** pass the new source-bound admission audit. Of those 46,
**26 require the parameter correction** and **20 already had correct C16 artifacts
that are now independently qualified**. All 46 are recovered relative to the
retained historical C15 default baseline; that baseline/profile distinction is
intentional.

The admitted subset covers 518 definitions, 1,044 callables, 526 prototype
parameter lists, 2,670 lexical call sites and 39 named types. This verifies the
stated normalized-artifact scope, not data fields, complete native signatures,
ABI, runtime behavior or original project-harness equivalence.

## Validation and retained failures

The final repository gate passes **2,235 tests, three skipped**, with **87%
coverage** and a fresh **856-file index**, no index failures and no coverage
issues. Final preflight passes all eight checks; Semgrep runs outside the sandbox
and reports zero findings. The focused C/bundle/root-contract surface passes 160
tests. The atomic source commit passes the repository hooks.

Three native parameter profiles agree with Clang, including pointer parameters;
four wrong parameter sets are rejected. The final source-macro controls contain
nine qualifying cases and six intentionally held cases. All **61 wrong-artifact
controls** are rejected, including missing calls erased or stringified inside
macro arguments. Non-call checks remain enforced.

The preliminary gate failed one stale dependency-pin assertion, expecting 2.0.6
after the 2.0.7 bump. It was corrected before the passing final gate. Its failed
log and exit status are retained. An initial native event capture was rejected
before admission because 29 macro-name strings had lifetime corruption. The
corrected capture owns its JSON strings and verifies all **18,625 events across
226 sources** against original bytes. Earlier failed controls and captures remain
unchanged; they are not admission evidence.

A separate production issue was exposed by the directive control: a macro in a
`#if` condition can be recorded as a body call. That case remains unqualified and
is pending a source-call extraction fix. Other inactive-branch and declaration
context limitations also remain held, rather than being classified as malformed
or future syntax.

## Durable evidence

All raw evidence and generators remain under
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `c-parameter-macros-production-r3/`: complete current artifacts and dependency identities;
- `c-qualified-c17-r2/`: unchanged earlier C qualifications;
- `c-parameter-macros-grading-r3/`: unchanged R5 comparison after the production fix;
- `c-macro-invocations-native-r2/`: corrected source-bound native events;
- `c-source-macro-grading-r3/`: final R9 comparison, preserving non-call checks;
- `c-source-macro-reference-controls-r4/` and `c-source-macro-reference-negative-r3/`: final positive, held and wrong-artifact controls;
- `c_source_macro_native_oracle_r9.py`: exact independent reference implementation;
- `c-parameter-macros-validation-receipt-r1.json`: examined final gate and source hashes;
- `c-macro-invocations-r1-rejection.json`: rejected capture explanation and affected records;
- `c-parameter-source-calls-admission-r1.json`: per-file admission bindings and evidence hashes;
- `classification-v27.jsonl`, `classification-v27.csv` and `classification-summary-v27.json`: full ledger and language/version/repository groups.

Next work should continue to rank shared causes by the number of fully cleared
files, keeping isolated edge cases last. None of the remaining 23,111 files is
implicitly waived by this phase.
