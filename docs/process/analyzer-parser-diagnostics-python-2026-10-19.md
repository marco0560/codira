# Python grammar diagnostics and original-coordinate recovery

This phase fixes the three remaining supported-version Python diagnostic paths.
All three original files pass native Python 3.14.7 AST parsing. They are ordinary
CPython test modules, not deliberately malformed files. Malformed Python snippets
inside their string literals do not make their containing modules invalid.
The pinned corpus, original benchmark identity and main checkout stay unchanged.

| Language | Syntax version relevant to attribution | Repository | Relative path | Bundled grammar gap |
| --- | --- | --- | --- | --- |
| Python | File includes Python 3.14 template strings; parenthesized starred subscripts require 3.11 | cpython | `Lib/test/test_annotationlib.py` | Parenthesized starred operands in subscriptions and extended-slice parameter annotations. |
| Python | Valid within the declared 3.10–3.14 support range; also accepted by native 3.13 | cpython | `Lib/test/test_compile.py` | Attribute names continued on the next physical line inside parentheses, including indentation below the surrounding suite. |
| Python | Type-parameter defaults require 3.13; native 3.13 and 3.14 accept the file | cpython | `Lib/test/test_type_params.py` | Default separators in generic function type parameters. |

## Correction and bounds

The package-owned parser uses narrowly selected parse views only when the original
provider tree has errors. It adapts declaration type-default separators,
parenthesized starred subscript operands, independently valid slice annotations
and whitespace after attribute dots inside delimiters. Expressions and their
command/call tokens are retained. A recovered view must parse wholly without errors;
otherwise the original partial tree is returned.

Provider tree edits restore original byte offsets and row/UTF-8 byte-column points
after inserted parentheses and whitespace changes. Extracted names, signatures and
other text are always read from original source bytes. Production recovery invokes
neither a host AST parser nor an interpreter subprocess and executes no source.
Literal/comment contents do not select transformations. Malformed type-list
lookalikes, missing operands and incomplete attributes retain diagnostics.
A bare line break after an attribute dot outside delimiters is also diagnosed:
the bundled provider otherwise accepts that invalid input. Explicit backslash
continuations remain valid.

The independent comparison also exposed two metadata defects: non-ASCII attribute
names used character length to calculate byte columns, and definition end lines
included trailing comment trivia. Columns now use UTF-8 byte length; class/function
ends use the final non-comment syntax token. This retains comments in the normalized
syntax tree and changes only persisted declaration bounds, not comment contents.

Type-default syntax produces an explicit Python 3.13 feature diagnostic when the
declared target is older. Grammar recovery does not remove the target-version
contract. Python distribution **2.0.2**, logical analyzer **13**, artifact revision
**v2**, and official bundle **2.0.29** invalidate the affected cached semantics;
root pins, package assertions and generated lockfile agree. No release is published.

## Verification and retained failures

Independent native ASTs agree on **433 function/method records, 45 class records
and 2,410 lexical call records** for the three original sources. The comparison
checks literal identity, start/end lines, the existing simplified signature and
parameter contract, and call kind/target/base with physical byte positions.
It excludes nested callable bodies and includes nested-definition decorator calls
as the existing lexical execution-scope contract does. It does not claim expanded,
type-resolved or runtime semantics. The initial oracle omissions for nested
decorators and its incompatible signature policy are retained alongside the
corrected native reader; the product's existing signature contract is preserved.

All **60 focused tests** pass, including original-coordinate checks with CRLF,
Unicode and combined gaps. Native Python 3.14 syntax-only checks accept ten positive
controls and reject twelve malformed controls. Additional boundary tests inject
the exact tokenizer internal failure observed in the real corpus. No corpus module
or test is executed during native syntax checking.

Real SQLite and DuckDB checks index byte-identical copies of the three original
sources at declared target 3.14. Both route to Python logical version 13, retain
all **478 checked class/function/method symbol rows**, reuse all three sources and
preserve those rows after a full rebuild. These are routing/persistence probes,
not retrieval or test execution qualifications.

The full replay covers every **8,954 `.py` file** in the pinned corpus, including
Python inputs under repositories grouped by other implementation languages. The
first attempt exposed a new host-tokenizer `SystemError` on `test_fstring.py`.
The original bundled parser handles that file; optional lexical inspection now
falls back to the original provider decision when the host tokenizer fails.
That failure and the first replay remain retained. The corrected replay recovers exactly the three original paths, with zero
exceptions or parsing-status regressions. Another 262 previously clean payloads
change only in definition ends or UTF-8 call columns. Each changed field requires
an independent native-position audit before admission; parse cleanliness alone
is insufficient. The native Python AST also fails on `test_fstring.py` with a
`ValueError`; its one changed end boundary is instead checked using a complete
native-parsed final statement and a suffix containing only comments/whitespace.
That local proof does not qualify the complete f-string module against native AST.

The first full gate passed 1,940 tests with three skips and failed two capability
metadata assertions still expecting logical version 12 and distribution 2.0.1.
Those assertions are aligned to logical 13 / distribution 2.0.2, without changing
the capability checks. Failed `python-grammar-r1` gate evidence is retained.
The fresh complete gate passes **1,942 tests**, with three skips and **87%**
coverage. It indexes **823 files**, with zero failed files and zero coverage
issues. Semgrep runs outside the sandbox with zero findings.

## Evidence and admission

Evidence is retained under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `python-native-314-r1/`: original-file native AST capture;
- `python-native-items-r5/`: complete cohort identity/signature/call comparisons;
- `python-grammar-native-controls-r1/`: source-bound positive/negative controls;
- `python-grammar-focused-r2.log`: focused tests;
- `python-grammar-full-replay-r1/`, `r2/` and `r3/`: immutable source-bound replays;
- `python-changed-positions-r2/`: changed-field/native-position comparisons;
- `python-grammar-backend-probe-r1.json`: both real backend checks;
- `python-grammar-quality-r4.log`: final inexpensive checks, Semgrep outside sandbox;
- `classification-v17.jsonl`, CSV and summary, plus
  `python-grammar-validation-receipt-r1.json`: admission after the examined full gate.

Classification-v17 admits these three original paths after validation:
**663 verified recoveries**, **446 separately classified inputs**, and **24,653
original diagnostic paths still open**, all in C/C++. The full goal remains open.
