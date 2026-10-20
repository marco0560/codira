# Source-backed C++ assertion statements and native capture throughput

The full 25,762-file remediation goal remains active. Classification v55 is
unchanged: **4,136 verified fixes, 680 separated inputs and 20,946 open files**.
No helper result, clean parse or native-only result in this phase adds a file fix.
The original v38 baseline and all immutable evidence remain preserved.

## Committed shared production correction

Commit `665412912b31e024bd244a528136a35c6fdcc71a` integrates source-backed static
assertion statements through the accepted ADR-034 macro-context machinery.
Candidate names come from captured function-like definitions, including variadic
forms; the implementation does not hard-code `ASSERT_SAME_TYPE`. Ordered context
selection preserves include boundaries, explicit undefined states and uncertainty.

Statement-only expansions use an AST mapped back to original source bytes before
ordinary extraction. This preserves templates, classes, same-line overloads,
following declarations, UTF-8/CRLF coordinates and source macro hints. Duplicated
argument sites are retained once. Unsupported call-shaped argument erasure,
replacement-introduced calls and malformed or ambiguous expansions remain holds.
Mixed declaration/statement expansion continues through generated-callable
normalization. The production correction also excludes the `noexcept` language
operator from calls while preserving calls in its unevaluated operand.

C++ logical version is 27, distribution 2.0.28, and official bundle 2.0.54.
Schema 24, backend 28 and provenance format 1 are unchanged. Runtime, source,
staged tree, full gate and committed assets are bound in the phase receipt.

All 77 focused checks and nine preflight checks pass. The full outside-sandbox
repository gate passes: **2,739 tests, 3 skipped, 88% coverage**, 911 indexed files,
zero failures and zero coverage issues. All **2,700 cases for 1,350 previously
admitted macro originals** are byte-for-byte unchanged. An independent Clang
control proves that `noexcept(argument())` contains a language operator and one
physical operand call; six metadata corruptions are rejected.

## Full candidate measurement and native evidence

The frozen 603-original libc++ assertion cohort has 674 source/include snapshots
and 993 independently established C++20 prefix facts. Production readiness first
completed 127 files. Retained failure inspection identified wrapper-specific
normalization of template header positions and phantom `noexcept` calls as shared
causes. The corrected run completes **392 of 603** with zero exceptions.

Native evidence covers all 603 originals under the explicit C++20 host-library
profile: 441 native-complete cases and 162 compiler failures. One future-extension
warning is retained in a failed case. Compiler failures remain open inputs; this
measurement does not establish malformed-fixture roles or unsupported grammar.
Of the 392 production-complete originals, **344 also have complete native and
preprocessing-origin captures**; 48 retain native-negative holds.

The first conservative metadata pass covers all 344, including classes and
templates. It produces **27 preliminary passes and 317 holds**, with zero ledger
admissions. It reuses the established r11 inventory/type/parameter/bodyless
comparison contract and changes only its nested source-call projector; an AST
comparison proves all other comparison logic unchanged. Additional checks compare
qualified identities, namespace inventories, physical signatures and body ends.
The six-field call comparison and complete control/admission/index binding still
need to be completed before a pass can become a verified fix.

The dominant hold is shared verification coverage: the existing native macro
origin helper accepts uppercase names only. This prevents it from proving standard
`assert` expansions and their argument-origin calls. Unmapped occurrence counts
are diagnostic, not distinct-file or distinct-defect counts. Extend the independent
origin controls and projector before deciding which remaining mismatches require
production corrections. Preserve the existing analyzer contract for heuristic
external-target classification; do not silently change either side to force parity.

## Measured native throughput correction

The original full-AST capture spent most of its output serializing library headers,
including failed compilation attempts. It was stopped after 42 completed captures;
four interrupted compressed streams and their recoverable-prefix hashes remain.
Nothing was deleted or overwritten, and the interrupted identity exited 143.

A Clang 22 consumer now parses the complete translation unit and emits each
source-owned top-level declaration with its complete AST, dependency snapshot and
native qualified context. Two positive controls, including an actual original,
match **every source-owned AST field** against retained full-driver dumps; only
process-local pointer values are normalized for cross-process comparison. A
negative source remains rejected. Dependency and context output are independently
checked. This changes serialization scope while retaining full header parsing.

Across the same first 42 originals, native exit results are identical. Raw output
falls from **19,265,963,396 to 107,742,909 bytes**; median capture time falls from
**38.95 to 1.50 seconds**, approximately 26 times faster. These are capture
measurements, not file-fix throughput or an estimate for the full campaign.

## Durable identities and next action

All identities below are in the dedicated worktree under
`.artifacts/analysis/parser-diagnostics-20261017-r1/`.

- `cpp-statement-macro-gate-result-r1.json`,
  `cpp-statement-macro-commit-binding-r1.json`,
  `cpp-statement-macro-prior1350-regression-r1/` and
  `cpp-noexcept-expression-native-controls-r1/`.
- `libcxx-assert-603-profile-capture-r1/`,
  `libcxx-assert-603-readiness-r1/` (superseded results retained), and
  `libcxx-assert-603-readiness-r2/` (current committed-source results).
- `libcxx-assert-603-native-inventory-r1/` (interrupted full-header output),
  `cpp-source-owned-ast-consumer-r1/`, `cpp-source-owned-ast-consumer-r2/`,
  their corresponding control identities, and
  `source-owned-native-throughput-comparison-r1.json`.
- `libcxx-assert-603-native-inventory-r2/`,
  `libcxx-assert-392-macro-capture-r1/` and
  `libcxx-assert-344-native-grading-r1/` (preliminary comparison, no admissions).

Next extend native macro-origin proof for the measured lowercase `assert` family,
retain argument calls and generated-operation distinctions, and run the same
full metadata comparison with controlled six-field checks. Reuse the complete
source-owned native and preprocessing evidence. Then qualify actual production
indexes before any ledger admission. Continue the larger full-corpus objective;
do not restrict success to this cohort or the wrapper tail.
