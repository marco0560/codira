# TypeScript parser diagnostics: remaining contexts and native replay

The follow-up to the
[generic-tag correction](analyzer-parser-diagnostics-typescript-2026-10-17.md)
addresses all 16 remaining TypeScript/TSX files from analyzer main-r1.
All 381 original TypeScript diagnostic files now permit complete symbol
indexing in fresh direct analyzer replay. Original campaign databases, source
files, main and benchmark configuration remain unchanged.

## Reproduced causes and correction

| Source construct | Files | Repositories |
| --- | ---: | --- |
| Qualified literal-module import array types | 1 | Vue core |
| Optional `in`/`in2` properties following union annotations | 1 | Vue core |
| Parenthesized decorator function expressions invoked with empty arguments | 2 | Nest |
| Generic calls with `typeof import()` type arguments | 6 | Prometheus 2, Twenty 4 |
| Literal ampersands in JSX text | 5 | Prometheus 1, VictoriaMetrics 2, Twenty 2 |
| `abstract override readonly` property modifiers | 1 | Twenty |

The native TypeScript compiler 5.9.3 accepts every original file. These are
released-language grammar gaps, not malformed or future-syntax exclusions.
The compiler is an isolated diagnostic oracle, not a new product dependency.

The package-owned compatibility module selects only observed syntax structures.
Its parser buffer retains the original byte length and every newline. Artifact
names, signatures and source coordinates always use original source bytes.
The complete projected candidate must parse without unresolved errors, or the
original partial result and diagnostics survive.

Literal JSX ampersands are changed only in error tokens directly belonging to
JSX text. Boolean operators, strings and expressions are preserved. Optional
property aliases retain original names in interface signatures. Modifier
normalization changes no declaration name or method body. Qualified import
types retain their original module/type text in signatures, and erased type
queries do not produce runtime dynamic-import calls.

Decorator expressions are independently parsed as ordinary expressions before
projection. The complete function expression remains in the tree; call
extraction restores the original IIFE callee, its text and byte location. It
does not invent an underscore-named call, and genuine underscore calls remain
ordinary calls. Missing parentheses, malformed arrow types and argument holes
remain partial. A candidate guard rejects empty call-argument slots that the
bundled grammar otherwise tolerates.

Native call comparison also found one previously silent grouping error in
Twenty's `SettingsEnterprise.tsx`: `await` became part of a generic query's
callee. The correction restores the `query` target and receiver position,
while preserving explicitly parenthesized awaited-function calls as expressions.

## Independent verification scope

The final replay binds every source to the baseline SHA-256, actual selected
analyzer and original repository root. It records the original configuration
digests and verifies that the baseline configurations use default analyzer
controls. The analyzer is distribution 2.0.3, logical artifact version 4; root
pins and official bundle 2.0.17 are aligned.

| Native comparison | Result |
| --- | ---: |
| Original TypeScript/TSX diagnostic files | 381 |
| Files permitting complete symbol indexing | 381 |
| Named top-level targets checked by name and kind | 2,784 |
| Indexed callable bodies matched | 459 |
| Runtime call-syntax records matched | 4,441 |
| Missing targets/bodies or call mismatches | 0 |

Calls are checked in source order for kind, target, receiver, line and UTF-8
byte column. Type syntax is excluded from runtime calls by both independent
walkers. This proves the stated syntax/artifact facts; it is not type checking,
call-target resolution, program execution, complete language-semantic grading,
backend persistence evidence or a full benchmark rerun.

Retained evidence under the worktree-relative
`.artifacts/analysis/parser-diagnostics-20261017-r1/` includes
`ts-runtime-call-oracle-r1.cjs`, `ts-runtime-call-oracle-r1.json`,
`replay-typescript-context-r2.py`, and `typescript-context-replay-r2.json`.
The earlier provisional replay retains the one call mismatch rather than
overwriting that observation. New regressions reproduce the original coverage
failures and check valid keyword-named properties, genuine comparisons,
runtime imports, source preservation and malformed-source rejection.

All 22 focused package/metadata tests pass. The complete workflow-quality
preflight and repository gate pass outside the sandbox. Semgrep scans the new
staged module along with existing code: 21 rules, 169 files, zero findings.
The full gate reports 1,728 passed tests, three skipped, 86% coverage, and a
fresh structural index with 788 files, zero failures and zero coverage issues.
Its embeddings are intentionally deferred by the validator. The retained
`typescript-context-validation-receipt-r1.json` binds these results to the same
product-source digests used in native replay.

Other language populations remain under the active investigation; this report
does not claim a benchmark-wide clean bill.
