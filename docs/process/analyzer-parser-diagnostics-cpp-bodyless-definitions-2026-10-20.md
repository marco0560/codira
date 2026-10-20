# C++ defaulted/deleted definitions — 2026-10-20

## Shared issue

The starting ledger remains classification v36: **2,669 verified fixes, 453
separated, 22,640 open**, or 12.12% accounted. This batch is not admitted yet.

The analyzer distinguished definitions only by the presence of a compound body.
Valid `= default` and `= delete` definitions therefore had no end position and
could lose preference to earlier declarations. The original LLVM header
`llvm/include/llvm/IR/DiagnosticPrinter.h` was held solely because its defaulted
destructor was represented as a declaration. Clang explicitly records defaulted
and deleted definitions even when it omits an implicit compound body.

A source token footprint finds 2,603 pending C++ paths containing these clauses:
LLVM 2,549, Catch2 37, fmt 15, PostgreSQL one and CPython one. These are candidates,
not a recovery estimate; other parser or metadata gaps can still hold a file.

The correction assigns definition ranges to provider-proven explicit clauses
and prefers actual out-of-class default definitions over prototypes. Ordinary
prototypes and pure virtual declarations remain declarations. No executable body
or implicit runtime calls are fabricated. Signatures, ownership, parameters and
stable identities remain source-bound.

A focused test also exposed a grammar gap for valid free deleted functions,
including deleted function templates. The provider interpreted `= delete` as
an incomplete initializer. Recovery now masks only a single declarator with a
complete callable shape and exact deleted-definition suffix. It preserves byte
width and line breaks, guards captured keyword overrides, rejects pointer
variables/multiple declarators, and retains unrelated syntax errors. The builder
uses the original source to retain the definition clause and end position.

Logical analyzer version 22, distribution 2.0.18 and official bundle 2.0.43 are
aligned with pins, lock and package contracts. Changes remain in the dedicated
worktree; main is unchanged.

## Focused verification

Thirteen new tests pass: defaulted constructor/copy/move/assignment/destructor,
deleted member/free functions, prototypes, pure virtual declarations,
out-of-class definition preference, comments, UTF-8/CRLF ranges, namespace and
template recovery, lexical-call preservation, invalid pointer/multiple forms,
keyword overrides and unrelated malformed syntax. The C++/bundle/root contract
run passed **371 tests**; typing passed for all 12 source modules. Repository
preflight passed all eight checks with Semgrep outside the sandbox.

Fresh native controls pass **54 positive cases**, retain three known held cases,
and reject all **40 negative cases**. The latter include omitted/wrong end
positions, invented calls, changed parameters and declarations falsely marked as
definitions.

The native reference distinguishes explicit default/delete flags, verifies the
written clause and semicolon at native-owned source positions, and checks the
actual definition end line. Clang sometimes ends its native range at the
parameter list for free/out-of-class definitions; the first reference attempt
held those cases, and its evidence is retained. The corrected R11 reference
proves only the immediately adjacent written clause. Native-generated implicit
bodies contribute no invented lexical calls. Existing callable, parameter,
prototype, type and qualified ownership checks remain in place.

The original `DiagnosticPrinter.h` now passes the complete independent native
comparison with no issues or limitations. Its only output change is the restored
destructor end position at line 34; all other metadata is unchanged. This is a
single original proof, not a ledger admission.

## Running validation and regression work

The full repository gate passed: **2,343 tests passed, three skipped, 87%
coverage**, with a fresh 871-file index, zero index failures and zero coverage
issues. Semgrep ran outside the sandbox. The examined result is bound to source
digests by `cpp22-bodyless-validation-receipt-r1.json`.

The replay completed all 861 requests and all 438 prior qualifications: 418
payloads are byte-identical and 20 change exactly 61 method end positions from
missing to their correct source lines. Every other output field is unchanged.
Complete native comparisons preserve all 438 files in their exact current
profile and measured language mode. This includes the historical `stack.h`
C++03 context using the modern include root and `__optional/hash.h`'s explicit
C++17 compatibility context. Cached C++23 evidence for the latter remains an
expected contrast, not a waived failure.

Three pending LLVM headers fully qualify: `llvm/ABI/TargetInfo.h`,
`llvm/Analysis/SimplifyQuery.h` and `llvm/IR/DiagnosticPrinter.h`. These are
measured in the source-generated C++17 LLVM context; their original minimum
language version is not inferred. Admission follows the source commit. The 20
existing rows need updated source/native evidence, not another fixed-file count.

Six newly complete outputs received fresh native captures: four were previously
partial trees and two previously hit execution limits. All six remain held for
metadata mismatches. Seventeen execution exceptions in the full replay remain
open. These results do not establish malformed or future syntax.

This is a small file-count gain despite the broad token footprint. The next
priority should be a larger shared failure family; do not equate all 2,603
candidate files with successful recoveries or continue isolated metadata cases
merely because a focused fix is straightforward.

## Durable evidence

All records are under the dedicated worktree's
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `cpp-defaulted-callable-native-r1/`,
  `cpp-defaulted-callable-prioritization-r1.json`;
- `cpp22-bodyless-focused-r1.log/.exit`,
  `cpp22-bodyless-preflight-r1.log/.exit`;
- `cpp22-bodyless-native-controls-r1/` (initial held reference cases), `r2/`
  (all expected outcomes), and `cpp22-bodyless-negative-controls-r1/`;
- `template_call_native_oracle_r10.py` (retained first attempt), `r11.py`
  (native flags plus written-clause and exact end-line proof);
- `cpp22-bodyless-original-native-r1/`,
  `cpp22-bodyless-original-grading-r1/`;
- `cpp22-bodyless-production-r1/`, source-bound inputs and checkpoints;
- `cpp22-bodyless-{legacy,modern,llvm,prior-modern,optional}-native-r1/`
  and corresponding strict grading outputs when terminal;
- `cpp22-bodyless-gate-launch-r1.json` and retained gate log/status.

The full correction goal remains open. No pending file is newly separated as
malformed or future syntax on the basis of these partial parses or context gaps.

Additional final evidence: `cpp22-bodyless-qualification-review-r1.json` proves
all 438 prior profiles/modes still qualify; `cpp22-bodyless-prior-change-audit-r1.json`
proves the 61 exact end-line additions and otherwise identical output;
`cpp22-prior-modern-historical-input-audit-r1.json` verifies all 227 cached PP
payloads against their original admission hashes. The initially incomplete
profile audit and fresh `cpp22-bodyless-stack-context-r1/` plus grading retain
how the historical include-root variant was resolved.
