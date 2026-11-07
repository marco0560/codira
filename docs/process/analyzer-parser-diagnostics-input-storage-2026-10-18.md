# External analysis inputs: normalized metadata and backend persistence

The [C++ include-context groundwork](analyzer-parser-diagnostics-cpp-includes-2026-10-18.md)
establishes that source bytes alone do not identify header-dependent analysis.
This phase provides the normalized input identity and its physical persistence.
It does not yet activate dependency-based index planning or public C++ header
recovery. The corrected-file ledger therefore remains unchanged.

## Contracts and storage

`FileMetadataSnapshot.analysis_input_fingerprint` is an independent, default-empty
field. Its value does not replace `sha256`, analyzer name or analyzer version.
The optional `AnalysisInputFingerprintProvider` analyzer contract declares a
deterministic, nonempty identity of external analysis inputs, including relevant
negative lookups. Source-only analyzers do not need this hook. Fingerprinting
does not execute compilers, build scripts or source-generating processes.

The optional `AnalysisInputStateBackend` capability requires persistence of that
field through incremental and full-index writes and exposes a backend-owned
read keyed by absolute source path. It leaves the existing source-only backend
protocol intact. Core coordination still needs to enforce this capability before
accepting an analyzer that declares external inputs.

SQLite stores the additional value in its parameterized file insert. DuckDB
stores it in its structural row buffers and Arrow file table, covering both
incremental writes and native full-index bulk persistence. Owned and shared
connection reads preserve the caller's connection lifetime. Physical DDL remains
inside the backend packages; the core contains no backend-specific SQL.

The logical schema advances to 22; both physical schemas advance to 26. The
SQLite distribution advances to 2.0.4, DuckDB to 2.0.6 and official bundle to
2.0.21. Root pins, package contract assertions and the lockfile are aligned.
Existing physical version guards require older index schemas to be rebuilt.
The C++ distribution and its public analysis behavior remain unchanged in this
phase. These are local source-build changes, not a published release.

## Validation scope

Real SQLite and DuckDB tests persist both an external-input identity and the
empty source-only sentinel. They check owned and shared reads and replace the
external identity through the backend write-session lifecycle while proving
that source SHA-256 values remain unchanged. A separate real DuckDB test covers
the Arrow full-index path. Embedding eligibility is disabled in these tests;
they do not download a model or grade retrieval quality.

Existing package, bundle, normalized-contract, generation and incremental-index
tests are included in focused validation. The durable validation receipt records
the examined preflight and complete repository gate. A storage round-trip is
not evidence that the planner or readers already invalidate changed headers.

The final full repository gate exits zero with 1,793 tests passed, three skipped,
87% coverage, 801 files freshly indexed, zero failed files and zero coverage
issues. Semgrep runs outside the sandbox with zero findings. The final preflight
passes every selected quality check. After the broader 137-test focused run,
eight targeted checks cover the new storage paths, quality policy and schema
reporting expectations.

Earlier gate attempts exposed an outdated line reference for an existing lint
suppression and three reporting tests that still expected physical schema 25.
The policy reference is updated without adding a suppression. MCP and plugin
reporting expectations now use the selected or declared backend version. Failed
attempt evidence remains retained; the final full gate confirms these repairs.

## Required follow-up

1. Populate and validate the analyzer fingerprint during scanning and compare it
   with the persisted identity in incremental plans.
2. Bind worker analysis and retained failures to the same observed inputs.
3. Include dependency changes in CLI and family freshness checks, respecting
   physical schema guards before reading the new field.
4. Verify source-unchanged/header-changed indexing with both backends and worker
   strategies; then enable the public C++ include context and replay the corpus.

Durable evidence is retained under the worktree-relative
`.artifacts/analysis/parser-diagnostics-20261017-r1/` directory. The
`analysis-input-storage-validation-receipt-r1.json` record binds validation to
source digests once the gate has been examined. The original campaign, pinned
corpus and main checkout remain unchanged. The wider parser goal remains open.
