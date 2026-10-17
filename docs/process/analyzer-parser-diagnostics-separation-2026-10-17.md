# Parser diagnostics: initial language/version/repository separation

This report precedes product fixes in the dedicated
`fix/analyzer-parser-diagnostics` worktree, based on analyzer-run source `91c4e07`.
It classifies the exact **25,762 distinct diagnostic paths** from analyzer
main-r1. Baseline SQLite file metadata supplies the actual selected analyzer and
source hash. Every source matched that hash when probed. Original benchmark
records, corpus files, main, and the active stress runtime remain unchanged.

## Confirmed separation

| Disposition | Files |
| --- | ---: |
| Intentionally malformed compiler/identifier fixtures | 351 |
| Python 3.15 syntax beyond declared Python grammar maximum 3.14 | 72 |
| C++26 pack-indexing fixtures completely explained by the newer syntax | 4 |
| LLVM lit directive file, not an executable shell program | 1 |
| Retained for investigation and fixes | 25,334 |
| **Baseline population** | **25,762** |

The malformed set contains 119 C-analyzed and 231 C++-analyzed LLVM files plus
one Python identifier fixture in CPython. Compiler cases require actual parsed
comment annotations explicitly expecting syntax/lexical errors; expected type
errors, directory names, and generic negative compiler exits are insufficient.
The skip-function-bodies fixture explicitly documents its garbage function body
and the harness option that avoids parsing it. CPython's `badsyntax_3131.py`
is imported by `test_unicode_identifiers.py:test_invalid`, which asserts the
specific invalid euro-sign identifier error.

