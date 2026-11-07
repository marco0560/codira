# Conditional C signatures and statement continuations

This phase follows the C guard/annotation correction and keeps the complete parser
objective open. The remaining inih witnesses expose two separate grammar limits:
directives interrupting an else-if chain in `ini.c`, and alternative complete signatures
sharing one body in `tests/unittest.c`.

The C package now creates coordinate-preserving views only when the base parse is
partial. Complete written signature alternatives are parsed separately; disjoint
alternatives use a linear covering set instead of Cartesian expansion. Only balanced,
grammar-valid conditional directives can become transparent. Statement alternatives must
each parse as complete statements or complete else continuations inside an existing
function body. Incomplete type fragments, invalid alternatives and unbalanced directives
retain partial status. No macro conditions, compiler flags or external headers are
evaluated.

The public analyzer requires every produced view to be clean. A failing view restores
the original partial analysis. The merger preserves written signatures, parameter lists
and physical source coordinates; deduplicates shared artifacts and calls; assigns unique
final variant identities; and remaps documentation owners. Module documentation uses the
original base tree. The call set remains an overapproximation of written alternatives,
not a condition-correlated runtime graph. Fragment includes such as `ini_xmacros.c`
remain unfinished.

The malformed-control replay exposed a separate unsafe annotation projection: `DROP
#include ...` could become a directive if DROP expanded to an empty annotation. The
preprocessor identifies directives before that expansion, so the transformation was
invalid. Both C and C++ now protect logical lines containing real hash tokens from
annotation deletion. Escaped newlines join protected lines; hashes inside comments and
literals do not. This preserves the existing negative LLVM fixture `dr1xx.c` rather than
counting it as a recovery.

Local versions are C 2.0.2 (logical 12), C++ 2.0.6 (logical 10), and official bundle
2.0.25. Storage schemas remain unchanged. Pins, lockfile and package assertions are
aligned. No release has been published.

The focused C/C++ matrix passes 117 checks. The final preflight passes lint, formatting,
primary/package typing, fresh indexing, docs and docstring audit; Semgrep executes
outside the sandbox with zero findings. Native inih probes match 17 callable
declarations across five GNU C17 modes: both callback modes for each source, plus
disabled stack allocation with custom allocators for `ini.c`. The first allocator probe
omitted `INI_USE_STACK=0`; its evidence is retained and the corrected probe records the
actual required controls.

The C replay covers all 6,209 diagnostic paths and produces 584 clean results, zero
exceptions and 22 newly recovered candidates awaiting independent admission. The 562
previously clean C results preserve their complete artifact payloads, and all 122
malformed controls remain partial. C++ preservation covers all 19,026 diagnostic paths:
the same 227 clean results, zero exceptions, zero regressions and no artifact changes.
Preservation is evaluated from canonical persisted JSON in
`cpp-hash-lines-preservation-audit-r1.json`; the inline replay summary compares
in-memory tuple/Path values with decoded JSON and is not a valid artifact-equality
check. Its false differences are superseded by that retained canonical audit, without
rerunning or discarding captured outputs.

The full gate exits zero: 1,853 tests pass, three are skipped, coverage is 87%, 809
files are freshly indexed, and failed files and coverage issues are zero. Semgrep
executes outside the sandbox without findings. Native GNU C17 accepts five of the 22 new
candidates. All five qualify by independent artifact grading, with 36 matched
declarations; the inih comparison additionally checks parameter names across the
explicit recorded modes. Classification-v11 admits those five paths, taking the total to
587 verified recoveries and 24,732 paths still open.

The other 17 candidates remain unqualified. Their probes lack PostgreSQL or CPython
include/generated build context, or require the actual including unit for a mimalloc
fragment. Read-only inventory confirms the source headers and configure scripts exist
while `pg_config.h` and `pyconfig.h` are absent. These are verification-context
requirements, not evidence of malformed source.

A real-backend probe on byte-identical inih copies checks default routing to C logical
version 12, both dumper signature rows, header/source prototypes, incremental reuse and
identical symbol results after a complete rebuild on SQLite and DuckDB. This is not
retrieval or condition-correlated execution grading. No ledger path is admitted on clean
parsing alone. Durable evidence is retained under
`.artifacts/analysis/parser-diagnostics-20261017-r1/`, including
`c-conditionals-full-replay-r2/`, `c-conditionals-native-ini-r3/`,
`cpp-hash-lines-full-replay-r1/`, `cpp-hash-lines-preservation-audit-r1.json`,
`c-conditionals-quality-r2.log`, `c-conditionals-native-artifacts-r1/`,
`c-conditionals-backend-probe-r1.json`, `classification-summary-v11.json` and
`c-conditionals-validation-receipt-r1.json`.
