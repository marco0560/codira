# Complex type and operator diagnostics: qualified recovery

After native structural comparison, complete source binding and the examined full
gate, classification-v20 admits **80 original paths**: 63 C and 17 C++ in LLVM.
Totals are **759 verified recoveries**, **448 separately classified inputs** and
**24,555 open original diagnostic paths**. Parser cleanliness and native compilation
alone never advance that registry.

## Root causes and language attribution

The provider grammars reject ordinary complex declarations such as `_Complex double`.
GNU alternative spellings `__complex` and `__complex__`, integer complex types and
real/imaginary operators have additional gaps. The original benchmark uses default
C/C++ analyzer settings: its retained SQLite and DuckDB configuration files do not
supply project include search roots. The pinned corpus and main checkout remain
unchanged; all corrections and fresh evidence use the dedicated worktree.

| Language / version probe | Repository | Observed cause |
| --- | --- | --- |
| C11, with GNU extensions where used | LLVM; text candidates also occur in CPython | Missing complex type grammar; GNU real/imaginary operators can be mistaken for external calls. Magic-method strings in CPython are text candidates, not language-keyword proof. |
| C++17 with GNU extensions | LLVM | The same type/operator gaps, including unnamed parameters and overload binding. Strict ISO acceptance is a separate property. |
| C/C++ header routing, default configuration | LLVM libc++ | `__cxx03/__algorithm/all_of.h` is currently claimed by C because incomplete C++ trees hide the template declaration node used by header detection. A path component does not prove a minimum language version. This cause remains open. |
| C++ include/macro inputs, default configuration | LLVM / libc | `LLVM_ABI` and `LIBC_INLINE` declarations remain blocked by absent include context or unsupported declaration-macro forms. Missing project context is not proof of malformed or future-language source. This cause remains open. |

`current-header-routing-r1.json` records the actual current dispatcher, not a guessed
analyzer. `complex-keyword-candidates-r1.json` finds 406 still-open original paths
by text; string/comment matches do not establish grammar defects or qualification.

## Correction and controls

Package-owned, equal-width parse views distinguish complex modifiers, bare complex
type names and real/imaginary operands. Stored text and physical byte positions
come from the original source. Qualifier placeholders retain exactly the keyword
width, including unnamed trailing parameter types. This avoids truncating the
source type used by overload identity. A tagged non-call view preserves nested
operand calls through the C grammar's cast ambiguity; artifact extraction excludes
the tag. No source program, compiler or interpreter is executed by production code.
Placeholders assert no volatility, nonreturning, alignment, arithmetic, ABI or
runtime semantics. Their role is structural parsing only.

Comments, literals and preprocessing directives are shielded. Source-local keyword
definitions/undefinitions disable the affected projection; C++ also checks captured
header definitions. Known reserved operators without operands remain diagnosed even
if the original grammar treated their spellings as ordinary identifiers. Duplicate
complex specifiers accepted by Clang with a warning retain their original text;
the first native-control attempt incorrectly expected rejection, and is retained.

The focused package suites pass **242 tests**. Native controls match all **81**
expected outcomes: 72 accepted programs/modes, eight malformed-input rejections
and one strict C++17 rejection of a GNU extension. The matching strict C99
floating-complex control is accepted. Coverage includes type spelling and
ordering, accepted duplicates, named/unnamed parameters, nested operand calls,
UTF-8/CRLF coordinates, overload separation, local/captured macro overrides and
malformed operands. Native controls and their exact flags/warnings are retained;
strict-standard boundaries are checked separately from GNU-mode acceptance.
Local versions are C distribution 2.0.5 / logical 15, C++ distribution
2.0.9 / logical 13, and official bundle 2.0.32. Nothing is published.

## Full possible surface and measured parsing result

The source inventory rechecks **77,192 files**. A graph built with the actual default
literal-include resolver covers **60,468 nodes**, including **133 additional captured
headers**. Reverse include closure is included so changes in a header cannot escape
review merely because its consumer lacks the keyword. No include roots are inferred.

