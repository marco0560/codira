# Compiler-observed callable qualification — 26 October 2026

[ADR-039](../adr/ADR-039-compiler-observed-generated-callable-evidence.md)
implements the generated-callable requirement left pending by ADR-038.
Version-one provenance remains strict and unchanged. Version two preserves
compiler-observed source/context identities, spelling/expansion coordinates and
correlated preprocessing events without fabricated token derivations.

The isolated native qualification used the actual CLI with deferred embeddings,
explicit backend selection, frozen profiles and helper-r5. Each backend indexed
nine translation units. Four queries verified the two source-invoked generated
functions on SQLite and DuckDB, including exact source SHA, analyzer input
fingerprint, USR, invocation text/range and `source_kind=compiler_generated`.
C body spelling is on line 31, invocation line 32; C++ body spelling is on line
53, invocation line 54. Name spelling coordinates remain separate.

The independent persisted-row exporter validates provenance with the core codec
and compares it with source-authored expectations. Both backend grades have
zero required failures; pending assertions decrease from eight to six. Those
six remain required: five requested header projections and the header-defined
`PARITY_CPP_CALL` declaration. Overall scope remains incomplete.

Native CLI/index/query evidence and the frozen adapter sources are retained in
the `clang-analyzer-parity-r1` worktree under
`.artifacts/analysis/clang-analyzer-port-20261026-r1/actual-macro-index-phase2-r4/`
and `phase2-source-freeze-r1/`. The independent grade, immutable copied source
and input records are retained in the `clang-exact-call-targets` worktree under
`.artifacts/analysis/clang-exact-call-targets/phase2-native-actual-grade-r1/`.
Root integration, final candidate qualification and validation receipts are
recorded under the remediation run's `phase2-integration-r1/` directory. Failed
and superseded attempts are retained, including incomplete top-level stream
capture in an interrupted early harness; later runs write streams before launch.

Core logical schema advances to 26; physical schemas remain 29. C and C++
distributions advance to 2.0.17 and 2.0.46, logical versions 26 and 45. Frontend
0.2.0/native protocol 3 is unchanged; official bundle advances to 2.0.81.
No publication or default-frontend change is made. No selected-field/native
qualification is counted as a verified original benchmark-file fix.
