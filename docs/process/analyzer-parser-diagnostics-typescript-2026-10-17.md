# TypeScript parser diagnostics: generic tagged templates

All 381 TypeScript/TSX files in the frozen analyzer main-r1 diagnostic set pass
syntax parsing with Microsoft's TypeScript compiler 5.9.3. This is syntax-only
evidence, without module resolution, type checking, compilation or execution.
Every source digest matches the frozen inventory.

## Corrected population and artifact evidence

In 365 Twenty files, every Tree-sitter error is a spurious missing `!` on a
generic tagged template. This syntax has been supported since
[TypeScript 2.9](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-2-9.html#generic-type-arguments-in-generic-tagged-templates).
It is not a future-language fixture. Both bundled TypeScript and TSX grammars
reproduce the problem, so switching grammars is not a remedy.

The correction recognizes only a missing bang on a non-null-expression wrapper
whose clean child is a generic instantiation used as the callee of a tagged
template. Every other error and missing node remains unresolved and continues
to prevent complete symbol indexing. The original source and syntax tree are
retained, including type arguments, template substitutions and byte coordinates.

Generic tags with simple type arguments expose a second grammar problem:
Tree-sitter can represent them as comparisons without reporting an error. Call
extraction recognizes the angle/template shape only after independently parsing
the enclosed type arguments. Genuine comparisons with parenthesized operands or
non-type expressions remain comparisons. Transparent generic/non-null wrappers
are unwrapped when identifying callees.

Expression-bodied arrows also need correct ownership: the grammar can place
the generic tag outside its arrow node. The analyzer restores the callable's
body extent and call ownership without including calls from parameter defaults.
Root expression calls are included, and expression-bodied arrows report that
they return a value. Source-based signatures and call coordinates are preserved.

Direct replay of all 381 frozen files recovers complete symbol indexing in
exactly **365**, retaining partial coverage in **16**. For the recovered files,
all **2,649 unique named top-level targets** match the native compiler's names
and declaration kinds. These are file-local target identities, not a count of
every symbol, import or relationship in the source. Focused regressions also
check generic tag call targets, Unicode byte positions, original signatures,
arrow body ownership, genuine comparisons, and retention of malformed source.

The TypeScript analyzer distribution advances to 2.0.2 and its logical artifact
version to 3. Root pins and official bundle 2.0.16 are aligned. No compiler or
Node dependency is introduced into the product; the native compiler is an
isolated diagnostic oracle only.

## Remaining valid-source cases

These 16 files remain genuine analyzer work and are not reclassified as malformed
or future syntax merely to obtain complete coverage.

| Reproduced grammar surface | Files | Repositories |
| --- | ---: | --- |
| Qualified `import()` types with array suffixes | 1 | Vue core |
| Optional `in`/`in2` properties following union annotations | 1 | Vue core |
| Parenthesized arrow expressions used as decorators | 2 | Nest |
| Generic calls with `typeof import()` type arguments | 6 | Prometheus 2, Twenty 4 |
| Ordinary ampersands in JSX text | 5 | Prometheus 1, VictoriaMetrics 2, Twenty 2 |
| Combined `abstract override readonly` property modifiers | 1 | Twenty |

## Retained evidence and validation boundary

Evidence is under the worktree-relative
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `ts-alternate-parser-probes-r1.json` and
  `ts-tagged-template-attribution-r1.json` preserve the exact parser errors and
  strict per-error attribution.
- `typescript-5.9.3-registry.json` and `typescript-5.9.3.tgz` retain the compiler
  package and the verified npm SHA-512 integrity binding.
- `ts-native-oracle.cjs` with `ts-native-oracle-r1.json` records the original
  syntax/name oracle. The separately versioned `ts-native-oracle-r2.cjs` and
  `ts-native-oracle-r2.json` add declaration-kind checks.
- `typescript-replay-r1.json` records all 381 source digests, recovered and
  residual status, and expected/actual top-level target names and kinds.

All 13 focused package/metadata tests pass. The complete workflow-quality
preflight and repository gate pass outside the sandbox, including Semgrep with
21 rules and zero findings. The gate reports 1,719 passed tests, three skipped,
86% total coverage, and a fresh index with 785 files, zero failures and zero
coverage issues. Its embeddings are deferred by the validator; this is not
embedding-completeness evidence. The derived gate receipt is
`typescript-validation-receipt-r1.json` under the same evidence directory.

Direct analyzer replay does not establish complete relationship correctness or
a benchmark-wide clean bill. The original campaign, corpus and main checkout
remain unchanged. The 16 residual TypeScript files and other languages remain
part of the active investigation.
