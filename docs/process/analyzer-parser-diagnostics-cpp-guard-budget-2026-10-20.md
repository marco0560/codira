# C++ controlling guards and directive budget — 2026-10-20

The actual LLVM `libc/src/math/generic/ceil.cpp` readiness probe exhausted the
8,192-directive budget in both packaging modes. Its retained r2 measurements
record 8,193 events, 288 visits, 675,676 traversed bytes and 1,288 bindings at
failure. Repeated visits to guarded headers charged all their inactive directives.
This was directive exhaustion, not binding exhaustion.

The context walker now caches a structural controlling-guard proof alongside
the directives for each frozen source. Only an initial exact `#ifndef NAME`
whose balanced closing `#endif` is last can qualify. No outer alternative or
non-comment token outside that conditional is allowed. Malformed alternatives,
closing directives and lexical errors retain the normal diagnostic path.
A proven guard skips directive processing only when currently known defined
and no source-offset query is requested. Unknown/undefined states, source
undefinition and re-inclusion, nested guarded cycles and opaque known-defined
states retain their existing semantics. Include observations and traversal
accounting remain recorded; all safety limits remain unchanged.

Fresh r4 readiness measurements reach and expand the original wrapper:

| Packaging | Directives | Visits | Traversed bytes | Bindings |
| --- | ---: | ---: | ---: | ---: |
| Disabled | 2,156 | 477 | 1,363,409 | 1,282 |
| Public | 2,141 | 475 | 1,359,302 | 1,282 |

The baseline failed partway through the graph; its smaller visit/byte totals
are not whole-file comparisons. Readiness still uses independently captured
native initial states, including explicit undefined and opaque states, and
does not establish that a production preprocessing profile is integrated.

The 108 context controls include structural negative cases, unknown guards,
source undefinition, inactive root query snapshots and a repeated-header case
that would otherwise exceed the directive budget. Native control r4 checks
40 cases over 50 profiles, all matching; four ambiguity holds produce distinct
native variants. Real captured `common.h` synthetic drivers retain exact six-
and 36-token parity in both modes. The plugin distribution advances to 2.0.21
and the official bundle to 2.0.47; logical analyzer behavior remains version 22
because these helpers are still disconnected from indexing.

Actual original-file Clang 22 preprocessing and AST captures also exit zero in
both packaging modes. Comparison with the original invocation and body confirms
token parity in both modes and isolates the original namespace's one disabled-mode
declaration and three public-mode declarations. The latter comprise the
`__ceil_impl__` prototype, `ceil` alias and `__ceil_impl__` definition. The prototype
and alias have unnamed parameters; the definition has parameter `x`.
They retain all raw output and commands, but do not yet
compare production analyzer metadata, source ownership, generated declarations
or provenance. They qualify no files. The full objective remains incomplete:
classification v38 stays at **2,786 verified fixes, 453 separated inputs and
22,523 open files**. [ADR-034](../adr/ADR-034-bounded-cpp-declaration-macro-analysis.md)
still requires configuration, indexing/cache integration, generated-artifact
provenance and independent actual-file qualification before admission.

All durable ignored evidence is under
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `cpp-context-original-ceil-readiness-r2/` preserves the measured failure;
- `cpp-context-original-ceil-readiness-r3/` and `-r4/` preserve successive
  successful readiness captures;
- `cpp-context-native-controls-r3/` and `-r4/`, and
  `cpp-context-libc-native-r3/` and `-r4/` preserve control/native comparisons;
  r4 binds the final formatted helper source;
- `cpp-context-original-ceil-native-r1/` preserves actual original-file native
  preprocessing, AST, commands and output digests;
- `cpp-context-original-ceil-comparison-r1/` records exact original-file token
  parity and the source-owned native declaration inventory;
- `cpp-generated-shape-readiness-r1/`, `-r2/` and
  `cpp-generated-shape-findings-r1.json` distinguish a synthetic renderer artifact
  from the measured omission of public prototypes/aliases by the current builder;
- `cpp-guard-quality-r1.log/.exit` records all eight preflight checks passing,
  including outside-sandbox Semgrep with zero findings.

The focused package/bundle suite passes **600 tests** after aligning the version
assertions; `cpp-guard-focused-r1-failure.json` retains the initial stale-assertion
failure and `cpp-guard-focused-r2.log/.exit` the corrected result. The full
repository gate exits **0**: **2,622 passed, three skipped**, **88%** coverage,
zero Semgrep findings, **887 indexed** and zero coverage issues.
`cpp-guard-gate-result-r1.json` preserves the compact source-bound receipt.
