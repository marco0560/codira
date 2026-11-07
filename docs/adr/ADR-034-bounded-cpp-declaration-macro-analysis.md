# ADR-034 — Bounded opt-in C++ declaration-macro analysis

**Date:** 20/10/2026
**Status:** Accepted by the operator (option A)

## Context

[ADR-030](ADR-030-syntax-only-macro-analysis.md) establishes the shared syntax-only
macro boundary. LLVM libc contains valid function-generating macros that cannot
be recovered by removing annotations. Its `LLVM_LIBC_FUNCTION` wrapper can create
a differently named implementation, an implementation prototype and a public
alias, depending on explicitly selected packaging settings. The retained native
probes demonstrate both variants. The 1,607-file candidate inventory is not a
promised recovery count.

The operator accepted option A in the
[capability proposal](../process/analyzer-cpp-expansion-decision-proposal-2026-10-20.md).
This decision permits the C++ exception below. It does not relax Rust analysis or
authorize general build-system execution.

## Decision

Add bounded declaration-macro expansion to the independently distributed C++
analyzer, enabled only by an explicit preprocessing profile. Existing
unconfigured behavior remains syntax-only. No compiler, linker, build system,
external process or mandatory compiler dependency is added to indexing.

### Explicit inputs and active definitions

The opt-in `preprocessor_definitions` mapping supplies explicit initial macro
states alongside existing contained include paths and
namespace bindings. String values supply object replacements, `true` means a
defined macro with replacement `1`, and `false` explicitly means undefined.
The value `{ "defined": true }` records a known-defined macro whose replacement
is unavailable. It can prove definedness, but cannot supply invented tokens or
a numeric value. Missing initial states remain unknown.
An absent mapping disables the new capability. Invalid keys, values or
unsupported replacement syntax fail configuration explicitly.

Only captured repository-contained source/header snapshots and this profile may
supply expansion inputs. Preserve actual include/directive order, definition
availability, source overrides, undefinitions and guarded re-inclusion. Do not
infer compiler, platform, language-version or packaging settings. An unknown or
conflicting condition affecting a required expansion prevents that expansion;
an unused unknown branch need not invalidate an otherwise proven declaration.
Unsupported conditional syntax must remain explicit rather than selecting a
convenient branch. Diagnostic evidence must distinguish insufficient context
from malformed original source.

Selected definitions may use bounded object/function replacement, fixed and
variadic arguments, argument prescan/rescan, stringification and token pasting.
The tested helper supplies token substitution only; its tests do not establish
active-definition correctness or production integration.

### Explicit intrinsic-query observations

An explicit profile may also supply bounded `preprocessor_features` answers for
pure compiler intrinsics and `preprocessor_header_queries` observations for
literal `__has_include` / `__has_include_next` calls. These are operator results,
not opaque macro replacements or whole conditional-branch answers. Preserve exact
native integer literals, including attribute version values. An operator must
remain the initial opaque binding; source redefinition or undefinition cannot be
overridden by an observation. Pure-feature operands require unchanged explicit
initial undefined states rather than guessed macro substitutions.

Header-search observations are specific to a translation unit. Bind them to the
full contained source/include-graph SHA-256, the configuration fingerprint with
only the header observations removed, the exact owner and invocation span,
literal query tokens, and every original include directive in the root-to-owner
chain. Include search order or source/dependency changes invalidate their use.
A missing, stale, unobserved or macro-produced site remains unknown. Observations
do not add external header reads or a compiler invocation to indexing.

Conditional expressions still pass through the bounded source evaluator after
licensed operator substitution. Unsupported conditional grammar remains held;
a native `#if` result cannot bypass it. Native query capture, compiler/dependency
bindings and physical-origin controls are QA evidence, independently retained
from the profile consumed by indexing. A complete product is still subject to
actual-file native metadata and persisted-index qualification.

### Provenance and normalized artifacts

Expansion may expose real declarations, aliases and definitions only when the
captured definitions and supplied profile determine their identities. Preserve
actual generated implementation names, public alias identities, parameter
names, namespace ownership and lexical calls. Do not silently replace the
public-packaging case with the easier packaging-disabled case.

Keep original invocation/body bytes and original source coordinates. Generated
token spellings must carry their derivation separately from physical spelling
locations. An argument-derived anchor is not proof that generated bytes occur
there. Do not fabricate physical ranges, source snippets, signatures or
relationships. Extend normalized metadata explicitly where existing models
cannot truthfully express a generated identity or declaration relationship.
Macro-replacement implementation calls must not be mistaken for calls literally
written in the original body.

### Bounds, failure and reuse

Bound input bytes, tokens, expansion depth/steps, include traversal and
conditional processing. Reject unsupported lexical or replacement semantics;
never accept a partially interpreted expansion as complete indexing. Preserve
original diagnostics and a conservative partial result when required evidence
is unavailable. Do not make a whole file clean by suppressing unrelated errors.

Bind configuration, ordered resolution outcomes, exact captured dependency
bytes, explicit undefined states and provenance/schema versions to analysis and
incremental-cache identity. Relevant context changes must invalidate reuse even
when original source bytes are unchanged. Advance the logical C++ analyzer
version for integrated behavior and coordinate plugin/bundle distributions.
Any normalized-artifact or cache-schema change follows the repository runtime
version rules.

## Validation and delivery

Before connecting expansion to indexing, validate definition selection and
source reaching independently of token substitution: explicit true/false and
unknown conditions, source redefinition/undefinition, include order and guards,
unsupported forms, bounds and context invalidation. Preserve existing default
behavior and previously qualified artifacts.

Validate both observed LLVM libc packaging variants against independent native
compiler/preprocessor captures. Compare actual generated names, declarations,
parameters, lexical calls, namespaces and provenance; include deliberately wrong
artifacts that must be rejected. Native compilation during QA is distinct from
indexing and does not establish original project-harness or runtime success.

Only source-bound original-file results passing complete independent comparison
may enter the fixed ledger. Clean parser trees, token parity, a passing repository
gate and the candidate inventory alone do not qualify files. Preserve existing
campaigns, failed attempts and raw native evidence under fresh run identities.

## Consequences

This capability can address a high-volume valid-source family while retaining
explicit build assumptions and source provenance. It adds conditional-context,
expansion and generated-declaration complexity that requires bounded rejection
and stronger cache identity. Unsupported families remain open; they are not
reclassified as malformed or future syntax.
