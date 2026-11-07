# Official LLVM libc headers and native qualification — 2026-10-20

## Shared qualification causes

The retained native compiler commands for 116 open originals already defined `LIBC_FULL_BUILD=1`, but mixed LLVM libc internal types with glibc public headers. Sixty-three originals first failed on conflicting FILE definitions and 53 on timespec definitions. These were native qualification-environment failures, not deliberate malformed source or evidence of 116 independent analyzer defects.

`cpp-official-libc-headers-causal-r1/` generates 100 public headers with LLVM's official checked-in Python generator and YAML inputs. Native commands use those headers and the checked-in public type/macro support headers, with C++ system-library includes disabled. All six causal cases pass. The same profile produces **232 complete native inventories for all 116 originals**, with zero exceptions; commands, source/generator/header hashes, generated files and raw output remain retained. This is a defined native QA profile, not a claim of a complete LLVM build or hermetic target runtime.

The first analyzer run failed before analysis because it used the broader 953-file macro-state table above the existing binding limit. It remains retained. A fresh 116-file profile queries only its captured source/header names and retains all compiler object predefines; the limit is unchanged. That run completes 24 originals under both packaging modes, and native grading passes 21 under both modes.

Two exact active-error traces then identify `futex_word.h:25`, the previously diagnosed unavailable syscall-fact boundary. The established explicit `sys/syscall.h` preinclude method captures those facts under the official-header profile. Its dependency receipt snapshots the actual preincluded headers. The profile has 1,886 bindings per packaging mode, within the existing bound. No unavailable macro is guessed undefined and no analyzer behavior is weakened.

## Original-file verification and admission

`cpp-official-libc-headers-syscall-116-native-inventory-r1/` passes all **232 native cases**, without exceptions. The matching analyzer run completes 95 originals under both modes, 201 complete cases overall, without exceptions. Full metadata grading passes 93 cases and **46 originals under both modes**. Incomplete analysis, call mismatches, unmapped native calls, ordinary functions and parameter-type differences remain explicit holds.

The comparator reuses the prior native corruption controls only after proving that every comparison function has identical AST structure to the previously controlled grader. Native source-call, macro-hint and original-parameter helper hashes remain bound. No new source macro hints are admitted by this group. The admission generator independently reruns the complete comparison for every admitted case against retained native ASTs, source bytes and call projections.

`cpp-official-libc-headers-syscall-qualified-cli-index-r1/` indexes all 46 originals under both profiles using DuckDB and SQLite, with zero failures and complete selected-file coverage. The corresponding index-verification run passes **92 persisted comparisons and six actual CLI probes**. It verifies definitions, prototypes, aliases, signatures, source coordinates, calls and generated provenance. Direct query-helper probes are labeled separately from CLI execution. Embeddings are deferred.

The tested production source remains `abbddac4d6bc66f8cb405722d6c0a2ced41202bc`, described in [source-proven owner exclusions](analyzer-parser-diagnostics-cpp-owner-throughput-2026-10-20.md). The existing full gate passes 2,703 tests, three skipped, 88% coverage and zero Semgrep findings. Every execution source/asset hash is checked against both that committed implementation and the gate's staged tree; the frozen generated runtime is bound separately. All 2,374 earlier macro-admission regression cases remain byte-identical. This artifact/report-only qualification does not require another unchanged-source full gate.

Classification v52 admits **46 verified original fixes**, covering 92 definitions, 46 prototypes, 46 aliases and 136 source-call records across both modes. The independent audit preserves all original identities, every prior fix and exclusion, and all 25,716 other v51 rows. No helper test or clean parse counts as a fix.

The current totals are **4,019 verified fixes, 680 justified exclusions and 21,063 open originals** (C 5,551; C++ 15,512). Fixed-only progress is **15.60%** of the original 25,762 inputs; fixed plus exclusions is **18.24%**. The wrapper inventory has 374 open originals. The complete 680-input grouped export remains `separated-inputs-v51-r1/`; its records are independently checked as exactly equal to the unchanged separated subset of v52.

## Next shared frontier

Retained call projections identify 41 disabled-profile originals held for unmapped calls. Repeated groups include macro-internal calls through LIBC_ASSERT and related helpers, plus member calls on cast or other complex receivers. `cpp-official-libc-headers-next-call-frontier-r1.json` records examples and counts. These are qualification holds, not independently established analyzer defects. Reuse the established native macro-origin capture where applicable, then distinguish missing oracle coverage from actual metadata differences with native controls. Do not waive missing origins or complex callees.

The full remediation goal remains active across all original languages and repositories. Native-only cases and the 70 originals from this batch not admitted remain open.
