# C++ declaration-macro indexing integration — 2026-10-20

## Scope and accounting

This implements the indexing path approved in [ADR-034](../adr/ADR-034-bounded-cpp-declaration-macro-analysis.md), following the independently checked [context budget repair](analyzer-parser-diagnostics-cpp-guard-budget-2026-10-20.md) and [projection layer](analyzer-parser-diagnostics-cpp-projection-2026-10-20.md).

The starting classification-v38 baseline was **2,786 verified fixes, 453 separated inputs and 22,523 open originals**. Classification v39 admits 70 `stdbit` originals; v40 then admits 497 generic math originals. The current totals are **3,353 verified fixes, 453 separated inputs and 21,956 open originals** (C 5,611; C++ 16,345). These 567 admissions follow complete original-file native and production qualification; helper controls and clean parses contribute no fixed-file count.

The shared-cause inventory contains 1,607 still-open LLVM libc function-wrapper files. The first batch contains 501 generic math files, each checked under packaging-disabled and public-packaging profiles. All 501 captured dependency graphs match the immutable inventory source hashes. Native predefined-macro and definedness probes provide initial states; an omitted macro is never assumed undefined.

## Integrated behavior

An explicit `preprocessor_definitions` mapping activates bounded captured-context analysis. The default remains unchanged. Known-defined macros without available replacement bytes use an opaque state; definedness can be proved without inventing replacement text. Include order, source overrides, guards and earlier declaration availability remain significant.

Projection feeds ordinary analyzer extraction. Generated definitions, prototypes and aliases retain actual qualified names, source-spelled types and independent parameter-name information. A generated `decltype` declaration requires a unique active earlier source declaration with compatible types. Unsupported ownership, missing context or ambiguity retains an explicit partial result.

Generated provenance records invocation spans, exact source/context identities, contributing macro inputs and token derivation separately from physical spelling. Pasted and stringified tokens do not acquire fabricated physical spelling spans. Original lexical body calls retain their coordinates. A generated prototype uses the existing secondary-declaration storage slot with an explicit `prototype` role; it is not evidence of a C++ overload. Public aliases do not borrow implementation bodies or parameter names.

Both SQLite and DuckDB persist generated provenance in an `artifact_provenance` table, including incremental replacement, deletion and transactional full rebuild. Symbol evidence checks current source, configuration and captured dependency freshness before returning generated metadata, and exposes attached records as `generated_declarations`. Logical schema version is 24, both physical backend versions are 28, and the C++ logical analyzer version is 23. Plugin distributions and official bundle pins advance together; the installer distribution advances to 2.0.6 with its regenerated schema catalog.

Nested preprocessing tables exposed a configuration serializer defect: writing a detached table body lost its plugin parent. The renderer now serializes the complete plugin parent context. This is exercised through actual configuration loading and indexing.

## Validation and retained evidence

Evidence remains under `.artifacts/analysis/parser-diagnostics-20261017-r1/` in this worktree. Existing attempts are immutable and retained, including failed configuration, public declarator and DuckDB rebuild attempts.

- `cpp-integrated-focused-r1.log`: 806 focused checks passed before the additional context fast-path control.
- `cpp-math-generic-profile-capture-r1/`: all 501 source/dependency captures and independent native initial-state probes.
- `cpp-math-generic-integrated-readiness-r1/`: retained partial attempt stopped after 252 cases to address a measured conditional-merge bottleneck.
- `cpp-math-generic-integrated-readiness-r2/`: fresh source-snapshotted run; compares all overlapping metadata byte-for-byte. This checks analyzer readiness, not native semantic qualification.
- `cpp-integrated-original-ceil-index-r2/`: actual original-file public-profile CLI indexing succeeded. Embeddings were deferred; this does not claim embedding evaluation or original project runtime success.
- `cpp-ceil-filtered-native-r1/`: focused qualified-name native ASTs match the previously retained full native declaration inventories while substantially reducing output volume. This is an oracle capture check, not file admission.

The single-outcome conditional merge now clones its sole environment rather than rebuilding every binding and origin. The focused control verifies independent mutable state; the fresh readiness run checks unchanged original-file metadata against the retained pre-optimization results.

