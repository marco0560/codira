# Source-owned negative syntax fixtures — 2026-10-20

## Classification and scope

Classification v50 separates 13 additional LLVM fixtures, five C and eight C++, whose configured verification prefixes declare deliberate syntax errors. Native diagnostics match those source annotations under the recorded source-owned compiler profiles. These are exclusions, not analyzer fixes. The ledger now contains **3,973 verified fixes, 466 separated inputs and 21,323 open originals** (C 5,606; C++ 15,717), across all 25,762 original identities.

The complete separated export is `separated-inputs-v50-r1/` under `.artifacts/analysis/parser-diagnostics-20261017-r1/`. Its CSV and JSONL retain every path, repository revision, source digest, language version, declared modes and qualification evidence. `by-language-version-repository.csv` and README.md provide the full grouped report. Of the 466 separated inputs, 383 are deliberately malformed fixtures; the other 83 retain their earlier future-grammar and documented input-role classifications. Earlier exports remain immutable.

## Evidence and safeguards

The original classifier missed configured custom verification prefixes. `clang_syntax_intent_r3.py` reads parsed comments, matches only configured prefixes, respects prefix boundaries, counts and phase-two continuations, and uses Clang's comment-begin anchor for multiple directives in one comment. Only leading syntax-diagnostic phrases qualify; semantic errors containing those phrases do not. Ten independent native controls pass, including negative controls for strings, suffix collisions, unconfigured prefixes and semantic diagnostics. Earlier failed controls and raw output are retained.

`negative-syntax-prefix-native-r3/` rescored retained native output without recompilation: 13 of 16 screened originals have a matching source-owned syntax error. Four complete verification commands pass; nine fail other expectations. Those failures remain retained and are **not** reported as whole-harness success. The classification proves deliberate syntax-error intent under the selected profile; it does not assert that every declared mode or other source portion is invalid or correctly analyzed. Three unconfirmed originals remain open.

`negative-syntax-prefix-modes-r1/` records native standard macros under each selected profile. Explicit source standards and compiler defaults are distinguished; the C++26 entry denotes the compiler mode, not a claim that future syntax caused its analyzer gap.

| Language | Selected verified version | Repository | New exclusions |
| --- | --- | --- | --- |
| c | C11 | cpp-llvm-project | 1 |
| c | C17 | cpp-llvm-project | 1 |
| c | C23 | cpp-llvm-project | 3 |
| cpp | C++11 | cpp-llvm-project | 3 |
| cpp | C++17 | cpp-llvm-project | 1 |
| cpp | C++20 | cpp-llvm-project | 2 |
| cpp | C++26 compiler mode | cpp-llvm-project | 1 |
| cpp | C++98 | cpp-llvm-project | 1 |

`negative-syntax-prefix-admission-audit-v50-r1.json` independently checks all original identities, the 13 transitions, native output hashes, mode probes and exact grouped exports. All 25,749 other v49 rows, including every prior fix and exclusion, remain unchanged. The executed C++ implementation and its passing full-gate receipt remain those documented in [constructor argument calls](analyzer-parser-diagnostics-cpp-initializer-calls-2026-10-20.md); this classification adds no production change or new verified fix.

The full remediation objective remains incomplete. The next implementation work addresses repeated C++ header parsing, followed by qualification of larger shared-cause groups.
