# Native call origins and shared header profiles — 2026-10-20

## Shared comparison gaps

The retained LLVM native projections conflated macro-expanded implementation calls with source-written calls and could not describe member calls on complex receivers. Clang also elides repeated filenames in JSON, so macro locations cannot be interpreted independently of serialization order. These were gaps in qualification evidence, not independently established analyzer defects.

`cpp_native_call_sites_r4.py` decodes the ordered bare-location filename state and retains the original JSON. It does not guess elided presumed names/lines. Active libclang preprocessing cursors bind physical function-like macro invocations to captured definitions. Source argument calls retain their physical spans, including namespace macros bound to explicit compiler definitions. Native macro implementation operations are separately retained. Native member/receiver spans prove explicit cast, parenthesized, call-result and indexed receivers, without importing analyzer code.

`cpp-native-call-origin-controls-r4/` verifies seven source sites, four macro implementation operations, three argument occurrences and four complex member cases with source UTF-8/CRLF positions. The resulting source fields match production output. Eleven mutations reject missing cursor/definition evidence, wrong invocation or definition names, missing namespace origins, and incorrect member access/name/receiver/coordinates. Repeated argument evaluation retains duplicate native occurrences while preserving distinct source sites. Erased argument calls are not waived; argument-selected callees without sufficient proof remain held. All earlier six-site/seven-occurrence/two-implicit-operation controls and their three negative cases remain satisfied.

## First admission: 40 originals

`cpp-official-headers-open70-macro-capture-r1/` captures all 140 preprocessing cases for the open originals from the preceding 116-file group. `cpp-official-headers-macro-origins-116-grading-r1/` reuses every retained compiler AST and compares all 232 cases: 183 cases and **86 originals pass both packaging profiles**, preserving all 46 earlier passes. The metadata comparator is unchanged; its controlled functions remain AST-identical to the prior comparator. The new projection helper has separate native controls, and all six macro-hint corruptions fail under the actual cohort profiles.

Production CLI indexes admit only the 40 newly passing originals. `cpp-macro-origin-qualified40-index-verification-r1/` passes **80 persisted comparisons and six actual CLI probes**, with no index failures. Classification v53 admits those 40 after independently rerunning the native comparison and checking source, macro/receiver provenance, prefix flags, immutable native evidence and the earlier source-bound repository gate. Across both profiles: 80 definitions, 40 prototypes, 40 aliases, 228 source-call records, 36 native-proven macro hints and 42 separately retained native macro operations. Operations are not counted as additional source calls or files.

## Second admission: 50 originals

The same consistent public-header/syscall profile is applied to the next 106 source-bound native failures. All original failures remain retained. `cpp-official-headers-remaining106-native-inventory-r1/` completes 128 of 212 cases without exceptions; **64 originals complete both native profiles**. The other 42 originals remain open. Their compiler failures do not establish malformed inputs or unsupported analyzer syntax.

`cpp-official-headers-remaining106-profile-r1/` reuses verified source graphs and the identical immutable native prefix dump. It verifies compiler/header hashes and derives 2,368 bounded bindings from complete recorded definitions; unqueried system names remain unknown. Analyzer readiness still checks each actual input fingerprint before and after analysis, completing 58 originals under both profiles without exceptions. Native macro capture completes all 128 selected cases. Grading passes 103 cases and **50 originals under both profiles**, with native corruptions checked in every exercised hint mode.

Production CLI indexes select only those 50. `cpp-remaining64-qualified50-index-verification-r1/` passes **100 persisted comparisons and six actual CLI probes**, with no index failures. Admission v54 rechecks the native prefix, every retained source/header snapshot, all source/asset hashes, native ASTs, selected definitions and macro/body source-call projections. Across both profiles: 100 definitions, 50 prototypes, 50 aliases, 182 source-call records, 26 native-proven macro hints and 12 native macro operations retained separately.

## Current accounting and controls

The two independent ledger audits preserve every original identity, all prior fixed/separated decisions and every other row: 25,722 unchanged rows for v53 and 25,712 for v54. The current ledger is **4,109 verified fixes, 680 justified exclusions and 20,973 open originals** (C 5,551; C++ 15,422), across all 25,762 original inputs. Fixed-only progress is **15.95%**; fixed plus exclusions is **18.59%**. The wrapper inventory has 284 open originals of 1,607. The complete grouped separated export remains `separated-inputs-v51-r1/`, independently verified as exactly equal to v54's unchanged 680-record separated subset.

Production source remains `abbddac4d6bc66f8cb405722d6c0a2ced41202bc`, C++ distribution 2.0.26/logical version 25. All execution source and asset bytes match that commit and its passing full-gate tree; generated runtime is frozen separately. The gate passes 2,703 tests, three skipped, 88% coverage and zero Semgrep findings, with all 2,374 prior macro-profile regressions byte-identical. This phase changes qualification evidence, not production source. The prior polling-cadence exception remains explicitly recorded in its original receipt/handoff.

No helper control, native-only case or clean parse is counted as a verified file fix. Raw, failed and superseded evidence remains immutable. No merge, push, main change, cleanup or agents are involved. The full remediation objective remains active.

## Next shared causes

The remaining call-field differences include explicit class construction represented by native CXXFunctionalCastExpr/CXXTemporaryObjectExpr rather than CallExpr. Further holds include an explicit destructor call, lowercase stdarg macros, original parameter forms and additional declaration inventory. These remain open until controlled native evidence or a demonstrated production fix resolves them. Preserve these holds and extend the common oracle rather than inventing targets or discarding native operations.
