# Compiler-observed macro declarations — 28 October 2026

The C and C++ adapters now preserve compiler-observed origins for existing
variable and constant artifacts, including supported owned record fields.
Declaration provenance uses a separate typed variant; existing callable
provenance remains unchanged. See [ADR-038](../adr/ADR-038-clang-metadata-and-exact-call-identities.md).

The current 50-original native census contains 359 macro-origin nonfunction
records. Applying the existing C++ declaration-scope predicate leaves 43 eligible
variables/constants across 14 files. The other 316 are intentionally excluded
locals. In CFP-073, all 282 macro-origin records are excluded locals; their
presence alone must not trigger `generated_declaration` partial coverage.
These counts diagnose shared causes, and do not establish original-file fixes.

Declaration evidence binds source/context identities, native metadata, a unique
compiler-observed macro event and exact invocation bytes. It preserves spelling
and expansion coordinates and owner/access metadata without reconstructing macro
tokens. Native source-range ends identify the start of the last token; object-like
macro invocations therefore accept a start and end at the same token position.
Out-of-range or ambiguous evidence remains held.

Both adapters compute the analysis input identity when macro declarations need
evidence, including files without macro-generated callables. Evidence queries
discriminate declaration payloads before accessing callable-only roles. A macro
static-member declaration sharing an identity with an ordinary out-of-line
definition remains held when their physical anchors cannot be represented
unambiguously; the ordinary definition retains its own source provenance.

## Evidence and limits

The durable family is
`.artifacts/analysis/parser-diagnostics-20261017-r1/clang-macro-declaration-qualification-20261028-r1/`.

- `scope-census-r2.json` binds the 43 eligible records and excluded-local counts
  to current native protocol 5 outputs and unchanged source hashes.
- The four `c-sqlite`, `c-duckdb`, `cpp-sqlite` and `cpp-duckdb` qualification
  receipts bind authored fixtures, prepared profiles, native helper and query
  results. The `backend-index-query-r6/` run passed four real indexing and
  evidence-query cases; its manifest SHA-256 is
  `b86d9d29db286aa297758ce92ba8cff72345f5b42a3b1cc734445e5210af8214`.
- C fixture coverage was complete. C++ retained the expected partial category
  for its deliberately ambiguous duplicate declaration/definition case.
- Earlier failed setup, compiler and query attempts remain intact. The r6
  evidence predates the resumed review and is reused without rewriting receipts.

Core tests cover the actual process-worker result envelope and both backends'
strict provenance JSON storage. Projection tests cover scope, owner, duplicate
identity and object-like range behavior. Authored fixtures and selected matching
facts do not establish independent whole-file semantics for the original cohort.
The ledger remains **5,030 verified / 716 separated / 20,016 open** until the
original admission requirements pass.

Required continuation includes qualification of the 14 original declaration
files and CFP-073, complete independent grading of the 50-file cohort, larger
context-backed groups, remaining metadata and platform/default qualification.
The full remediation objective remains unfinished.
