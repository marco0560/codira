# C nested tags and C++ member aliases

The compiler-pragma phase left four original diagnostic paths unqualified even
though their parser trees were clean. Native Clang exposed missing type artifacts.
This follow-up fixes the extraction layer; it does not change parser grammar.
Main, the pinned corpus and the original benchmark evidence remain unchanged.

| Language | Native probe mode | Repository / original path | Missing artifact |
| --- | --- | --- | --- |
| C | Clang 22.1.8, C11, recorded `-verify -Wno-pragma-pack` syntax mode | LLVM `clang/test/Parser/pragma-pack.c` | Nested record `T`, physical name line 39. |
| C++ | Clang 22.1.8, C++17, `-fopenacc`, syntax AST | LLVM `clang/test/SemaOpenACC/combined-construct-ast.cpp` | Member alias `S::type`, physical name line 238. |
| C++ | Same explicit probe mode | LLVM `clang/test/SemaOpenACC/compute-construct-ast.cpp` | Member alias `S::type`, physical name line 115. |
| C++ | Same explicit probe mode | LLVM `clang/test/SemaOpenACC/loop-ast.cpp` | Member alias `S::type`, physical name line 227. |

Probe standards qualify those modes, not inferred minimum language versions.
OpenACC code generation, lowering and PCH consumers remain outside the proof.

## Correction and verification scope

C declaration extraction now follows direct type bindings into defined record/enum
specifiers and record member containers. Named tags inside anonymous containers
are retained, including written conditional members. It also retains a named
record/enum definition attached to a file-scope variable declaration. References
to existing member types are not new definitions. Function bodies, parameter types,
initializers and field values remain opaque. The existing typedef tag handling is
preserved. Enrichment fills absent identities; existing declaration representatives
are retained even when a new nested definition could replace a forward declaration.
Names, physical lines, signatures, enum members and local comment
attachment use the existing source-backed artifact builders; C tags retain their
existing file-scoped identities.

C++ record traversal dispatches ordinary and templated member `using` aliases to
the existing alias builder with their class and namespace owner. Alias-only structs
and unions do not acquire fabricated callable containers. Access sections retain
all written aliases, consistent with the existing declaration contract; inherited
using declarations and local function aliases are not reclassified as member aliases.

Distributions C **2.0.4** / logical **14**, C++ **2.0.8** / logical **12**, and
bundle **2.0.31** invalidate the changed artifacts and align pins/lock/assertions.
No release is published.

The first complete gate passed 1,992 tests, but its semantic replay exposed a
regression: namespace-conflict inference treated qualified member alias prefixes
as conflicting owners and dropped some external method associations. Member aliases
are now excluded from those alternatives using explicit record ownership; legacy
nonmember alias handling is unchanged. A focused header/source regression test also
covers a source outside the lexical replay filter. The first replay, failed delta
audit and passed-but-nonqualifying gate remain retained. A fresh gate is required.

The second gate passed 1,994 tests and the complete canonical delta audit, but
a further conflict-set comparison found one remaining namespace/record collision
in `Modules/odr_hash.cpp`. A namespace alias whose parent is also a written record
now retains its conservative conflict evidence. The original fixture and a new
conditional header/source regression test cover this case. The second gate and
audit are retained without admission; final validation uses a fresh third identity.

The focused package suites pass **160 tests**. Eight native syntax checks of the
actual four new regression sources pass, covering both values of their conditional
configuration. Tests cover named/anonymous and conditional members, preserved tag
identities, physical lines, comments, enum members, nested owners, access sections,
template aliases, inherited using declarations and excluded local/parameter types.

The native original-file comparison is rerun over the preceding 17-path cohort:
all **15 native-accepted files** now match their complete source-owned named callable
definition and record/typedef/enum/namespace identity sets with physical name lines
(**53 named targets**). The two remaining paths have their separately proven
preprocessing/diagnostic roles; they are not native C program qualifications.
The four newly qualified files account for **20 named targets**. The profile
excludes callable prototypes, variables, fields, unnamed closures, calls, macro
expansion, layout and pragma effects. No source is executed.

## Retained evidence and admission

Evidence root: `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `nested-type-followup-attribution-r1.json`: the original four omissions;
- `nested-types-baseline-r1/`: complete package sources from committed phase `c120186`;
- `nested-types-native-originals-r3/`: complete native comparisons and exact commands;
- `nested-types-native-controls-r3/`: actual regression-source native syntax checks;
- `nested-types-focused-r5.log`: focused result;
- `nested-types-full-surface-r3/`: source-bound replay, checkpoint/resume and full
  before/after canonical artifacts, including previously clean and excluded files.

The full inventory of 77,192 sources is reverified. A conservative lexical filter
selects **26,517 potentially affected analyses** across each matching discovery
language: C sources with any record/enum keyword and C++ sources with `using` and
a record keyword. Sources outside that surface cannot enter the new extraction
paths. The final replay completes all 26,517 analyses with **zero exceptions**, **zero
parser-status regressions**, **zero newly clean trees** and **22,815 unchanged
payloads**. The **3,702 changed analyses** concern **3,620 distinct paths**.
`nested-types-changed-deltas-r3/` verifies that every existing declaration,
documentation record and other payload field is identical. Only **886 C type
declarations**, **13,063 C++ aliases** and **694 documentation records owned by
new types** are added. Each added declaration has complete signature, literal-name
and start-line source evidence. This is source-local delta qualification, not
complete native semantic qualification of all changed files.

`nested-types-owner-alternatives-r2.json` checks all **3,240 changed C++ results**:
the conflict sets used for captured-header owner inference match their baseline
sets exactly. This complements canonical owner/call preservation and the focused
source-outside-filter regression control. The final source/test bindings and all
corpus and captured-dependency hashes are reverified before admission.

The final complete gate passes **1,995 tests**, with **three skips**, **87%**
coverage and a fresh **829-file** index: zero failed files and zero coverage issues.
Semgrep runs outside the sandbox, with 21 rules on 177 files and zero findings.

After the examined gate, `classification-v19.jsonl`, CSV and summary admit the four
newly qualified original paths. Totals are **679 verified recoveries**, **448
separately classified inputs** and **24,635 open original diagnostic paths**
(C: **5,960**; C++: **18,675**, by original analyzer attribution). The source-bound
receipt is `nested-types-validation-receipt-r1.json`. The overall goal remains open.
