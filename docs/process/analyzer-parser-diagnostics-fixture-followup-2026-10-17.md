# Parser fixture classification: counted and punctuation diagnostics

The [initial separation](analyzer-parser-diagnostics-separation-2026-10-17.md)
was deliberately conservative. A follow-up reviewed all **24,881 remaining
C/C++ paths** using the same frozen sources and actual parsed comments.
It recognizes counted/wildcard Clang annotations and additional expected
punctuation diagnostics. Fourteen additional files explicitly expect syntax
errors in active verification modes; they are deliberate negative fixtures.

All fourteen belong to **LLVM (`cpp-llvm-project`)**. Paths below are relative
to that repository. Language-standard flags are the explicit harness modes,
not invented minimum versions. Baseline analyzer selection is preserved in the
machine-readable inventory even where the harness requests another dialect.

| Harness language | Explicit standard modes | Source path |
| --- | --- | --- |
| C++ | `c++20` | `clang/test/CXX/basic/basic.link/p3.cpp` |
| C++ | `c++1z` (C++17 alias) | `clang/test/CXX/temp/temp.deduct.guide/p1.cpp` |
| C++ | `c++11`, `c++17`, plus an unspecified compiler-default mode | `clang/test/CXX/temp/temp.param/p2.cpp` |
| C++ | Compiler default, not specified | `clang/test/FixIt/fixit-punctuator-spelling.cpp` |
| C | Compiler default, not specified | `clang/test/Lexer/eof-include.c` |
| C++ | `c++2a` (C++20 alias) | `clang/test/PCH/cxx2a-constraints-crash.cpp` |
| C++ | `c++20`, `c++23` | `clang/test/Parser/cxx2b-init-statement.cpp` |
| C | Compiler default, not specified | `clang/test/Parser/designator.c` |
| Objective-C++ | `c++11` with `-x objective-c++` | `clang/test/Parser/objcxx11-invalid-lambda.cpp` |
| C / C++ | `c2x` and `c++17`, including `-x c++` | `clang/test/Sema/generic-selection-type-extension.c` |
| C++ | `c++11` | `clang/test/SemaCXX/PR16677.cpp` |
| C++ | `c++11`, `c++17` | `clang/test/SemaCXX/conditional-expr.cpp` |
| C++ | `c++98`, `c++11`, `c++1y` (C++14 alias) | `clang/test/SemaCXX/cxx1y-variable-templates_in_class.cpp` |
| GNU C++ | `gnu++11`, `gnu++14`, `gnu++17`, `gnu++20` | `clang/test/SemaCXX/type-traits.cpp` |

The review verifies actual comment nodes, source SHA-256 equality and RUN
directives selecting the `expected` diagnostic prefix. It does not classify
files merely because a compiler test expects a type error. Examples include
missing delimiters, missing case-label colons and malformed declarations.
Counted forms such as `expected-error 2{{...}}` were outside the initial matcher.

This is evidence of per-file fixture intent under the recorded modes, not
attribution of every Tree-sitter error or a claim that every portion is invalid
under every standard. The module-linkage file is also a split-file harness
input. The Objective-C++ fixture must not be misrepresented as ordinary C++
simply because the baseline selected the C++ analyzer.

The confirmed malformed inventory grows from **351 to 365**: 364 LLVM fixtures
and the previously established CPython identifier fixture. Source and campaign
records remain untouched. Full Clang harness execution is not claimed.

Resumable review databases and immutable review/confirmation records are under
the worktree-relative `.artifacts/analysis/parser-diagnostics-20261017-r1/`:
`clang-counted-annotation-review-r1.sqlite`,
`clang-counted-annotation-review-r2.sqlite`, and
`clang-syntax-annotation-confirmed-r2.json`. The latest complete per-file
dispositions are `classification-v6.jsonl` and `classification-v6.csv`.

After the verified Go and complete TypeScript repairs, 386 baseline paths are
fixed. Alongside the 365 malformed fixtures, 72 Python grammar-ceiling cases,
four C++26 fixtures, one harness-only shell input and one invalid production
shell script, **24,933 paths remain under investigation**. The overall goal
remains active.
