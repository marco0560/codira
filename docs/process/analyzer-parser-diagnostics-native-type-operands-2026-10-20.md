# Native type operands and 142 additional verified originals

Classification v57 records **4,349 verified fixes, 680 separately classified inputs
and 20,733 open files** across the original 25,762 paths. Open attribution is
C: 5,551 and C++: 15,182. Fixed-only progress is 16.88%; fixed plus separated is
19.52%. The complete remediation goal remains active, including the original
v38 baseline, all languages and repositories, and every remaining supported file.

This phase admits 142 actual originals through stronger independent native
qualification of the existing statement-macro correction. Production source
remains `665412912b31e024bd244a528136a35c6fdcc71a`: C++ logical version 27,
distribution 2.0.28 and official bundle 2.0.54. No production Python, package,
runtime or original corpus source changed.

## Shared evidence correction

The [previous source-origin phase](analyzer-parser-diagnostics-native-source-origins-2026-10-20.md)
identified 212 held originals with source calls inside captured type-assertion
macros that were absent from native JSON call inventories. A focused control
established the boundary: JSON exposes the operand of a direct builtin type
trait, but omits calls in `decltype` operands passed as `std::is_same` template
arguments. These were not established analyzer defects.

A supplemental Clang 22 consumer now visits written `DecltypeTypeLoc` nodes and
serializes their actual underlying native expressions. It parses the same full
translation unit under the unchanged C++20 host-library/test-support profile.
Expression records include their native function name position, body boundaries,
type location and source path. No source expression or callee is synthesized.

The independent association helper requires a unique written native body and
matching owner name and source offsets. It verifies physical expression ranges
and coordinates, literal `decltype` bounds or independently captured macro
invocations. Overlapping expressions must match every existing native field;
only process-local native pointers are normalized for cross-process comparison.
Previously omitted expressions supplement the retained declaration AST. Explicit
specializations, source macro origins and all original raw captures are preserved.

Controls cover template patterns, explicit specializations, ordinary and member
calls, macro operands, an assertion erased by `NDEBUG`, and malformed source.
All six expected type operands are captured. Three overlap the original source
AST and match exactly; three are newly exposed. Two overlapping expressions also
match the independently captured full compiler-driver AST. Eleven corrupted
ownership, body, type, source, coordinate and macro-origin cases are rejected.
The first control's incorrect expected member column is retained with its failed
result; the corrected control reuses all native captures.

## Full cohort regrade and actual indexes

Supplemental capture covers all **344** previously eligible originals, including
all 71 earlier admissions for regression. Every capture succeeds, with zero
timeouts, capture errors or future-extension holds. Dependencies match the
retained declaration captures exactly. The result contains 1,133 native operands:
1,093 supplement their source bodies and 40 already exist with identical fields.
There are no association holds.

The unchanged metadata engine and qualified structure checks now pass **213
originals**, up from 71. All 71 earlier admissions remain valid; 142 new originals
qualify. The other 131 remain explicit metadata or origin holds. No preliminary
result or helper control is counted as a verified file.

Actual CLI indexing succeeds for all 142 new originals with SQLite and DuckDB.
All **284 per-original persistence checks pass**, covering source input identities,
modules, classes, callable ownership, signatures, docstrings, overloads,
declaration identities, imports, complete call/reference fields and provenance.
Across the two indexes, 600 functions, 14 classes and 8,268 call records match
the retained production artifacts. Deferred embeddings and retrieval ranking are
outside this qualification.

The current qualification path again rejects ten deliberate metadata corruptions.
Rendering classifiers are checked for all 213 positives against the documented
analyzer-owned static policy, independently of native macro provenance. Actual
originals, compiler and library identities, native dependencies and expressions,
macro records, association receipts, unchanged production assets and both indexes
are bound by the admission script.

The independently audited ledger update changes exactly 142 rows and preserves
25,620 other rows, all original identities and all 680 separated decisions.
The existing source-bound full gate still matches every production asset:
2,739 passed, three skipped, 88% coverage, zero indexing failures or coverage
issues. The prior 2,700-case regression remains unchanged. This evidence-only
phase does not claim a new production implementation or repository-gate run.

## Larger remaining groups

The refreshed full open-file inventory checks source hashes for all 20,733
remaining originals and reuses historical measurements with explicit stale-result
labels. The largest directory groups are libc++ standard tests (2,204), LLVM
headers (1,093), Clang C CodeGen tests (986), libc tests (800), and LLVM target
implementations (745). These are investigation inventories, not proven shared
causes or fix estimates. Source markers identify 5,243 inputs with RUN directives,
1,532 with diagnostic-error markers and 163 with split-file markers; none is
blanket-excluded.

A separate source inventory selects **278 new candidates outside the completed
603-file population**, using related assertion/statement names defined in common
test support. Overlapping family counts include `LIBCPP_ASSERT` in 150 files,
`ASSERT_NOEXCEPT` in 57 and `LIBCPP_ASSERT_NOEXCEPT` in 35. The selection screens
observed C++20 exclusion and expected-error markers. These source names and
screens do not prove reaching definitions, native acceptance or fixes. This
provides a larger fresh investigation group without repeating the 603 cases.

The remaining 131 files in the present native-positive cohort include shared
verifier limits around dependent member calls and complex template spellings,
alongside genuine signature and inventory mismatches. Prioritize measured impact
across the larger population before choosing a small tail. The existing LLVM
native generated-header context and its C++17 profile are retained and must be
inspected and reused before considering another build or investigation.

## Durable evidence

All paths below are relative to the dedicated worktree's
`.artifacts/analysis/parser-diagnostics-20261017-r1/` directory.

- `classification-v57.jsonl`, `classification-summary-v57.json`,
  `cpp27-type142-admission-v57-r1.json`, and
  `cpp27-type142-admission-audit-v57-r1.json`.
- `cpp-native-type-location-consumer-r1`,
  `cpp-native-type-location-controls-r1/r2`, and
  `cpp_native_type_supplement_r1.py`.
- `libcxx-assert-344-native-type-expressions-r1`,
  `libcxx-assert-344-native-grading-r5`,
  `libcxx-assert-type213-qualification-controls-r1`,
  `libcxx-assert-type142-qualified-cli-r1`, and
  `libcxx-assert-type142-index-verification-r1`.
- `current-open-impact-ranking-r2` and the retained historical source/profile
  artifacts referenced in its input manifest.
- `libcxx-remaining-shared-macro-ranking-r2` and
  `libcxx-statement-family-candidate-selection-r1`.

All raw, failed and superseded evidence remains retained. No merge, push,
main-checkout modification, branch cleanup or sub-agent work occurred.
