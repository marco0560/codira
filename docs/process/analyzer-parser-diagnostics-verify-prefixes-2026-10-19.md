# Parser diagnostics: verified negative fixtures and complete separation groups

Five additional LLVM C++ files are separated as intentional syntax-negative fixtures. The initial classifier missed non-default verification prefixes (`both`, `all`) and named source locations (`@#marker`). The retained native responses confirm six matching-language reference consumers with exit zero. Three commands add an explicit syntax-only action to the recorded RUN arguments; no shell, generated-file or experimental-interpreter consumer was substituted.

This is fixture-role classification, not a product fix. It does not attribute every parser diagnostic in mixed test files, qualify all configurations, or infer a future-language ceiling. Mode-dependent rejections alone do not justify separation of otherwise valid syntax.

The current ledger is **759 verified fixes**, **453 separately classified files**, and **24,550 open paths**: C **5,897**, C++ **18,653**, by original analyzer attribution. This is approximately **3.0% fixed** within the current correction population and **4.7% accounted for** across the original 25,762 paths; counts measure files, not effort.

## Newly separated files

| Language | Recorded language version | Repository | File |
| --- | --- | --- | --- |
| C++ | c++20, c++23 | LLVM | `clang/test/AST/ByteCode/cxx23.cpp` |
| C++ | c++20 | LLVM | `clang/test/AST/ByteCode/invalid.cpp` |
| C++ | c++20 | LLVM | `clang/test/AST/ByteCode/typeid.cpp` |
| C++ | c++2c | LLVM | `clang/test/Parser/cxx2c-binding-pack.cpp` |
| C++ | not specified by source harness | LLVM | `clang/test/ParserHLSL/hlsl_parameter_modifiers.cpp` |

The HLSL-directory fixture is run as C++, not HLSL. Its standard is left unspecified because the source RUN does not set it. `c++2c` is retained as the exact source flag for the binding-pack negative test; it is not silently converted into an analyzer support declaration.

## Complete separated population by language, version and repository

Version combinations reproduce each source harness or its previously established feature evidence. Each file appears once; a row listing multiple modes is not a count for each mode. The disposition distinguishes malformed tests, future grammar, templates and other confirmed non-program roles. An invalid production script is reported separately from deliberate test inputs.

| Language | Version evidence | Repository | Disposition | Files |
| --- | --- | --- | --- | ---: |
| bash | Declared /bin/sh on AIX; host sh syntax checked; AIX runtime not exercised | c-postgres | confirmed_invalid_production_source | 1 |
| bash | LLVM lit directives; Bash version not applicable | cpp-llvm-project | confirmed_harness_only_nonprogram_fixture | 1 |
| c | c++11, c++2d, c11, c2x, c99 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c++11, c11, c99 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c++17, c++23, gnu++11, gnu11 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c++17, c2x | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 2 |
| c | c++23, c23, c99 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c++98, c99 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c11 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c11, c23 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c11, c23, c2y, c99 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c11, c90, gnu11 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c11, c99 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 2 |
| c | c17, c23 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c17, c2x | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c1x | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c23 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 11 |
| c | c23, c2y | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 2 |
| c | c2x | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 6 |
| c | c2y | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 2 |
| c | c89 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | c99 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 3 |
| c | gnu2x | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| c | not specified by source harness | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 80 |
| c | not specified by source harness | cpp-llvm-project | confirmed_pragma_diagnostic_fixture | 1 |
| c | not specified by source harness | cpp-llvm-project | confirmed_preprocessor_only_fixture | 1 |
| cpp | C++26 pack indexing; RUN modes c++2c | cpp-llvm-project | confirmed_future_cpp26_fixture | 4 |
| cpp | c++03, c++11 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++03, c++11, c++14, c++17 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++03, c++11, c++14, c++17, c++20, c++23 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 2 |
| cpp | c++03, c++26 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++03, c++98 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++11 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 49 |
| cpp | c++11, c++14, c++17, c++20, c++23, c++26, c++98 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++11, c++14, c++17, c++20, c++23, c++2c, c++98 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 9 |
| cpp | c++11, c++14, c++17, c++98 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++11, c++14, c++98 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 3 |
| cpp | c++11, c++17 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 3 |
| cpp | c++11, c++17, c++20, c++2c, c++98 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++11, c++17, c++98, gnu++17 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++11, c++1y, c++98 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++11, c++1z, c++98 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++11, c++20 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 2 |
| cpp | c++11, c++20, c++23 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++11, c++20, c++98 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 2 |
| cpp | c++11, c++2c | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++11, c++98 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 13 |
| cpp | c++14 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 6 |
| cpp | c++17 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 6 |
| cpp | c++17, c++20 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 3 |
| cpp | c++17, c++26 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++17, c++2a | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++17, c++2b, c++2c | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++17, c++2c | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++1y | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 4 |
| cpp | c++1z | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 3 |
| cpp | c++1z, c++2a | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++20 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 15 |
| cpp | c++20, c++23 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 5 |
| cpp | c++20, c++2c | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++23 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 2 |
| cpp | c++2a | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 11 |
| cpp | c++2b | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++2c | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 6 |
| cpp | c++2c, c++2d | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++2d | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | c++98 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 3 |
| cpp | gnu++11, gnu++14, gnu++17, gnu++20 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | gnu++11, gnu++98 | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | gnu++14, gnu++1z | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 1 |
| cpp | not specified by source harness | cpp-llvm-project | confirmed_intentionally_malformed_fixture | 76 |
| javascript | No applicable ECMAScript version for raw extraction fixture | python-django | confirmed_extraction_only_nonprogram_fixture | 1 |
| javascript | Template grammar; output ECMAScript minimum not declared | python-cpython | confirmed_template_input | 1 |
| javascript | Template grammar; output ECMAScript minimum not declared | python-django | confirmed_template_input | 1 |
| python | Python 3.15 | python-cpython | confirmed_beyond_declared_python_grammar | 72 |
| python | Python 3.x; PEP 3131 identifier negative fixture | python-cpython | confirmed_intentionally_malformed_fixture | 1 |

## Held-open candidates and evidence limits

The prefix audit found 22 candidates. Forty-eight bounded reference cc1 probes cover 20 files: 16 commands pass, spanning ten files, with no timeouts. Only the five reviewed files above enter this classification. Seventeen remain open, including mode-sensitive constructs, a foreign-language consumer and a generated split-file module harness. `-verify-directives` is unsupported by the installed Clang 22.1.8, and some other diagnostics differ from the pinned test expectations. Those failures are not evidence of malformed production code or unsupported analyzer grammar.

The source-only annotation audit and all raw native stdout/stderr are retained under `.artifacts/analysis/parser-diagnostics-20261017-r1/verify-prefix-audit-r1/` and `verify-prefix-consumers-r1/`. The immutable ledger, CSV and grouped totals are `classification-v21.jsonl`, `classification-v21.csv` and `classification-summary-v21.json`. The classification/report generator is retained there as `admit_verify_prefix_fixtures_r1.py`; `finalize_verify_prefix_report_r1.py` derives the final syntax-only adaptation count from native records.

The preceding header-selection correction remains a prerequisite: 98 headers now select C++ correctly, while their unresolved include/macro contexts still prevent clean extraction. No such header is counted as a verified parser fix. The full correction objective remains open.
