# C++ parser follow-up: source-local annotation macros

This phase follows the [initial separation](analyzer-parser-diagnostics-separation-2026-10-17.md)
and [production-source witnesses](analyzer-parser-diagnostics-source-findings-2026-10-17.md).
The original campaign, pinned corpus, main checkout and configuration are unchanged.
It does not establish a benchmark-wide clean bill.

## Cause and correction

Tree-sitter can misread an annotation macro as a type or declarator, producing
errors in otherwise valid declarations. The package now recognizes object macros
defined in the same source file whose replacements are empty or parsed GNU,
Microsoft or standard C++ attributes. Same-file annotation aliases are resolved
to a fixed point. Uppercase spelling alone is not evidence of an annotation.

Every definition of a name must be compatible. Function macros, conflicting
redefinitions and names appearing in `#undef` are excluded. Uses must follow
the required definitions. A projection blanks only parsed identifier uses;
definitions, preprocessor conditions, comments and literals remain intact.
Every byte coordinate and newline is preserved. The complete projected tree
must be clean; otherwise the original diagnostic tree remains authoritative.

Extraction reads original bytes. Leading annotation prefixes are restored in
function signatures and declaration line numbers, without crossing siblings or
comments. Regression tests cover unresolved macros, alias cycles, use before
definition, conflicting definitions, function macros, invalid declarations,
unrelated errors, UTF-8 call columns and source preservation.

The native comparison also exposed omitted anonymous-namespace functions and
free operator overloads in the recovered Catch2 file. Anonymous namespaces now
have an explicit `(anonymous namespace)` identity component, preventing their
members from colliding with names in the enclosing namespace. Operator names
are recognized as callable declarators.

No header is read to recover annotation definitions. Header-based recovery,
including `INIReader.cpp`, remains unfinished: it requires dependency-aware
reuse so a changed header cannot leave a stale source result. Compiler invocation,
build configuration and conditional evaluation are not product dependencies.

## Frozen replay and independent checks

| Population | Files | Result |
| --- | ---: | --- |
| Remaining C++ investigation paths | 18,780 | All source hashes verified and replayed |
| Local annotation recovery | 88 | Clean product tree and direct extraction |
| Deliberately malformed C++ fixtures | 242 | None became clean |
| Separated future C++26 fixtures | 4 | None became clean |

The 88 recovered paths comprise inih's `INIReader.h`, one Catch2 source file
and 86 LLVM files. Their original harness language declarations are retained
per path: 76 unspecified, five C++14, three C++17, two C++11, one C++2a and
one with C++98/GNU++98/GNU++11 modes. The annotation spellings also include
compiler extensions; a missing language flag is not a language-version finding.

Clang independently accepts the original `INIReader.h` under C++11 and the
Catch2 source under C++23. All 18 explicit header methods and seven Catch2
function definitions match by name and source name line. Five synthetic
annotation variants also match Clang, including five runtime `callee` call
targets, lines and UTF-8 byte columns. The compiler is a diagnostic oracle.
Other production call targets are not compared by this oracle.

These are syntax and stated artifact checks, not execution, type-resolution
grading, backend-persistence evidence or native verification of all 88 files.
The other 86 recovered paths still need native/harness attribution and extraction
checks before being counted as fully verified fixes.

A subsequent host-mode triage of all 88 files produces 39 matching target
comparisons, 32 host-mode rejections and 17 comparison differences. These
commands do not execute the LLVM lit harness. Rejections need their build,
target or harness settings; differences include omitted linkage-block and
struct declarations, template handling and conditional-branch/oracle effects.
They remain follow-up findings, not new malformed-source classifications.

## Validation and retained evidence

All 35 focused C++ and bundle tests plus the root extras contract test pass.
The repository quality preflight passes
outside the sandbox, including fresh indexing, documentation, Ruff, typing,
docstring audit and Semgrep (21 rules, 170 files, zero findings). The initial
preflight's formatting and typing failures are retained beside the corrected
passing attempt. The first full gate reports 1,756 passed, three skipped and
one failure: the root extras contract still expected C++ distribution 2.0.1.
The assertion is aligned to the updated 2.0.2 manifest; its focused check passes.
That failed gate's log and exit status are retained. The corrected full gate's
terminal outcome is exit 0: 1,757 passed, three skipped, 86% coverage, and a
fresh index with 793 files, zero failures and zero coverage issues. Embeddings
are deferred by the validator. The examined outcome and source digests are
retained in `cpp-local-annotation-validation-receipt-r1.json`.

The C++ distribution advances to 2.0.2, logical analyzer version 7; root pins,
lockfile and official bundle 2.0.18 are aligned. The logical version invalidates
older C++ extraction results without changing raw source hashes.

Evidence is retained under the worktree-relative
`.artifacts/analysis/parser-diagnostics-20261017-r1/` directory:

- `cpp-local-annotation-product-replay-r2.jsonl` and its summary retain final
  product replay, source digests and recovered artifacts.
- `cpp-annotation-native-oracle-r4.json`, its script, AST JSON and stderr retain
  the independent checks. Earlier oracle attempts retain the observations that
  exposed the omitted definitions and distinguished source annotation lines
  from compiler declaration/name locations.
- `cpp-local-annotation-quality-r4.log` and `.exit` retain the final preflight.
- `cpp-annotation-native-triage-r5.json` and its AST/stderr files retain the
  host-mode triage, with target differences summarized separately.
- `cpp-local-annotation-validation-receipt-r1.json` binds the examined full gate
  and final replay to product-source digests.

The broader parser investigation remains active across C/C++, Python, Rust,
Bash and JavaScript. The previously verified Go and TypeScript corrections
remain separate completed phases.
