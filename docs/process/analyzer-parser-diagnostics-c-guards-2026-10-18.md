# C language guards, annotation recovery and guarded API declarations

The C diagnostic cohort contains 6,087 paths still requiring investigation and 122
deliberately malformed controls. Source-bound replay now covers all 6,209 against the C
analyzer frozen at commit `1fbaf03`, without changing the corpus.

The first concrete witness is `c/inih/ini.h`. Its C++ linkage braces occur inside
positive `__cplusplus` guards, and its API declarations use locally defined annotation
macros. The C grammar previously reported errors and the extractor also stopped at the
outer header guard, omitting the API and callback typedefs.

The C package now owns a coordinate-preserving recovery module. Only positive
C++-language branches can be excluded for C syntax recovery; explicit source
redefinitions or undefinitions of `__cplusplus` prevent that inference. Comments,
literals and macro bodies remain opaque. Unknown platform conditions are not evaluated.
Compatible source-local object annotation macros are blanked only after their
definitions. Function-like, undefined and incompatible alternatives remain unsupported.
The original tree is retained unless the complete projection is clean. No headers, host
preprocessor state or build commands are read by the public analyzer, and no dependency
on the independently distributed C++ plugin is introduced.

File-scope extraction now traverses conditional wrappers while keeping function and type
bodies out of the module scope. It preserves prototypes for functions without written
definitions, rejects pointer variables as functions and retains callback typedef
alternatives with distinct identities. Original annotation prefixes, signature lines and
Doxygen attachment coordinates are preserved. Existing type/declaration behavior and
both real structural backends are checked alongside the new cases. One existing
exact-symbol test now expects a function prototype as a function while still rejecting
the pointer variable.

The C distribution advances to 2.0.1, logical analyzer version 11, and official bundle
to 2.0.24. Dependency pins, package assertions and the lockfile are aligned. Logical and
physical storage schemas remain unchanged. These are local source build changes, not a
published release.

The 64 focused checks pass. The complete preflight passes lint, formatting,
primary/package typing, Semgrep, fresh indexing, documentation and docstring checks.
Semgrep runs outside the sandbox. The public `ini.h` output matches five function
prototypes and three written callback typedef alternatives against the union of retained
Clang GNU C17 ASTs for both `INI_HANDLER_LINENO` configurations. This compares names,
physical name lines and declaration kinds; it does not prove all macro semantics or
complete type equivalence.

Full replay produces 562 newly clean candidates, zero analyzer exceptions and zero
malformed controls made clean. Host GNU C17 syntax triage accepts 193, rejects 369 and
times out on none. Rejection does not prove malformedness or failure under the actual
project harness. Artifact grading of all 193 accepted candidates qualifies 101 files
with 965 matched callable/type declarations. Native names and kinds match; each native
declaration-name token lies within an original normalized signature beginning at the
artifact's reported source line. Definitions supersede earlier declarations. The
comparison covers functions, prototypes, typedefs and named struct/union/enum
declarations; it excludes full macro expansion, fields, values, calls and actual
project-harness equivalence. The remaining 92 accepted candidates are not admitted. They
include empty comparisons and mismatches or oracle limitations; those sets can overlap.
The SN_env tag introduced through a return type in snowball headers is one concrete
mismatch retained for investigation.

The complete gate exits zero with 1,836 tests passed, three skipped, coverage 87%, 806
files freshly indexed, zero failed files and zero coverage issues. Final Semgrep runs
outside the sandbox without findings. Classification-v10 admits only the 101 qualified
paths: the total is 582 verified recoveries, with 24,737 paths still requiring
investigation/correction. Of those, 5,986 are C paths: 5,525 remain parser-partial and
461 are recovered candidates not yet independently qualified. Parser recovery and ledger
admission remain separate.

Durable evidence is under `.artifacts/analysis/parser-diagnostics-20261017-r1/`,
including `c-guards-full-replay-r1/`, `c-guards-native-triage-r1/`,
`c-ini-header-native-probe-r1.json`, `c-guards-native-artifacts-r1/`,
`c-guards-quality-r1.log`, `classification-summary-v10.json` and
`c-guards-validation-receipt-r1.json`. The other three inih C witnesses still have
conditional signatures/statements or fragment includes that this phase does not recover.
These and the remaining C, C++, Rust, Bash, JavaScript and Python diagnostics keep the
wider goal active.
