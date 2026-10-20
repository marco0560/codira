# C++ declaration-time type macro proof — 2026-10-20

## Shared failure and current accounting

The 80 LLVM libc `stdfix` originals compile under the locally documented `-ffixed-point` mode: all 160 native packaging/profile cases complete. Before this change every packaging-disabled analyzer case completes, while every public-packaging case reports the same `decltype`/implementation type-spelling disagreement. The earlier header declaration retains, for example, `short accum`, while the implementation expansion contains `short _Accum`.

Classification v43 admits **76 original files**, bringing the authoritative ledger to **3,482 verified fixes, 453 separated inputs and 21,827 open originals** (C 5,611; C++ 16,216). The four remaining files stay open. Admission follows independent metadata/native comparison and actual production qualification. Clean parses, helper controls and isolated causal experiments add no admissions.

## Implementation

Earlier callable return and parameter fragments now expand with the macro state reaching that declaration. Later macro redefinitions do not retroactively change the proof. Unknown or opaque required replacements, incompatible expanded types, ambiguous declarations and late declarations remain explicit holds.

Each type proof carries the actual contributing macro origins into generated definition, prototype and alias provenance. Equivalent earlier declarations retain distinct origins even when the macro name repeats. The existing provenance input fields support these records; no payload shape or core/backend schema change is introduced. Exact expanded spelling comparisons do not infer typedef, ABI or compiler-dependent type equivalence.

C++ logical analyzer version advances from 23 to 24, distribution from 2.0.23 to 2.0.24, and the official bundle to 2.0.50. Root pins and package contracts follow. Regenerating the installer catalog produces no change, so its distribution remains unchanged. This follows the accepted [ADR-034](../adr/ADR-034-bounded-cpp-declaration-macro-analysis.md) design.

## Validation and qualification

Evidence is retained under `.artifacts/analysis/parser-diagnostics-20261017-r1/` in the dedicated worktree. `cpp-declaration-types-before-controls-r1/` runs the exact committed pre-change helper against the three new positive regression cases; all three fail as expected. The updated generated-analysis suite passes all 25 cases, including earlier macro state, chained replacements, distinct origins, incompatible parameter/return types, uncertain direct/chained replacements and opaque definitions. The initial focused C++/bundle/contracts batch passes 676 tests.

The final `cpp-stdfix-fixedpoint-integrated-readiness-r3/` completes all 160 cases with unchanged source hashes. `cpp-stdfix-fixedpoint-artifact-grading-r3/` passes 152 cases, or **76 originals under both profiles**, and rejects all 24 corruption controls. Independent `cpp-builtin-long-native-controls-r1/` assertions and ASTs prove only complete scalar `long int`/`long` and `unsigned long int`/`unsigned long` equivalence; signed and wider alternatives are rejected. This corrects eight grader spelling holds without guessing aliases, widths or pointer equivalence.

Four originals remain held: `exphk.cpp` and `expk.cpp` need a broader macro-call oracle; `uhksqrtus.cpp` and `uksqrtui.cpp` compare conditional source alternatives with one active native branch. These are retained qualification holds, not four established independent parser defects. No hold is waived or counted as a fix.

`cpp-stdfix-fixedpoint-cli-index-r2/` indexes all 80 originals under both profiles with zero failures and complete selected-file coverage. `cpp-stdfix-fixedpoint-index-verification-r1/` passes all 160 persisted-artifact comparisons and six actual CLI discovery/evidence commands. Embeddings are deferred; this is not an original project build/runtime or embedding qualification claim.

`cpp-declaration-types-legacy-regression-r1/` reanalyzes every earlier declaration-macro admission: all **1,240 cases across 620 originals match the earlier metadata byte-for-byte**, with zero exceptions and unchanged source hashes. All nine corrected preflight checks pass. The full repository gate passes **2,686 tests, three skipped, 88% coverage**, zero Semgrep findings, 897 indexed files, zero index failures and zero coverage issues. `cpp-declaration-types-gate-r1-result.json` binds the examined result to the tested source. The first failed typing preflight and first CLI attempt invalidated by a source annotation change remain retained; neither contributes an admission.

The next 650 native-compatible originals are being measured under a derived, source-bound profile retaining all relevant independently probed initial facts. Its 3,875 bindings fit the unchanged 4,096 limit. Those results contribute no admissions yet. Original native captures and every failed attempt are preserved. The full remediation objective continues across all languages and repositories.

Implementation commit: `3c63c0abc6e5785c5690d62e095d66a6f7953c7c`. `cpp-declaration-types-validation-receipt-r1.json` binds every executed tracked source/asset to that commit and retains the ignored generated runtime version separately. `cpp24-declaration-type-admission-v43-r1.json` records the source-bound 76-file admission; `cpp24-declaration-types-admission-audit-r1.json` independently verifies every original identity, all prior fixed/separated rows and all 25,686 other v42 rows remain unchanged. These admissions check 152 definitions, 76 prototypes, 76 aliases and 152 lexical calls. The wrapper inventory has 911 open originals; the full objective remains incomplete.
