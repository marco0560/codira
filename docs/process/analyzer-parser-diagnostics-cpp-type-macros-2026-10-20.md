# C++ declaration-time type macro proof — 2026-10-20

## Shared failure and current accounting

The 80 LLVM libc `stdfix` originals compile under the locally documented `-ffixed-point` mode: all 160 native packaging/profile cases complete. Before this change every packaging-disabled analyzer case completes, while every public-packaging case reports the same `decltype`/implementation type-spelling disagreement. The earlier header declaration retains, for example, `short accum`, while the implementation expansion contains `short _Accum`.

Classification v43 admits **76 original files**. Further native-compatible qualification in v44 admits **206 originals**, bringing the authoritative ledger to **3,688 verified fixes, 453 separated inputs and 21,621 open originals** (C 5,611; C++ 16,010). The four remaining files stay open. Admission follows independent metadata/native comparison and actual production qualification. Clean parses, helper controls and isolated causal experiments add no admissions.

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

The next 650 native-compatible originals use a derived, source-bound C++17/full-build profile retaining all relevant independently probed initial facts. Its 3,875 bindings fit the unchanged 4,096 limit. Readiness completes 497 originals under both packaging modes; this alone admits no files. `cpp-native-compatible-650-artifact-grading-r2/` compares all 1,300 cases, passes 206 originals under both modes and rejects all 24 corruption controls. Additional declarations, unresolved source calls and other unsupported comparison shapes remain explicit holds.

`cpp-native-compatible-207-cli-index-r1/` indexes all 207 selected candidates under both modes with zero failures. `cpp-native-compatible-207-index-verification-r1/` passes all 414 stored comparisons and six actual CLI commands. `localeconv.cpp` has an additional structure declaration outside the native oracle's scope, so it stays open despite passing function comparisons. The first admission attempt correctly rejects it before writing a ledger; that failure is retained. The revised grader applies this declaration-inventory guard to every candidate, and only 206 are admitted.

`cpp24-declaration-type-admission-v44-r2.json` checks 412 definitions, 206 prototypes, 206 aliases and 378 lexical calls. The independently generated `cpp24-native-compatible-admission-audit-r1.json` verifies all 25,762 original identities, every prior fixed/separated row and all 25,556 other v43 rows are unchanged. Original native captures and every failed attempt are preserved. The full remediation objective continues across all languages and repositories.

Implementation commit: `3c63c0abc6e5785c5690d62e095d66a6f7953c7c`. `cpp-declaration-types-validation-receipt-r1.json` binds every executed tracked source/asset to that commit and retains the ignored generated runtime version separately. `cpp24-declaration-type-admission-v43-r1.json` records the source-bound 76-file admission; `cpp24-declaration-types-admission-audit-r1.json` independently verifies every original identity, all prior fixed/separated rows and all 25,686 other v42 rows remain unchanged. These admissions check 152 definitions, 76 prototypes, 76 aliases and 152 lexical calls. After v44 the wrapper inventory has 705 open originals; the full objective remains incomplete.

Further [native source-call qualification](analyzer-parser-diagnostics-cpp-native-call-oracle-2026-10-20.md) admits 163 originals in v45. The current ledger is **3,851 verified fixes, 453 separated inputs and 21,458 open originals**; 542 wrapper originals remain open. These admissions reuse the unchanged, fully tested implementation and qualify the shared native comparison gap.
