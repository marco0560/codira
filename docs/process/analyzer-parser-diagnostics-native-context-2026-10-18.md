# Native build context for recovered C diagnostics

The conditional-parser phase left 17 newly clean C paths unqualified because
standalone compilation lacked PostgreSQL/CPython headers or tried to compile an
included fragment by itself. This follow-up supplies that context without changing
the frozen corpus or analyzer implementation. Main and the original benchmark
identity remain untouched. The complete parser-fix objective remains open.

## Configuration and source ownership

PostgreSQL 20devel and CPython 3.16 configure successfully with Clang 22 in
separate out-of-tree directories beneath the ignored durable investigation:
`.artifacts/analysis/parser-diagnostics-20261017-r1/native-build-context-r1/`.
PostgreSQL uses `--with-ssl=openssl --without-readline CC=clang`; CPython uses
`--with-ensurepip=no CC=clang`. PostgreSQL's `src/backend generated-headers`
target generates its required headers in the build tree. No installation or
corpus regeneration is performed. These upstream development versions describe
the verification projects, not a change to Codira's supported Python grammar.

Compile commands come from each configured project's Makefiles. Only object
output/compilation actions are replaced with syntax/AST/dependency capture.
ECPG expected C fixtures use the thread test's flags, with the existing C output
marked old during the dry run so that the preprocessor is not rebuilt or run;
the compile input is then the original retained expected fixture.

Three paths require a containing translation unit:

| Source under examination | Native consumer |
| --- | --- |
| PostgreSQL `src/backend/regex/regc_nfa.c` | `src/backend/regex/regcomp.c` |
| PostgreSQL `src/include/libpq/libpq-be-fe-helpers.h` | `contrib/dblink/dblink.c` |
| CPython `Objects/mimalloc/page-queue.c` | `Objects/obmalloc.c`, through `mimalloc/static.c` and `page.c` |

Native AST grading uses physical source file ownership and byte offsets, including
Clang's repeated-file-name elision. Expected names must occur literally in the
original source, inside the analyzer's reported signature at its physical line.
Definitions supersede preceding declarations. An AST from a consumer is never
credited as though all its declarations belonged to the included fragment.

## Results and explicit controls

Configured Linux syntax checks accept 16 of the 17 candidates. Nine immediately
match all graded callable/type targets, totaling 135 declarations. Four more
qualify after independently checking the relevant modes:

| Repository / path | Additional native mode | Matched declarations |
| --- | --- | ---: |
| PostgreSQL `src/backend/regex/regc_nfa.c` | `REG_DEBUG` through `regcomp.c` | 67 |
| PostgreSQL `src/common/wchar.c` | Project `wchar_shlib.o` flags | 76 |
| CPython `Objects/mimalloc/page-queue.c` | `Py_DEBUG`, with `NDEBUG` undefined, through `obmalloc.c` | 16 |
| CPython `Python/pythonrun.c` | `USE_STACKCHECK` | 67 |

The debug modes independently account for written declarations absent from the
default native configuration. Passing `MI_DEBUG=2` directly was insufficient:
CPython's header overrides it according to `Py_DEBUG`. That unsuccessful grading
attempt is retained; the corrected probe uses the header's actual control.
PostgreSQL's ordinary `wchar.o` intentionally renames `pg_utf_mblen` to
`pg_utf_mblen_private`; its shared-library target preserves the literal source
name and permits a direct identity comparison. The base-mode discrepancies are
retained rather than silently discarded.

In total, **13 additional paths and 361 declarations** qualify. Classification-v12
therefore records **600 verified recoveries**, **24,719 unresolved paths**, and
443 separately classified fixtures/version cases/special inputs. This admission
checks callable/type identities, definition kinds, physical name positions and
signature containment. It does not claim complete macro, variable, field, call,
runtime or project-test-suite equivalence. No path qualifies from syntax
acceptance alone, and there are no analyzer code or distribution-version changes
in this follow-up.

## Four paths still open

PostgreSQL `src/backend/port/win32_shmem.c` requires the Windows target and SDK;
the Linux build configuration does not provide them. It remains unresolved,
not classified as malformed or as an unsupported source extension.

The three ECPG fixtures `thread-alloc.c`, `thread-descriptor.c` and
`thread-prep.c` pass configured Linux syntax checks but remain unqualified.
Their written Windows function signatures are inactive in that mode. They also
contain copied `sqlca.h` declarations suppressed by the guard set by an earlier
real include. The source analyzer retains those written declarations; the native
mode omits them. A Windows/alternate include-context check is still required to
validate all emitted variants. These discrepancies do not, by themselves,
establish malformed source or an extraction defect.

## Evidence and validation

The durable directory retains configure logs/status, generated headers,
Makefile dry runs, syntax diagnostics, compressed ASTs and exact commands.
`dependencies-r1/` binds the 16 successful base commands to 841 dependency paths;
`dependencies-extra-modes-r1/` binds the four qualifying additional modes to 501
dependency paths. These sets overlap. Each receipt includes resolved paths and
SHA-256 hashes, including generated headers and the compiler.

The authoritative comparisons are `artifacts-r1/results.jsonl`,
`artifacts-debug-r1/results.jsonl` and
`artifacts-extra-modes-r1/results.jsonl`. The unsuccessful direct mimalloc-debug
probe remains in `artifacts-debug-r1/`. Standalone failures, first-pass ECPG
command-discovery failures, and their corrected configured checks remain in
`syntax-r1/` and `syntax-r2/`.

All analyzer and package bytes remain equal to the preceding validated commit
`8ceb257`, whose full gate passed 1,853 tests with three skipped and 87% coverage.
The follow-up gate and evidence bindings are recorded in
`native-context-validation-receipt-r1.json` alongside classification-v12.
Semgrep is run outside the sandbox. Remaining work includes the four paths above,
the bulk C/C++ diagnostic population, and the outstanding Rust, Bash, JavaScript
and supported-version Python inputs.
