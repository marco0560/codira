# Compiler pragma operators: recovery and qualification

The C and C++ analyzers now recognize Microsoft `__pragma(...)` and the standard
`_Pragma("...")` preprocessing operator. The provider previously reported parser
errors or extracted these operators as callable declarations/calls. This phase
uses package-owned parse views and preserves the pinned corpus, original run
identity and main checkout.

## Behavior and limits

The view blanks only recognized operator spans while retaining byte widths and
line endings. Balanced Microsoft payloads may contain strings, comments and
nested parentheses; standard operands must be a single ordinary or L-prefixed
string literal. Incomplete operands, ambiguous preprocessing continuations and
transformations that would promote a trailing `#` into a directive are refused.
Comments, literals and preprocessing definitions do not select recovery. Local
definitions/declarations shadowing either spelling disable it; the C++ analyzer
also checks captured include-context sources. This does not add C include-context
resolution. Recovered trees must be wholly clean or the original tree is retained.
Declaration prefixes keep original API annotation text and physical coordinates.
The production implementation launches no compiler and executes no source.

Pragma payloads remain opaque, as existing hash-prefixed pragmas do. This phase
does not qualify ABI, layout, code generation, expanded macros, OpenACC lowering
or runtime call resolution. C distribution **2.0.3**, logical version **13**, C++
distribution **2.0.7**, logical version **11**, and official bundle **2.0.30**
update the affected cache identities and pins; no release is published.

## Evidence

Evidence root: `.artifacts/analysis/parser-diagnostics-20261017-r1/`.
The full discovery inventory contains **77,192 distinct files** (36,580 C and
60,335 C++ discovery memberships). The source guard returns unchanged bytes for
files without either literal spelling. All **193 potentially affected analyses**
were replayed against the committed baseline and current implementation, including
previously clean and cross-language header analyses. This is not a claim that all
77,192 files were reanalyzed. Results: **19 newly clean analyses**, **zero parser
status regressions**, **zero exceptions**, **51 unchanged clean payloads** and
**two changed clean payloads**. The latter differ only by removal of three false
`_Pragma` calls; every other canonical field is identical.

`pragma-full-surface-r4/` binds source and include dependency digests and retains
complete before/after payloads. `pragma-clean-deltas-r2/` audits all changed fields.
The whole-file native `pragma-attribute.cpp` harness crashes Clang 22.1.8 at an
unrelated attribute later in the file; its stderr is retained and no full native
qualification is claimed for that previously clean file. The OpenACC syntax probe
for the other changed clean file is recorded independently. The operator grammar
is independently checked with **36 source-bound native controls**, all matching
expected acceptance/rejection (`pragma-native-controls-r5/`).

The **153 focused tests** cover positive/negative syntax, source positions,
shadowing, captured headers, directive promotion and combined API annotations.
Native probes use Clang **22.1.8**. Their exact modes and exclusions are retained:

| Language / repository | Explicit probe mode | Qualified original diagnostic paths |
| --- | --- | --- |
| C / CPython | Configured Linux C11, real build includes/configuration | `Include/Python.h`: independently empty own native declaration set and matching own macro `Py_PYTHON_H`. |
| C / LLVM | C11; AIX32 for PowerPC input; recorded Microsoft `-verify` mode for region input | `CodeGen/PowerPC/pragma-comment.c`, `Lexer/pragma-region.c`, `Misc/emit-html.c`, `Preprocessor/_Pragma-physloc.c`. |
| C++ / LLVM | C++17; `-fopenacc` for OpenACC inputs | `CodeGenCXX/optnone-pragma-optimize-off.cpp`; `SemaOpenACC/{atomic,cache,declare,init,shutdown}-construct-ast.cpp`. |
| C++ / clang-tools-extra | C++17, Microsoft extensions, Linux and Windows target syntax checks | `test/clang-tidy/checkers/portability/avoid-pragma-comment.cpp`. |

The complete native comparison covers source-owned named callable definitions and
named record/typedef/enum/namespace identities with physical name lines: **33 named
targets**, plus the independently checked CPython macro. Prototypes, variables,
fields, unnamed closures and calls are outside that qualification profile. Empty
native sets are proven independently, never inferred from the product output.
`pragma-native-candidates-r1/` and `pragma-native-originals-r1/` retain the proofs.
The AIX input is qualified as combined-source named definitions, not its split-file,
32/64-bit code-generation harness. HTML generation, optimization and PCH consumers
are likewise not claimed. Probe standards do not establish a minimum syntax version
or override a fixture RUN line that does not specify a standard.

Four newly clean original paths remain **unqualified and open**: C
`Parser/pragma-pack.c` misses nested record `T`; C++ OpenACC
`{combined-construct-ast,compute-construct-ast,loop-ast}.cpp` miss member alias
`type`. Native comparison exposed these real extraction omissions; removing
parser diagnostics is insufficient for admission.

## Separately classified input roles

Two C/LLVM paths are separated by actual consumer evidence, not counted as fixes:

- `Preprocessor/pragma-comment-elf.c` deliberately expects an invalid pragma-kind
  diagnostic. All three recorded `-verify -fms-extensions` target modes (PS4, PS5,
  Linux) pass. Their RUN lines do not specify a C standard.
- `Preprocessor/comment_save.c` is preprocessing-only input. Both exact recorded
  producers (`-E -C`, also with `-fminimize-whitespace`) and their strict-whitespace
  FileCheck checks pass. Native C AST acceptance is not its consumer contract.

The latter proof is in `pragma-pp-fixture-r1/`; the former is in
`pragma-native-originals-r1/`. Neither is attributed to unsupported future syntax.

## Validation and admission

The full repository gate passes **1,988 tests**, with **three skips** and **87%**
coverage. The fresh index contains **826 files**, zero failures and zero coverage
issues. Semgrep runs outside the sandbox: 177 files, 21 rules, zero findings.

After that examined gate, `classification-v18.jsonl`, CSV and summary admit
**12 verified original paths** and **two separately classified inputs**. The ledger
now contains **675 verified recoveries**, **448 separately classified inputs** and
**24,639 open original diagnostic paths** (C: **5,961**; C++: **18,678**). The four
extraction mismatches remain open. Nineteen newly clean analyses are not nineteen
verified fixes. `compiler-pragma-validation-receipt-r1.json` binds validation and
retained evidence to the admitted sources. The overall goal remains open.
