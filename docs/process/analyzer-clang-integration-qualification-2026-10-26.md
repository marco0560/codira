# Shared Clang frontend integration qualification — 26 October 2026

The measured evidence supports adopting a shared Clang frontend as the primary
development direction for C/C++ analysis with reproducible compiler context.
Tree-sitter remains the default and fallback. This is an experimental optional
integration, with explicit partial metadata coverage; it does not establish a
new default, general platform support, publication readiness or backlog closure.

[ADR-037](../adr/ADR-037-optional-shared-clang-production-integration.md)
records the approved boundary. The shared `codira-clang-frontend` package stays
outside core and is consumed by both independently distributed analyzer plugins.
No further custom-preprocessor development was added in this phase.

## Implemented behavior

Both plugins accept an explicit `frontend = "clang"` selection, helper/build
receipt paths, a durable attempt root, and either a compilation database or a
generic captured-profile manifest. Installing the optional `clang` extra does
not build a compiler helper or execute a project build system. Helper building
and profile preparation are explicit operations.

Preparation captures compiler-observed dependencies, ordered effective include
roots, directory membership, a controlled compiler environment, and Clang's
actual target triple and sysroot. Generic profile v2 retains those bindings;
older contextless profiles require preparation. Sysroot coverage means the
resolved setting and observed dependency/search-root identities, not a hash of
every unused file beneath the sysroot.

The adapter preserves written definitions, namespace-qualified names, class and
method ownership, selected declarations including aliases, and source-written
calls with physical coordinates. Implicit declarations and template
instantiations remain distinguishable from source-written symbols. Missing,
stale or unsupported context produces an explicit partial Tree-sitter fallback;
outputs from the two frontends are not merged.

## Independent evidence

Qualification used the actual indexer and independently authored source oracles.
The final frozen runtime was exercised on both SQLite and DuckDB:

| Input | Persisted checks | Result on both backends |
| --- | --- | --- |
| Authored C fixture | Definitions, prototype/definition ownership, macro-mediated calls, inactive branch, positions | Matched |
| Authored C++ fixture | Qualified namespaces, aliases, class/method ownership, overload declarations, template provenance, calls and positions | Matched within declared DTO scope |
| Original PostgreSQL `thread-descriptor.c` | Original repository/source identity and retained command, definitions, owned calls, inactive Windows branch | Matched |

These are six source/backend cases. PostgreSQL used the original readonly
checkout at revision `7beefa8d46978341aed7ba14cc82bf37c0564948` and source
SHA-256 `850c1e19b81cf38f423af9d4db0e667c66ccf27911ae7bbfa3e338815cc7fb10`.
Its prepared profile bound 102 files and actual include-search context. It was
not replaced by a copied or synthetic source. All final cases recorded stable
inputs, parsed Clang results and explicit partial Codira DTO coverage.

Unchanged-source reindexing was also exercised in the same databases:

| Changed input | Verified behavior on SQLite and DuckDB |
| --- | --- |
| Header contents | Stale-profile fallback; fresh preparation changes the expected C and C++ symbols; restoration returns baseline facts |
| Compiler profile | `-DQUAL_CPP_ENABLED=0` removes the C++ marker; restoring the original profile restores it |
| Helper bytes at the same configured path | Identical configuration bytes; changed helper content causes a held fallback; exact-byte restoration returns parsed Clang facts |

The helper-content test used a qualification-owned copy with a documented
derived receipt. Original helper binaries and build receipts were untouched.
The older-helper selection test is compatibility evidence, not the proof of
content-based cache invalidation.

## Boundaries and remaining work

`CallSite` cannot persist the compiler's exact overload target USR or signature.
Overloaded calls therefore remain unresolved in the index; they are never
assigned an arbitrary internal edge. Native overload resolution was checked
separately and is not claimed as persisted dispatch qualification.

Imports, documentation, macro declarations, variables, body flags and other
language-specific fields listed in analysis status remain omitted. A complete
profile or frontend parse does not make this a complete whole-file analyzer
result. Runtime LLVM/Clang shared-library binaries are not individually hashed.
The tested native toolchain is Clang 22.1.8 on this Linux host; broader native
distribution and platform support remain unqualified. Attempt/state outputs
must be kept outside bound include roots to avoid self-invalidating profiles.

The next production work should finish the DTO/call-resolution contract and
make exact build-profile/generated-header preparation reusable across real
repositories. The earlier 200-input pilot does not support extrapolating a
whole-backlog recovery rate from these three inputs.

The canonical v79 ledger remains **5,030 verified / 716 separated / 20,016 open**.
No clean AST, helper test or selected-field integration grade was counted as a
new verified original-file fix.

## Reproducibility and validation records

The immutable evidence root is
`.artifacts/analysis/parser-diagnostics-20261017-r1/clang-production-integration-20261026-r1/`.
Its `qualification/final-qualification-r4-addendum.json` pins the final runtime,
both independent grades and actual index receipts. Its
`qualification/cache-qualification-final-r1.json` pins the cache phases.
Parent reference audits verified 8 final-addendum and 41 cache-report file hashes
without mismatches. Original raw attempts and research helpers remain in their
referenced worktrees; failed, stale, zero-file and superseded runs are retained.

Early compile/link/CLI failures recovered from the agent transcript are labeled
as tool transcript evidence, not original process byte streams. Subsequent
native attempts retain exact stdout/stderr bytes and terminal receipts.

Local distribution versions are frontend **0.1.0**, C **2.0.15**, C++ **2.0.44**,
installer **2.0.7** and official bundle **2.0.79**. The installer catalog was
regenerated. No packages were published. Wheel/sdist inspection verified that
native source and `py.typed` ship without automatic native compilation.

Delivery requires the combined repository preflight and full repository gate.
The examined command, source tree, exit status and test totals are recorded in
the evidence root's `validation/final-gate-receipt.json`; that terminal record
is authoritative for validation, rather than an estimated test count here.
