# Legacy libc++ C++03 context qualification — 2026-10-20

Ledger v32 adds **88 verified original headers**, producing **2,547 verified
fixes, 453 separated files and 22,762 open files** (C: 5,725; C++: 17,037):
**11.65% accounted for**. The full parser-correction objective remains open.
All language/version/repository groups for the 453 separated files remain
unchanged; no new malformed/future-syntax classification is made here.

The implementation remains `ebf61c5`, logical C++19 / distribution 2.0.15.
This phase supplies an explicit legacy include context and independent native
qualification; it changes no production code or package version. Main remains
at `91c4e07a3c25e72ee7c3346899f92e551037bf5e`, with no push or merge.

## Context and complete cohort

The exact legacy wrapper cohort contains **343 originals**: the preceding
modern-root diagnostic replay had 211 parser-clean, 114 partial and 18 timed-out
paths. This phase includes every one of them, rather than selecting only clean
paths. All 16 spread-selected context probes first passed parser and native
syntax checks.

The analysis profile supplies these roots in order:

1. `libcxx/include/__cxx03`
2. `libcxx/include`
3. `libcxx/test/support`

It also explicitly binds `_LIBCPP_ABI_NAMESPACE=__1`. Native capture uses
Clang 22 C++03 mode, the retained generated configuration and the legacy root
before the modern root. This is a declared standalone-header analysis context,
not a universal default or an original project-harness equivalence claim.
There is no per-file language/flag search or union of native profiles.

## Results and admission

| Check | Result |
| --- | --- |
| Complete checkpointed cohort | 343/343 processed, terminal exit zero |
| Public C++19 analyzer | 213 parser-clean, 126 partial, four timed out |
| Native syntax | 341 accepted, two unresolved context failures |
| Complete parser/AST/PP/written-call captures | 212 |
| Complete independent artifact comparison | 89 qualified |
| Previously qualified overlap | One path |
| Newly admitted pending rows | **88** |

| Language | Native validation mode | Repository | Newly admitted files |
| --- | --- | --- | ---: |
| C++ | C++03 | LLVM / libc++ frozen headers | 88 |

The native mode is recorded explicitly; it does not establish a stricter source
minimum, ABI/runtime behavior or a complete libc++ build. Complete comparisons
retain the existing definition/method identity, parameter, lexical-call, named
type, prototype, namespace-origin and qualified-ownership checks. R6 written-call
receipts come from the same native command and original target/translation unit.
The 18 positive, three held and 22 rejection controls remain binding evidence.

Admission rechecks exact source/dependency fingerprints, committed analyzer
bytes, product/AST/PP/written-call digests, compiler-tool identities, generated
configuration and native namespace spelling origins. The written-tool binary
and source, commands and evidence digests receive a separate 88-path invariant
audit. Only 88 pending rows change from v31 to v32; all other rows are unchanged.

The source-bound gate remains **2,276 passed, three skipped, 87% coverage**,
with a fresh 860-file index, zero index failures and zero coverage issues.
Semgrep ran outside the sandbox. No new source gate or complete benchmark run is
claimed for this unchanged-code qualification phase.

## Remaining issues

Native syntax still fails for `__thread/support/c11.h` (missing
`__cxx03/errno.h`) and `math.h` (missing `FP_*` definitions). These need their
proper generated/include/consumer context; they are not declared malformed or
future syntax on that evidence.

The partial-tree investigation retains 16 spread-selected native-valid headers
and final namespace-projection traces. Two source-backed examples are concrete:

- `__algorithm/fill.h`: the final projected error is a call argument containing
  `typename iterator_traits<...>::iterator_category()`.
- `__chrono/system_clock.h`: final projected errors include `_NOEXCEPT` uses;
  the captured object replacement is `throw()`, which the prefix-only
  annotation probe does not accept.

These are valid C++03 grammar/adaptation gaps, not unsupported future syntax.
Token footprints across the partial cohort are retained only to prioritize
investigation, not as a promised fix count. They are candidates for the next
shared parser change; neither is silently waived. Remaining artifact comparison
gaps include conditional type/definition identity and lexical-call coverage.

Across the complete macro-recovery phase, v28 to v32 admits **316 originals**:
227 validated in C++23 mode and 89 in C++03 mode. A preceding report subtotal
through v30 was corrected from 190 to 189; ledger totals and admission receipts
were already correct.

## Durable evidence

Evidence remains under the dedicated worktree's
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `cpp03-legacy-context-probe-r1/`: 16 actual context probes;
- `cpp03-legacy-context-replay-r1/`: immutable controls, all 343 outputs,
  checkpoint/resume records, AST/PP/written-call evidence and source digests;
- `cpp03-legacy-context-grading-r1/`: complete independent comparisons;
- `cpp03-legacy-context-admission-r1.json`: source-bound 88-file admission;
- `cpp03-legacy-native-tool-invariants-r1.json`: written-tool/command audit;
- `cpp03-partial-errors-r1/`, `cpp03-annotation-blocker-trace-r1/`,
  `cpp03-scope-errors-r1/`: retained parser and final-projection evidence;
- `cpp03-partial-token-footprint-r1.json`: explicitly unqualified prioritization;
- `classification-v32.jsonl`, `classification-v32.csv`,
  `classification-summary-v32.json`: complete dispositions and grouped report.
