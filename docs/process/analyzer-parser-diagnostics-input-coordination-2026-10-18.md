# Header-dependent C++ analysis and index coordination

The [include-context groundwork](analyzer-parser-diagnostics-cpp-includes-2026-10-18.md)
and [input-storage phase](analyzer-parser-diagnostics-input-storage-2026-10-18.md) are
now connected to the public analyzer and indexing lifecycle. These earlier reports
describe their historical phases; this report describes the subsequent integration. The
original corpus and benchmark records remain unchanged.

## Failure and corrected behavior

An annotation macro declared in an included header can prevent the source parser from
recognizing otherwise valid C++. Resolving that annotation changes analysis even when
the translation unit itself is unchanged. Previously, source-only incremental reuse
could retain stale results after a header edit.

The C++ analyzer now captures contained literal includes and uses the captured header
definitions for conservative annotation recovery. Missing paths and lookup precedence
are part of the identity. It does not search host system includes or invoke a compiler.
Existing macro safety restrictions still apply; a parser-clean result alone does not
establish complete semantic extraction.

Core coordination treats the optional analyzer input identity independently of source
SHA-256. Scan/planning, successful file metadata, retained failures and before/after
worker checks use the same identity. An unchanged failure is reused only with matching
inputs and analysis configuration. Changed inputs trigger reanalysis; concurrent input
changes discard that worker result. CLI and family freshness checks reject changed
external inputs after existing physical-schema and ownership checks. A backend lacking
the optional persistence capability is rejected when an actual indexed source needs
external inputs.

An optional content-based reuse validator checks captured source/header hashes and
positive/negative lookup outcomes without reparsing include syntax. It does not use
unchanged mtime or size as proof. Legacy or conservatively rejected identities fall back
to exact fingerprint recomputation. A matching analyzer configuration is required before
reuse.

## Source-owned methods and original header declarations

The first public `INIReader.cpp` probe exposed a second defect: its recovered qualified
definitions were emitted as free functions because the class was only declared in
`INIReader.h`. The normalized function contract now carries optional `owner_name` and
`owner_stable_id` fields. Source-owned method definitions refer to the original header
class; the analyzer does not copy a class declaration into the source file. Exact
captured class evidence is required; conflicting namespace/type-alias evidence prevents
ownership inference.

Both structural backends persist those references and bind the class relationship when
rebuilding derived graph indexes. Header replacement detaches external methods before
deleting the old declaration, then rebinds against the replacement. Queries, symbol
kinds and embedding names use the explicit owner reference. Real-backend tests cover
both source-before-header and header-before-source ordering, header replacement,
incremental indexing and full reconstruction.

The integration test also exposed an unresolved `Widget.run -> Widget.helper` edge. The
C++ analyzer now records a class-qualified member call when an included class declares
that method and lexical evidence permits the lookup. Parameters, local declarations,
nested scopes and explicit global qualification prevent unqualified-call inference. This
C++ rule does not change generic name lookup for other language analyzers.

## Versions and validation evidence

The logical schema is 23; SQLite and DuckDB physical schemas are 27. Local package
versions are C++ 2.0.5 (logical analyzer version 9), SQLite 2.0.5, DuckDB 2.0.7 and
official bundle 2.0.23. Root dependency pins, lockfile and package assertions are
aligned. These are local source changes, not a published release.

The public native probe verifies all 18 explicit methods in `INIReader.cpp` against the
retained Clang AST after verifying the original source and captured header hashes.
Names, physical name lines, method kinds and original class owner references match. It
emits no duplicate source-local class. This does not grade all types, calls, overload
resolution or compiler configurations.

The focused backend/package/input matrix initially passed 101 tests and failed only an
outdated lint-policy line reference. After correcting that maintained reference, both
policy tests pass. Four method-owner/backend cases pass. Member-call tests cover direct
calls, initializer calls, explicit receivers, global qualification and lexical
shadowing. The primary typing check passes 493 source files. The final focused follow-up
passes 27 tests, including both repaired gate failures. The final preflight passes lint,
formatting, primary/package typing, Semgrep, fresh indexing, documentation build and
docstring audit. Semgrep runs outside the sandbox. The first full gate completed with
1,816 tests passed, three skipped and two failures: a routing test supplied a fictitious
source hash and the Python golden payload lacked the new optional owner fields. The
routing test now supplies the real hash. The golden fixture is regenerated through its
existing normalization helper, with an explicit check that only null owner fields
changed. The final full gate exits zero: 1,820 tests pass, three are skipped, coverage
is 87%, 803 files are freshly indexed, and failed files and coverage issues are zero.
Semgrep runs outside the sandbox without findings.

A first complete public replay covers all 19,026 C++ diagnostic paths with zero
exceptions, 227 parser-clean results and no regression of previously clean paths. That
initial replay uses the earlier member-call normalization. A second complete replay with
the final source binding independently reproduces the same 227 clean results, zero
exceptions and zero regressions of previously clean paths. The native follow-up now
matches all 12 explicit internal INIReader method-call sites by caller, target and
physical line, with no missing or extra compared calls. Compiler callbacks and library
resolution remain outside this comparison.

The grammar also parses an initialized local function-pointer declaration as nested call
expressions. Such ambiguous bodies retain original call records; extra unresolved
records from that grammar interpretation remain a separate extraction issue. This phase
does not claim to resolve every C++ call.

Durable evidence is retained under
`.artifacts/analysis/parser-diagnostics-20261017-r1/`, including
`cpp-public-include-native-probe-r2.json`, `analysis-input-coordinator-quality-r3.log`,
the resumable `cpp-public-includes-full-replay-r2/` run and
`cpp-public-native-definitions-r1/`. The final gate receipt is
`analysis-input-coordinator-validation-receipt-r1.json`. Of 136 new candidates triaged
in host C++23 mode, 56 are accepted and 80 rejected. A rejected host probe does not
establish malformedness or actual harness failure. Native artifact grading of the 56
accepted files admits 39 with nonempty explicit definitions: all 221 source-owned
definition names, physical name lines and function/method kinds match. Empty definition
sets and mismatches or oracle limitations are not admitted. This grades the stated
artifact scope, not every semantic behavior. The new immutable classification is
`classification-v9`: 481 verified recovered paths and 24,838 paths still requiring
investigation/correction. The 139 parser-clean candidates therefore add only 39 verified
ledger paths.

On disposable byte-identical copies of the INIReader source and headers, both real
backends bind all 18 source methods to the original header class and resolve the 12
native-verified internal member edges. The original corpus is never indexed or modified
by that probe. Its receipt is `cpp-ini-backend-native-probe-r1.json`. The wider
parser-fix goal remains active.
