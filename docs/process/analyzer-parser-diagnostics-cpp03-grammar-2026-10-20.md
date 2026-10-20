# C++03 dependent construction and exception macro recovery — 2026-10-20

## Scope and cause

This work continues in `fix/analyzer-parser-diagnostics` in the dedicated
worktree. Main and the original benchmark corpus remain unchanged.

Two native-valid shared causes were reproduced in legacy libc++ headers:
`typename T::type()` in expression positions and object macros expanding to
exception suffixes such as `throw()` or `noexcept(true)`. These are grammar
adaptation gaps, not grounds to separate a source as intentionally malformed
or unsupported future syntax.

The C++ analyzer now masks only provider-proven dependent constructions while
preserving declarations, type contexts, comments, literals, original signatures
and byte coordinates. Exception macro handling accepts only captured object
alternatives that all resolve to one exception clause or an empty replacement,
with at least one actual exception clause. Reaching definitions, include
boundaries, namespace projections, cycles, keyword overrides and duplicate
suffix slots remain guarded. Function-like exception macros remain held.

The logical analyzer version is 20, distribution 2.0.16 and official bundle
2.0.41. Matching pins and lock metadata are updated.

## Verification

The focused behavioral/package/contract run passed 343 tests, including 39 new
regression cases. All eight workflow preflight checks passed. Semgrep ran
outside the sandbox. The source full repository gate passed: **2,315 passed, three skipped, 87%
coverage**, a fresh 866-file index, zero index failures and zero coverage issues.
The compact receipt binds the result to exact source digests. Source commit: `610e738`. Classification v33 admits the 44 fully qualified
originals after checking source, dependencies, native evidence and controls.

The production replay completed 571 distinct profile requests: all 343 legacy
originals and all 316 previously admitted macro/profile paths, with identical
profile overlaps merged. All 316 prior payloads remain byte-identical.

| Legacy result | Files |
| --- | ---: |
| Clean parser trees | 276 |
| Partial trees | 57 |
| Execution limits/exceptions | 10 |

Native AST, preprocessing and written-call evidence was complete for 275 of the
276 clean outputs. Existing native evidence was reused only after verifying its
hashes and original context; 63 written-call captures were newly obtained.
The complete comparison qualifies 106 legacy files, preserving all 89 earlier
qualifications and adding 17 candidates. The grammar changes contribute 17 additional qualifications. A separate scope
correction described below contributes another 27, for 133 total legacy
qualifications and 44 newly admitted originals relative to the earlier 89.

The native-call scorer was independently challenged. Two coordinated changes
to product payloads and native receipts passed the earlier draft scorer:
a forged `typename` qualifier/position and a named construction changed to an
unresolved call. Both failed examples remain retained. A fresh R8 scorer
requires the actual typename prefix proof and restricts unresolved construction
to independently checked builtin/native forms. Fresh controls pass 26 positive
cases, preserve three explicitly held cases and reject all 24 negative cases.
No new admissions used the affected scorer.

## Remaining diagnostic groups

Of the 275 native-compared clean outputs, 169 remain held. Findings overlap:
123 lexical-call mismatch occurrences, 93 named-type mismatches, 42 definition
mismatches, 30 omitted-prototype occurrences, 19 unmapped declarations and one
parameter mismatch. These are occurrences, not distinct file counts or promised
fix totals.

The additional ownership comparison incorrectly required function-local aliases
and classes despite `DeclarationArtifact` being documented as module-level and
the base scorer already excluding callable-local declarations. This was an
evaluator defect: the analyzer should not gain flattened local symbols to pass
it. A fresh R2 ownership replay excludes callable-local declarations while
preserving all module/class comparisons and all existing callable, parameter,
call, prototype and type checks. It qualifies the 27 files held only by the
inconsistent check and preserves all 106 previous current-source qualifications.
Native controls match the actual public analyzer artifact and reject six
mutations: missing module alias, member alias, method, function, record, and an
extra flattened local alias. No product behavior is changed for this correction.

The resulting 142 held native-compared clean outputs still need extraction or
independent evidence work. Other paths need conditional/macro and callable
extraction work; clean parsing alone does not qualify them.

## Durable evidence

All measurement records remain in the worktree under
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `cpp20-grammar-production-r1/`: frozen source manifest, all requests, outputs,
  fingerprints, exact regression comparisons and terminal summary;
- `cpp20-legacy-native-r1/`: source-bound native evidence, reuse provenance,
  newly captured receipts and terminal summary;
- `cpp20-legacy-grading-r1/`: retained earlier artifact/ownership comparisons;
- `cpp20-legacy-grading-r2/`, `cpp-full-identity-scope-controls-r1/`: corrected
  callable-local eligibility and explicit controls;
- `cpp20-native-grammar-controls-r1/` and `cpp20-written-call-negative-r1/`:
  retained earlier scorer evidence, including both unexpected acceptances;
- `cpp20-native-grammar-controls-r2/` and `cpp20-written-call-negative-r2/`:
  fresh positive, held and negative controls for R8;
- `cpp20-grammar-qualification-summary-r1.json`: candidate gains and overlapping
  remaining diagnostic groups. Classification is now v33: **2,591 verified fixes, 453 separated, 22,718 open**
  (C 5,725; C++ 16,993). Only the 44 admitted rows differ from v32.
- `cpp20-grammar-validation-receipt-r1.json`: examined successful source gate.

## Admission and continuation

The complete comparison replay preserves all basic checks across 275 files;
only the inconsistent callable-local eligibility in the additional full identity
check changes. `cpp20-legacy-qualification-invariants-r1.json` retains that audit,
sorting only unordered missing/extra counters and preserving parameter order
and multiplicity. The source-bound admission is
`cpp20-legacy-context-admission-r1.json`; complete JSONL/CSV and
language/version/repository groups are in `classification-v33.*` and
`classification-summary-v33.json`. Overall accounted share is 11.82%;
the remaining 22,718 paths are not declared resolved.

A targeted continuation selected 133 previously partial modern libc++ originals
containing `typename` or `_NOEXCEPT`. Its completed frozen-source replay found
61 clean and 72 partial outputs, with no execution exceptions. All 61 clean
outputs have complete native AST/preprocessing/written-call captures in the
same C++23 context. Qualification remains separate; they are not added to v33.
Records remain under `cpp20-modern-grammar-production-r1/` and
`cpp20-modern-native-r1/`.
