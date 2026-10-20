# Native source origins and 71 verified statement-macro originals

The full 25,762-file remediation goal remains active. Classification v56 records
**4,207 verified fixes, 680 separately classified inputs and 20,875 open files**
(C: 5,551; C++: 15,324). Verified fixes represent 16.33% of the original population;
fixed plus separated represents 18.97%. The original v38 baseline and all raw,
failed and superseded evidence remain preserved.

This phase admits 71 actual originals made analyzable by the committed
[source-backed statement correction](analyzer-parser-diagnostics-statement-macros-2026-10-20.md).
Production source commit remains `665412912b31e024bd244a528136a35c6fdcc71a`:
C++ logical version 27, distribution 2.0.28, official bundle 2.0.54. No production
Python, package metadata, compiler profile or original corpus source changed.

## Shared native verification corrections

The earlier native macro-origin helper accepted uppercase function-like names
only. The replacement proves lowercase invocations from captured native cursors,
physical source spans, reaching definition bytes and coordinates. It distinguishes
source argument calls from generated `__assert_fail` operations. Native macro
provenance remains separate from the analyzer-owned name-based rendering
classifier; lowercase `assert` retains its documented external classification.

A corruption control exposed an older span weakness: shortening an invocation to
an inner closing parenthesis was accepted. Exact balanced invocation checks now
reject that case while respecting strings, raw strings, comments and digit
separators. Standard `assert`, `NDEBUG` erasure and source redefinition have
separate native controls. Erased argument calls are never excused.

General source-owned macro-argument ranges now cover overloaded operators and
explicit constructions. Command-line namespace origins are recovered first.
A macro that manufactures a call from a bare argument remains a hold. Source
coordinates, type spellings and expansion ownership must be proven; unresolved
native template lookup names require matching native lookup declarations.

Clang also emits template patterns and instantiated copies at the same source
name position. The previous dictionary comparison could select an instantiated
copy. The controlled written-template view removes only template siblings at the
pattern's same physical name site. Explicit source specializations remain.
Neither original raw ASTs nor previous helper versions are overwritten.

## Qualification and admission

The same 344 eligible originals were regraded from retained native and
preprocessing evidence, without recompiling the cohort. Preliminary passes rose
from 27 to 33, then 67, then **71** after source-template selection. All original
67 candidates survived the final audit; four additional files qualified.

The final comparison retains the established r11 inventory, parameter and
bodyless-definition checks, qualified namespace/type/callable identities,
physical signatures and body ends. Calls compare six fields, including external
target name. Rendering classifiers are checked separately against the documented
static policy. Ten deliberate metadata corruptions are rejected through the
actual qualification path.

Actual CLI indexing succeeds for all 71 originals with both SQLite and DuckDB.
All **142 per-original storage comparisons pass**, covering modules, classes,
functions and ownership, overloads, declaration identities, imports, all call and
callable-reference fields, generated provenance and analysis-input fingerprints.
The two indexes together contain 300 functions, 24 classes and 3,038 call records.
Deferred embeddings and retrieval ranking are outside this qualification.

Admission binds original source hashes, native ASTs and dependencies, macro
origins, written-template selection receipts, production metadata, controls and
both actual indexes. The source-bound full repository gate remains applicable:
2,739 passed, three skipped, 88% coverage, zero indexing failures or coverage
issues. Every bound production source and runtime digest was rechecked. The
2,700-case regression for 1,350 earlier admissions remains unchanged.

An independent ledger audit confirms exactly 71 changed rows, 25,691 unchanged
rows, unchanged 680 separated decisions and preserved immutable original
identities across all 25,762 paths. These are verified file admissions; helper
controls and clean parses contribute no additional files.

## Next shared cause

Of the 273 held files in this cohort, **212 contain 835 distinct producer source
call sites missing from the native inventory inside captured `ASSERT_SAME_TYPE`
spans**. This is a candidate grouping, not 212 proven fixes or 835 analyzer bugs.

A focused native control accepts ordinary calls and calls within unevaluated
`decltype` type operands. JSON exposes the ordinary call but omits calls when the
operand appears as a `std::is_same` template argument. A retained earlier probe
using the direct `__is_same` builtin exposes those calls, establishing the exact
serialization boundary instead of a blanket unevaluated-expression claim.

Next investigate native type-location expression capture under the same compiler
profile, independently control it, and supplement the retained AST evidence.
Preserve written-template ownership, physical source provenance and all existing
metadata checks. Regrade the full held cohort before deciding which residuals
require production corrections. The larger C/C++ backlog remains in scope.

## Durable evidence

All identities below are under the dedicated worktree's
`.artifacts/analysis/parser-diagnostics-20261017-r1/` directory.

- `classification-v56.jsonl`, `classification-summary-v56.json`,
  `cpp27-statement-71-admission-v56-r1.json`, and
  `cpp27-statement-71-admission-audit-v56-r1.json`.
- `cpp-lowercase-native-origin-controls-r1/r2`,
  `cpp-native-argument-range-controls-r1/r2/r3`, and
  `cpp-native-written-template-controls-r1`.
- `libcxx-assert-344-native-grading-r2/r3/r4`,
  `libcxx-assert-qualified-cli-r1`, `libcxx-assert-extra4-qualified-cli-r1`,
  their 67-file and extra-four storage verifications, and
  `libcxx-assert-71-qualification-controls-r1`.
- `cpp-native-type-expression-visibility-r1/r2` and
  `libcxx-assert-type-expression-gap-ranking-r1.json`.

Failed controls and superseded measurements remain retained. No merge, push,
main-checkout modification, evidence cleanup or sub-agent work occurred.
