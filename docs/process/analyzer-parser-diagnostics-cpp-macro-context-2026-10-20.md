# C++ reaching-macro context — 2026-10-20

The operator accepted option A and [ADR-034](../adr/ADR-034-bounded-cpp-declaration-macro-analysis.md)
authorizes bounded, explicitly configured C++ declaration-macro analysis.
This phase implements the condition and source-reaching selection foundation;
indexing integration and original-file qualification remain open. Classification
v38 is unchanged: **2,786 verified fixes, 453 separated and 22,523 open files**.
The 1,607-file LLVM libc inventory remains a candidate population.

## Implemented context behavior

`cpp_macro_conditions.py` evaluates bounded signed integer expressions and
explicit defined/undefined states. Missing condition inputs stay unknown.
Width-dependent arithmetic, unsigned or character constants, unsupported
operators and unsupported subexpressions remain holds. C++ digit separators are
supported; LLVM's real hardening constants require them. Logical agreement can
resolve unknown definedness, while an unknown replacement cannot be treated as
an arbitrary scalar: its tokens could change expression precedence.

`cpp_macro_context.py` walks a frozen, ordered include graph without filesystem
or compiler access. It selects immutable environments at original byte offsets,
respecting source overrides, undefinitions, transitive include order, guards,
re-inclusion and pragma once. Unknown branches are compared rather than chosen.
Identical replacements retain all supporting physical directive origins;
conflicting or possibly absent replacements remain uncertain. Invocation
activity is separately true, false or unknown. Later definitions cannot reach
earlier queries.

Conditional pragma-once visits retain possible visited/unvisited states. For
example, conditionally including a once header, undefining its macro, then
including it again can leave that macro defined on one path and undefined on
another. Treating the header as globally visited or globally unvisited would
invent a result; the selector preserves the hold.

Logical directives retain original physical spans across UTF-8 and CRLF input,
line splices and comments. Directive-shaped text inside comments and literals is
opaque. Raw-string bodies preserve phase-two reversion when identifying their
real terminator. Multiline comments do not terminate a directive, and comments
before the hash, keyword or name are supported. Replacement whitespace remains
intact because nested stringification can distinguish `a+b` from `a + b`.

A known-defined compiler macro can have an explicitly opaque replacement.
`defined(NAME)` can then be proven without inventing a function body or value;
attempting actual substitution fails. Unrelated opaque definitions do not block
a supported expansion. Unavailable or macro include targets remain explicit
observations and supply no inferred definitions or compiler-equivalence proof.

Work is bounded by source/traversal bytes, captured files, include visits/depth,
directive count, conditional depth, binding count, expression size and token
substitution limits. Invalid contexts fail explicitly. Current configuration
schema and indexing behavior are unchanged; the new profile is not exposed yet.
Logical C++ analyzer version remains **22**. The plugin distribution advances to
**2.0.20**, and the official bundle to **2.0.46**, with aligned pins and lockfile.

## Independent checks

- **84 condition controls**, **77 context controls** and the existing **58 token
  expansion controls** pass. The complete C++ package suite passes **568 tests**.
- `cpp-context-native-controls-r2/` checks **34 cases across 43 native profiles**.
  All known selections match every declared concrete profile; three unresolved
  selections retain their holds and their native variants produce different
  expansions. These variants are controls, not merged corpus metadata.
- `cpp-context-libc-native-r2/` traverses the actual captured LLVM `common.h` and
  its contained dependencies under independently established initial states.
  A native predefined-macro dump supplies exact available object replacements;
  a separate native definedness probe supplies explicit undefined or opaque
  known-defined inputs. No compiler features are guessed false from their
  absence in the object-macro dump.
- Both packaging-disabled and public-packaging synthetic drivers match Clang 22
  preprocessing exactly: six and 36 output tokens respectively, with 11 include
  observations each and no unavailable include observations. Eighteen unrelated
  unresolved names remain explicit in each selection. The public result includes
  the generated implementation spelling, public alias and implementation
  prototype. This is header/selection/token evidence, not production artifacts,
  native AST grading, original-file qualification or LLVM build-harness success.

These checks do not connect the helper to `CppAnalyzer`. Production profile
validation, ordered-context/cache binding, generated-token artifact provenance
and correct `decltype` alias/prototype modeling remain required. Both packaging
modes must be independently qualified before any new fixed-file admission.

## Validation and evidence

The first preflight caught two test-only dictionary inference errors; explicit
union annotations correct them, and focused package typing passes. The failed
preflight record is retained. The corrected preflight passes all eight checks.
The full repository gate exits **0**: **2,591 passed, 3 skipped**, **88%** coverage,
zero Semgrep findings, **887 indexed**, zero index failures and zero coverage
issues. `cpp-context-gate-result-r1.json` binds these results to source hashes.
The subsequent report-only update is checked separately.

The original `libc/src/math/generic/ceil.cpp` readiness probe captures 163 source
and header files, but both packaging profiles still stop at the directive or
binding safety limit. This is retained in
`cpp-context-original-ceil-readiness-r1/`; the isolated header checks above do
not establish original-file qualification. The next investigation measures
guarded-header revisits before changing any bound.

Durable ignored evidence under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `cpp-condition-native-r4/`: all 36 current supported condition results match
  native preprocessing; preceding source-bound comparisons remain retained;
- `cpp-context-native-controls-r1/` and `cpp-context-native-controls-r2/`: fixtures,
  concrete profiles, commands,
  stdout/stderr hashes and selection/hold records;
- `cpp-context-libc-native-r1/` and `cpp-context-libc-native-r2/`: successive
  source-bound real-header comparisons; all original headers remain untouched;
- `libc-macro-token-native-r3/`: all 38 preceding token comparisons pass again
  under the current helper;
- `cpp-context-quality-r1.log/.exit`: retained test-typing preflight failure;
- `cpp-condition-foundation-progress-r1.json`: preceding intermediate checkpoint.

The independent C census has also completed under unchanged C18 source:
`c18-pending-default-census-r2/` measures all 5,611 remaining historical C paths,
with **645 default-clean files and zero exceptions**. Those 645 still require
qualification or metadata investigation and add no verified fixes. The separate
comment-only counterfactuals suggest 22 C and 14 C++ clean-tree gains; that
smaller family remains behind the approved high-volume LLVM integration.
