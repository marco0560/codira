# Parser follow-up: production input error and C++ annotation witnesses

These findings refine the
[initial separation](analyzer-parser-diagnostics-separation-2026-10-17.md)
without changing the frozen corpus or original campaign. They do not establish
completion of the remaining parser investigation.

## PostgreSQL AIX script: invalid production input

`src/backend/port/aix/mkldexport.sh` is production source with a declared
`#!/bin/sh` interpreter. It is not a deliberate malformed fixture or a
future-language test. Its error-message string contains an unescaped opening
backtick before `nm`, which begins command substitution instead of displaying
a literal character.

Host `/bin/sh -n` rejects the original with exit 2 and an unmatched-backtick
diagnosis. Escaping that one character in a separate diagnostic copy yields
exit 0 and a clean Tree-sitter parse. This is syntax evidence, not AIX execution
or a PostgreSQL build. The source digest matches the original baseline.

The correction is retained as `aix-mkldexport-correction.patch` under the
worktree-relative `.artifacts/analysis/parser-diagnostics-20261017-r1/` directory.
The original source is untouched. This path is classified as invalid production
input; suppressing its analyzer diagnostic would conceal the source error.
`aix-mkldexport-syntax-attribution-r1.json` retains the commands and outcomes.

## inih: valid C++11 annotations block symbol indexing

Native Clang accepts both `cpp/INIReader.cpp` and `cpp/INIReader.h` under
`-std=c++11 -x c++ -fsyntax-only`. Their parser errors are therefore concrete
valid-source analyzer problems, not malformed test inputs.

A diagnostic projection that blanks only parsed `INI_API` annotation tokens
clears both trees. Macro definitions, comments and strings must be preserved:
an earlier global substitution damaged definition names and incorrectly left
the header with errors. The scoped proof changes two annotation uses in the
implementation and sixteen in the header, preserving every byte coordinate.

A direct analyzer experiment with a substituted parser then permits indexing
of 18 implementation functions and the header's `INIReader` class with 18
methods. This is an extraction prototype with a known token projection, not a
committed C++ repair, backend persistence test, or general macro algorithm.

Evidence is retained as `cpp-ini-native-syntax-r1.json`,
`cpp-ini-api-scoped-probes-r1.json`, and
`cpp-ini-api-artifact-prototype-r1.json` under the same diagnostic directory.
Product work must distinguish actual annotations from uppercase type names,
retain malformed-source diagnostics, preserve source signatures/positions, and
account for cache invalidation if included headers become analysis inputs.