The completed readiness run covers all 1,002 cases with zero exceptions and unchanged source hashes. All 252 overlapping metadata payloads match byte-for-byte; the final paired speedup is 1.607×. Independent Clang C++17 captures complete in both modes for all 501 originals. `cpp-math-generic-artifact-grading-r3/` passes 994 cases, or **497 originals under both modes**, and rejects all 24 deliberately corrupted controls. It compares declaration inventories, names, roles, types, parameter names, linkage, alias targets, physical calls, definition end lines, signatures and captured macro provenance. Four originals (`atan2l.cpp`, `cos.cpp`, `expf.cpp`, `sin.cpp`) remain held for conditional lexical-call differences.

Preflight r2 passes all eight checks with zero Semgrep findings. Its earlier r1 exposed a row-wise DuckDB insertion despite exit zero; the insertion now uses the established Arrow path. The custom-rule validation command now includes `--error`, so future findings fail automatically.

The first full gate reports two failures, 2,675 passes and three skips: installer catalog drift and the Python characterization fixture's old DTO shape. The catalog is regenerated through its generator. The golden comparison asserts that Python generated provenance remains absent before projecting the old DTO shape; the frozen fixture is unchanged.

Actual CLI cohort attempt r1 exposed another zero-exit failure: spawned workers did not receive the external `--config-file` selection, so all 501 files in each mode were rejected for differing input identity. A real two-file spawned-process reproducer fails before the fix and passes afterward. Worker initialization and task execution now explicitly carry the selected configuration path. Fresh CLI attempt r2 requires semantic indexing success as well as exit zero. Failed raw attempts remain retained.

The second gate stopped on an existing lint-suppression inventory line moved by the worker fix. The inventory now records the actual line; its reason is unchanged. The inexpensive preflight now includes the two hygiene-policy checks, collecting their failures before a full gate. The final preflight passes **all nine checks**, including the newly included hygiene inventory. The corrected full gate passes: **2,678 tests passed, three skipped, 88% coverage**, zero Semgrep findings, **896 indexed**, zero index failures and zero coverage issues. `cpp-integrated-gate-result-r3.json` binds the examined result to the tested source and staged changes.

Actual CLI cohort indexing succeeds under both profiles: 501 math files and 70 `stdbit` files per mode, zero failures, complete selected-file coverage. Public packaging uses SQLite; disabled packaging uses DuckDB. Embeddings are deferred. This establishes neither embedding evaluation nor repository-wide LLVM completeness.

The next shared group, 70 `libc/src/stdbit` originals, also passes all 140 native cases. Its first comparison held equivalent scalar spellings `unsigned` and `unsigned int`. The retained `cpp-builtin-unsigned-native-controls-r1/` Clang probe proves that exact equivalence and rejects signed/wider alternatives. The corrected grader normalizes only that complete scalar spelling; all 140 cases pass and all 24 deliberately corrupted controls are rejected. No compiler-dependent alias equivalence is inferred.

`cpp-stdbit-index-verification-r4/` compares every stored function, prototype, provenance payload and lexical call for all 140 cases, then passes six actual CLI discovery/evidence commands. Complete CLI evidence equals normalized direct-helper evidence, with the CLI's additional selected-file coverage report separately checked. Earlier harness failures are retained: DuckDB cached handles must be released through its backend lifecycle before starting another process; the CLI adds coverage metadata to its JSON response. Neither mismatch was waived or counted as a product fix.

Implementation commit: `6ee42c4e1c78ffc38ccfa5cdeb7bdd754b9f9d4d`. `cpp-integrated-validation-receipt-r3.json` verifies every executed tracked source against that commit and retains the ignored, build-generated runtime version module separately as an exact snapshot. No generated runtime file is committed.

`cpp-math-generic-index-verification-r5/` also passes all 1,002 persisted-artifact comparisons and six actual CLI commands. Together with `cpp-stdbit-index-verification-r4/`, the checks cover all 1,142 original/profile index cases. Only the 567 originals passing both native profiles enter the ledger: **1,134 definition records, 567 prototypes, 567 aliases and 1,262 lexical calls checked**. The four math holds remain open.

Classification-v39 and v40 preserve all 25,762 original identities. All 25,195 rows outside these admissions, including every prior fixed or separated record, remain unchanged from v38. The existing v38 separated-input reports still describe the same 453 inputs by language, version and repository. `cpp23-combined-admission-audit-r1.json` independently checks the classification chain and counts native roles; it records the retained v39 raw counter spelling `aliass` without altering that evidence.

The wrapper inventory now has **1,040 open candidates**, including the four generic-math holds and 1,036 other wrapper files. The full remediation goal remains active across all languages and repositories.
