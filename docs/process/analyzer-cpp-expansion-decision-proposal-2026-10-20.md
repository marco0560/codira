# Proposed C++ declaration-macro capability — 2026-10-20

Status: **proposed; integration is awaiting the operator's decision**.

[ADR-030](../adr/ADR-030-syntax-only-macro-analysis.md) adopts a shared
syntax-only macro policy and says not to broaden it silently in a language
plugin. In particular, its indexing boundary excludes expanding declarative
macros, choosing conditional branches and synthesizing declarations from a
potential expansion. The current C++ README also explicitly excludes general
function-macro expansion and conditional selection. Recovering LLVM libc's
public-packaging function wrappers crosses that boundary, unlike removing
compatible annotation-only replacements.

The tested token helper is not called by indexing. Keeping it isolated permits
review and compiler comparison without changing the accepted analyzer contract.

## Option A — add an explicit C++ capability

Adopt a new ADR allowing bounded declaration-macro expansion only under an
explicit C++ preprocessing profile. Keep existing unconfigured behavior and the
Rust contract unchanged. The proposed configuration is an opt-in
`preprocessor_definitions` mapping with explicit defined/undefined inputs,
combined with the existing contained include paths and namespace bindings.

The capability must:

- Use only captured source/header bytes and the supplied profile, with their
  exact identities included in analysis/cache fingerprints.
- Respect source/include order and source overrides. Unknown or conflicting
  conditions affecting an expansion must remain an explicit hold; no inferred
  compiler, platform or packaging defaults.
- Avoid invoking compilers or build tools during indexing and avoid adding a
  mandatory compiler dependency.
- Preserve the actual generated implementation and public alias identities in
  both measured packaging variants, with correct parameters and lexical calls.
- Distinguish generated spellings from original byte spans. Original snippets
  and body coordinates must stay source-backed; no fabricated source positions.
- Bound work and reject unsupported expansion semantics explicitly.
- Advance the logical analyzer version when integrated behavior changes and
  qualify original files against independently retained native evidence before
  changing the classification ledger.

This addresses the observed shared blocker in the 1,607-file inventory. That
inventory is not a promised recovery count. Scope includes source-context
selection, token provenance and declaration modeling; it is more work than a
grammar-only correction and needs focused regression coverage.

## Option B — retain the accepted syntax-only boundary

Keep function-generating macros outside indexing. Record the libc wrapper
family as an unresolved analyzer limitation and prioritize the next shared
parser/metadata cause allowed by the current contract. Do not count these files
as fixed or move them into the deliberately malformed/future-syntax population:
the retained original/native probes demonstrate ordinary valid source.

This avoids changing the analyzer's capability boundary but leaves this large
candidate family unresolved. The unused expansion helper can remain pending
until there is an accepted capability decision; its tests are not proof of a
production correction.

## Recommendation

Choose A to pursue the high-volume wrapper family under an explicit, bounded
contract. Acceptance of this proposal authorizes the new C++ capability and its
ADR; it does not imply that token-level evidence alone qualifies corpus fixes.

Evidence and the implementation's current limits are recorded in the
[expansion report](analyzer-parser-diagnostics-libc-macro-expansion-2026-10-20.md).