The baseline is commit `08c0af6`. All **583 potentially affected analyses** retain
canonical before/after payloads and source/dependency hashes. Results:

- **189 newly clean analyses**: 108 C, 81 C++;
- **zero new parsing diagnostics**, **zero exceptions**;
- **three previously clean payloads changed**;
- 171 newly clean original-ledger paths, with unchanged current analyzer ownership;
  the other 18 recoveries are cross-analyzer discovery memberships.

These are parsing observations, not 189 verified fixes.

## Native results and remaining work

Raw original-source Clang 22.1.8 syntax/AST probes cover the 171 candidates and the
three clean deltas. **116 compile in the explicit host C11/C++17 probe modes**;
**58 reject**, with no timeouts. Every response and stderr is retained before grading.
Rejection under that mode does not prove malformed input, unsupported language
version or failure of the recorded target/verify/code-generation consumer.

The corrected independent structural comparison matches **80 new candidate paths**
and one complete clean-file profile. SourceLocation token lengths, macro-argument
locations and source-template instantiation duplicates were corrected in the oracle;
earlier comparisons remain retained. It checks source-owned definition identity/method-kind/name
lines, mapped parameters, lexical body calls and named type identity sets. Its
limitations and mismatches remain explicit; it is not full runtime, ABI, implicit
constructor/operator, expansion or alternate-configuration qualification. The 80
are admitted only after the final source binding and examined full gate. The
qualified cohort covers **1,665 definitions**, **1,976 mapped callable records**,
**1,398 lexical calls** and **125 named type targets**. Every native source prototype
is mapped or covered by its represented redeclaration-chain definition.

Other differences include written conditional alternatives absent from a single
native configuration, macro-expanded parameter/callee names, constructor/cast
representations, and unresolved model issues. Two already-clean thunk files also
expose a preexisting anonymous-namespace out-of-line method ownership mismatch.
That mismatch is unchanged by this patch and does not validate or invalidate the
specific changed parameter fields: those fields require their own native audit.

The complete three-payload delta audit now verifies five changed callable records
against native parameter declarations, retaining all other fields. Both real
backends pass seven-symbol/three-edge persistence, reuse and rebuild checks on
byte-identical original-source copies.

The full gate passes **2,077 tests**, with **three skips**, **87%** coverage and a
fresh **832-file** index: zero failures and zero coverage issues. Semgrep runs outside
the sandbox with zero findings. Source, included-header, control, canonical payload
and raw native-response hashes are checked before ledger admission. Final documentation
is checked again after recording the examined result.

`classification-v20.jsonl`, CSV and summary admit only those 80 paths. The remaining
original attribution is C **5,897** and C++ **18,658**. Other native rejections and
comparison mismatches remain open; deliberate/future fixture roles require exact
consumer evidence, not a failed host compilation. `complex-types-validation-receipt-r1.json`
binds the admitted source and validation evidence. No release is published.

## Retained evidence

Under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `complex-types-baseline-r1/`: immutable baseline package sources;
- `complex-types-full-surface-r1/`: include inventory/graph;
- `complex-types-full-surface-r2/`: full source/dependency-bound replay;
- `complex-native-controls-r1/`, `r2/`, `r3/`: native controls and retained corrections;
- `complex-native-originals-r1/`: all 174 raw compiler responses;
- `complex-native-grading-r1/`, `r2/`, `r3/`: comparisons and retained oracle corrections;
- `complex-clean-deltas-r2/`: complete changed-field/native-parameter audit;
- `complex-backend-probe-r1.json`: both real backend checks;
- `complex-existing-anonymous-owner-attribution-r1.json`: preexisting owner issue;
- `complex-focused-r4.log`: focused package tests;
- `complex-quality-r1.log`: passed preflight, Semgrep outside the sandbox;
- `classification-v20.jsonl` and `complex-types-validation-receipt-r1.json`: admission.

The overall diagnostic-resolution goal remains open.