The Python 3.15 set contains **43 production files and 29 tests**. It must not be
mislabelled malformed test data. Seventy-one files use PEP 810 lazy imports; one
uses unary-plus match patterns. In each case all baseline parse errors disappear
in a diagnostic-only same-byte ablation of that feature. Source bytes were never
edited. The version boundary comes from the analyzer's own capability contract,
which advertises Python targets through 3.14, and the pinned CPython 3.15 release
notes. The source checkout itself identifies as CPython 3.16.0a0.
See [PEP 810](https://peps.python.org/pep-0810/) and
[Python 3.15 changes](https://docs.python.org/3.15/whatsnew/3.15.html).

The four C++26 files have explicit future-mode RUN directives and pack-indexing
syntax. Diagnostic-only ablation completely clears their grammar errors. This
proves a localized grammar gap, not semantic correctness or compilation success.
Another **132 future-mode candidates remain in the investigation set**: a future
standard flag alone does not prove the reported error is caused by future syntax.
The [Clang standards table](https://clang.llvm.org/cxx_status.html#cxx2c) records
pack indexing as a C++26 feature. Mixed/new-feature cases will be refined as
further attribution proceeds; this initial separation is not the final audit.

## Language, version, and repository groups

The table below records baseline analyzer selection and **explicit RUN modes**.
A file can run under several standards; a comma-separated mode list is that
file group's test matrix, not an invented minimum version. Some C-analyzed files
also have C++ RUN modes, which is preserved rather than hidden. In the LLVM
malformed set, 152 files have no explicit RUN standard: their compiler-default
mode remains unspecified. Incidental standard flags in prose are not counted.
Per-file source hashes, exact annotations, and RUN directives are in the ignored
JSONL inventory described below.

| Category | Baseline language | Language version / explicit RUN modes | Repository | Files |
| --- | --- | --- | --- | ---: |
| Beyond Python ceiling | Python | Python 3.15 | python-cpython | 72 |
| Future C++26 syntax | C++ | C++26 pack indexing; RUN modes c++2c | cpp-llvm-project | 4 |
| Harness-only input | LLVM lit directives | LLVM lit directives; Bash version not applicable | cpp-llvm-project | 1 |
| Malformed fixture | C | c++11, c++2d, c11, c2x, c99 | cpp-llvm-project | 1 |
| Malformed fixture | C | c++11, c11, c99 | cpp-llvm-project | 1 |
| Malformed fixture | C | c++17, c++23, gnu++11, gnu11 | cpp-llvm-project | 1 |
| Malformed fixture | C | c++17, c2x | cpp-llvm-project | 1 |
| Malformed fixture | C | c++23, c23, c99 | cpp-llvm-project | 1 |
| Malformed fixture | C | c++98, c99 | cpp-llvm-project | 1 |
| Malformed fixture | C | c11 | cpp-llvm-project | 1 |
| Malformed fixture | C | c11, c23 | cpp-llvm-project | 1 |
| Malformed fixture | C | c11, c23, c2y, c99 | cpp-llvm-project | 1 |
| Malformed fixture | C | c11, c90, gnu11 | cpp-llvm-project | 1 |
| Malformed fixture | C | c11, c99 | cpp-llvm-project | 2 |
| Malformed fixture | C | c17, c23 | cpp-llvm-project | 1 |
| Malformed fixture | C | c17, c2x | cpp-llvm-project | 1 |
| Malformed fixture | C | c1x | cpp-llvm-project | 1 |
| Malformed fixture | C | c23 | cpp-llvm-project | 11 |
| Malformed fixture | C | c23, c2y | cpp-llvm-project | 2 |
| Malformed fixture | C | c2x | cpp-llvm-project | 6 |
| Malformed fixture | C | c2y | cpp-llvm-project | 2 |
| Malformed fixture | C | c89 | cpp-llvm-project | 1 |
| Malformed fixture | C | c99 | cpp-llvm-project | 3 |
| Malformed fixture | C | gnu2x | cpp-llvm-project | 1 |
| Malformed fixture | C | not specified by source harness | cpp-llvm-project | 78 |
| Malformed fixture | C++ | c++03, c++11 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++03, c++11, c++14, c++17 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++03, c++11, c++14, c++17, c++20, c++23 | cpp-llvm-project | 2 |
| Malformed fixture | C++ | c++03, c++26 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++03, c++98 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++11 | cpp-llvm-project | 47 |
| Malformed fixture | C++ | c++11, c++14, c++17, c++20, c++23, c++26, c++98 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++11, c++14, c++17, c++20, c++23, c++2c, c++98 | cpp-llvm-project | 9 |
| Malformed fixture | C++ | c++11, c++14, c++17, c++98 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++11, c++14, c++98 | cpp-llvm-project | 3 |
| Malformed fixture | C++ | c++11, c++17 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++11, c++17, c++20, c++2c, c++98 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++11, c++17, c++98, gnu++17 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++11, c++1z, c++98 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++11, c++20 | cpp-llvm-project | 2 |
| Malformed fixture | C++ | c++11, c++20, c++23 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++11, c++20, c++98 | cpp-llvm-project | 2 |
| Malformed fixture | C++ | c++11, c++2c | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++11, c++98 | cpp-llvm-project | 13 |
| Malformed fixture | C++ | c++14 | cpp-llvm-project | 6 |
| Malformed fixture | C++ | c++17 | cpp-llvm-project | 6 |
| Malformed fixture | C++ | c++17, c++20 | cpp-llvm-project | 3 |
| Malformed fixture | C++ | c++17, c++26 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++17, c++2a | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++17, c++2b, c++2c | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++17, c++2c | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++1y | cpp-llvm-project | 4 |
| Malformed fixture | C++ | c++1z | cpp-llvm-project | 2 |
| Malformed fixture | C++ | c++1z, c++2a | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++20 | cpp-llvm-project | 12 |
| Malformed fixture | C++ | c++20, c++23 | cpp-llvm-project | 3 |
| Malformed fixture | C++ | c++20, c++2c | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++23 | cpp-llvm-project | 2 |
| Malformed fixture | C++ | c++2a | cpp-llvm-project | 10 |
| Malformed fixture | C++ | c++2b | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++2c | cpp-llvm-project | 5 |
| Malformed fixture | C++ | c++2c, c++2d | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++2d | cpp-llvm-project | 1 |
| Malformed fixture | C++ | c++98 | cpp-llvm-project | 3 |
| Malformed fixture | C++ | gnu++11, gnu++98 | cpp-llvm-project | 1 |
| Malformed fixture | C++ | gnu++14, gnu++1z | cpp-llvm-project | 1 |
| Malformed fixture | C++ | not specified by source harness | cpp-llvm-project | 74 |
| Malformed fixture | Python | Python 3.x; PEP 3131 identifier negative fixture | python-cpython | 1 |

## Released-language problems retained for fixes

New to the grammar does not automatically mean outside the intended scope:

- Python 3.13 type-parameter defaults are within the declared Python ceiling.
  Host Python 3.13 accepts `test_type_params.py`; its six Tree-sitter errors
  therefore remain implementation work, not future-syntax exclusions. See
  [PEP 696](https://peps.python.org/pep-0696/).
- VictoriaMetrics' five Go files parse under native Go 1.27.1. They use
  `new(expression)`, introduced in released Go 1.26. No lower Go-version ceiling
  was identified in the analyzer contract, so they remain in the fix set.
  See the [Go 1.26 release notes](https://go.dev/doc/go1.26).
- All 46 Rust files pass unexpanded crate-root AST parsing with rustc 1.98.1:
  two Anyhow files under edition 2021, 29 Bevy and 15 Zed files under edition
  2024. These are syntax probes, not type checking, macro expansion, build or
  semantic-validation results. Their grammar gaps remain investigation work.
- Fourteen of the remaining 15 shell files pass native Bash 5.3.20 syntax checks.
  PostgreSQL's AIX script is rejected by this host's Bash; its intended platform
  shell still needs attribution and is not automatically called a deliberately
  malformed fixture. The excluded LLVM `.sh` file contains only a lit RUN line.
- The TSX tagged-template witness uses generic type arguments, supported since
  TypeScript 2.9. It is ordinary released syntax, not a future-language escape.
  See [TypeScript 2.9](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-2-9.html#generic-type-arguments-in-generic-tagged-templates).
- Native Clang 22.1.8 accepts `INIReader.cpp` under `-std=c++11`; its existing
  analyzer extracts 18 functions but withholds all symbol indexing after errors
  around the `INI_API` annotation macro. This is a concrete valid-source witness.

The remaining set is not asserted universally valid: it includes unresolved
fixture intent, language/dialect selection, templates, fragments, macro handling,
and mixed unsupported/new syntax. Those require evidence and corrections or a
more precise classification. No blanket warning suppression or directory-based
exclusion is an accepted fix.

## Evidence, reproducibility, and current status

Durable evidence is under this worktree's
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `baseline-inventory.json`, `collection-identity.json`, and `evidence.sqlite`
  bind the source population, baseline package grammars, selected analyzers,
  source hashes, byte/line error ranges, and harness annotations. Collection
  checkpoints per file and resumes without reparsing completed records.
- `classification-v3.jsonl` and `classification-v3.csv` give all 25,762 paths and
  their current dispositions. `malformed-fixtures-v3.csv` lists all 351 confirmed
  malformed paths; `beyond-grammar-files-v3.csv` lists the 76 newer-syntax paths;
  `remaining-fix-set-v3.csv` retains all 25,334 investigation paths.
- `separated-language-version-repo-v3.csv` and
  `classification-summary-v3.json` supply the complete grouped report.
- `python-feature-probes.json`, `cpp26-future-syntax-probes.json`,
  `native-go-bash-syntax-probes.json`, and `native-rust-syntax-probes.json` retain
  focused proof, command arguments and scope. Versioned initial classifications
  remain available; corrections never overwrite the original benchmark.

No product code has changed at this phase. The worktree has its own environment
and structural orientation index; main's environment and Git revision are
unchanged. Native probes do not index or persist to campaign databases. The
initial worktree-index command rejected an unsupported flag and was corrected
using the actual CLI help; that was an invocation issue, not a product defect.
The collector's initial database-path lookup also failed before records were
created; its failed source/log are retained and the corrected collection covered
all 25,762 paths without source drift or probe errors.

Next: continue attribution and implement localized fixes for the retained set,
add positive and negative regression oracles, replay the frozen population under
new identities, advance changed plugin/bundle distributions, and run required
quality and full validation gates. Full objective completion remains unproven.
