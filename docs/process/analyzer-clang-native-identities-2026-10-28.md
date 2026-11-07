# Native C/C++ declaration identities

The first original LLVM macro-declaration indexing batch exposed shared identity
loss in the adapter layer: 14 of 15 C++ files failed the existing duplicate-ID
validator, although their 15 native frontend attempts completed successfully.
The core duplicate guard is retained.

## Measured causes and correction

Sixteen collision groups (12 variables and four constants) contain the same
nonempty compiler USR, compatible type and owner facts, and exactly one
compiler-observed definition. The C++ adapter selects that definition only
when the metadata proves the rows describe one entity. Missing or conflicting
identity/type facts remain held. The original declaration/definition observations
remain in the immutable native evidence; no new public provenance field is
invented to retain them.

Two `InsertPointTy` aliases in OpenMPOpt.cpp have distinct compiler USRs and
function/lambda owners. They remain separate artifacts with distinct identities.
Documentation copied onto redeclaration rows is attached once to its actual
owner and physical comment. Distinct comments on overloaded out-of-line
`parseMDField` methods bind to the finalized distinct callable IDs.

Repeated macro definitions use physical source anchors rather than one name-only
identity. Unique macro names retain their existing IDs. The measured original
inputs contain 31 VISIT_MD_FIELDS definitions at distinct offsets in LLParser.cpp
and 63 definitions across 11 repeated-name groups in six C files. Identical
callbacks for one physical definition collapse only when their source facts
agree; conflicting or unanchored repeated observations remain held. Artifact
ordering follows physical source order.

These shared causes define a 21-file validation set: the original 15 C++ files
and the six C files identified by the retained native-v5 census. They are not
21 verified whole-file fixes. Package versions advance to C 2.0.21 (logical 30),
C++ 2.0.50 (logical 49), and official bundle 2.0.85. Native protocol 5 and frontend
0.4.0 are unchanged.

## Evidence and qualification boundary

Evidence is under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `clang-macro-original-projection-20261028-r1/original-sqlite-index-r1/sqlite-duplicate-id-diagnosis-r1.json` records all 20 duplicate IDs across 14 failed files.
- The independent duplicate-ID review records all 16 compatible same-USR groups,
  the distinct aliases, and actual macro/comment anchors.
- `adapter-census-r4/c-native-duplicate-id-review-20261028-r1/` binds the 25 C
  source/native-output joins and the six affected macro-definition files.
- `clang-native-identity-integration-20261028-r1/` retains validation and delivery
  evidence for this change, including failed attempts.

Retained-output adapter replay proves consumer behavior only. Fresh indexer,
SQLite/DuckDB persistence, public-query behavior and independent complete-file
semantic grades remain distinct obligations. The earlier 43-fact scope census
must be rederived after this implementation freezes; two backend indexes and
86 selected-fact assertions alone do not establish whole-file correctness.
Prepared profiles are not cached analyzer results: new indexing can still invoke
the native helper. A validated replay/cache path is required before claiming
zero new compiler work.

The retained CFP-017 and CFP-061 independent AST references are explicitly partial,
not whole-file gold. A complete independent oracle for the original 15 is still
missing. See `clang-original15-whole-file-readiness-20261028-r1/readiness-addendum-r1.md`
for the corrected qualification plan and limits.

## Remaining architecture work

The optional shared Clang runtime, explicit profile preparation, dependency-bound
fingerprints, both analyzer adapters, exact calls, header projection, and
compiler-origin callable/declaration evidence are implemented in this branch.
This change addresses metadata identity failures exposed by original inputs.

Completion still requires complete-file independent qualification on real
repositories, scaling prepared contexts across the backlog, supported native
installation/platform evidence, and an explicit default/rollout decision.
The local Linux native build and prior clean-distribution checks do not qualify
all platforms or the current adapter versions. Tree-sitter remains the default.
The separately committed Rust coordinate fix on main must also be preserved when
this long-lived branch is eventually integrated; this phase does not merge main.

The canonical ledger remains 5,030 verified, 716 separated, 20,016 open.
No helper success, clean AST, selected metadata query or adapter replay changes
those counts. The full remediation objective remains active until independently
verified complete or paused at the operator's budget threshold.

## Validation result

Retained-output replay projects all 25 C inputs with 91/91 physical macro
definitions and all 15 C++ inputs with zero duplicate IDs. The C++ replay omits
the analysis fingerprint and 14 results remain partial; it verifies identities
only. Focused negative tests hold same-USR chains with zero or multiple definitions.

The parent preflight passes every check. The full gate passes: 3,228 tests,
3 skipped, 87% coverage, 994 indexed files, zero failures and zero coverage
issues. The four opt-in native macro qualification cases are enabled.
The raw log and terminal status remain in the phase's `fullgate-r1/` archive.

Fresh SQLite indexing of the original 15 completes in 207.45 seconds: 15 indexed,
zero failures, all persisted statuses report complete Clang analysis, zero
Tree-sitter fallbacks and 43 compiler-observed declarations. Public queries and
read-only persistence checks verify the repeated macros, scoped aliases and
separately owned method comments. Source, real Git index, helper, profile and
compilation-database guards remain unchanged.

A fresh DuckDB run also finishes indexing 15 originals with zero failures in
about 201.6 seconds. Its report serializer initially used a SQLite-specific
filename after indexing had completed. That failed attempt remains preserved;
read-only recovery uses the actual DuckDB file without reindexing. The final
parity receipt is separate. Neither run supplies the missing independent
whole-file semantic grade, and the canonical ledger is unchanged.
