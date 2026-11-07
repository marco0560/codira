# CPython clinic builtin-profile qualification

All **33 clinic headers** in the selected shared-cause cohort now qualify under
the unchanged C17 analyzer and unchanged R9 reference. Ledger v28 contains
**2,231 verified fixes, 453 separated files and 23,078 open files**: **10.42%
accounted for**. Remaining languages are C (5,725) and C++ (17,353). The full
parser-correction objective remains open.

This phase independently qualifies existing parser recoveries; it introduces no
production analyzer change, reference-rule change, package release, main merge or
push. The source implementation remains commit `a3982b0`. See the [preceding
parameter/source-call report](analyzer-parser-diagnostics-c-parameters-2026-10-20.md)
for its implementation, validation and earlier qualifications. The deliberately
malformed/future-syntax classifications and their language/version/repository
breakdown remain unchanged.

## Shared cause and bounded intervention

The 33 files previously had only lexical-call mismatches, with no other R9 issues
or limitations. Their original consumers explicitly declare this build choice:

```c
#ifndef Py_BUILD_CORE_BUILTIN
#  define Py_BUILD_CORE_MODULE 1
#endif
```

Generated clinic code also contains branches enabled by `Py_BUILD_CORE` without
`Py_BUILD_CORE_MODULE`. The analyzer retains written conditional alternatives;
the original native module profile omitted source initialization sites such as
`PyVarObject_HEAD_INIT` and `_Py_ID`. Deleting those valid analyzer calls would
have hidden a reference-profile coverage gap.

Three actual original-consumer probes first compiled and passed the unchanged
R9 comparison in the source-declared builtin mode. The complete 33-file cohort
then used its exact retained compiler, original consumer and compiler arguments,
adding only `-DPy_BUILD_CORE_BUILTIN=1` to both native AST and preprocessor capture.
No original sources were edited. No per-file flag search or reference union was
used.

All **33 native compilations and 33 preprocessor captures succeed**, with no
exceptions. All **33 complete comparisons qualify**, without issues or
limitations. Function, callable, prototype, call-count and named-type comparison
counts remain identical to the original-profile comparisons; non-call issue lists
are unchanged. One original consumer, `pyexpat.c`, emits external API deprecation
warnings. These are retained; no newly captured stderr contains the guarded
future-C-syntax extension diagnostic.

## Scope and admission

The new qualifications cover **534 definitions, 1,068 callables, 534 prototype
parameter lists and 3,370 lexical call sites**. There are no named types in this
subset. The normalized-artifact scope excludes data fields, full native
signatures, ABI, runtime behavior and original project-harness equivalence.

Admission rechecks current source and consumer hashes, generated-header and
compiler/tool identities, exact base commands plus the builtin flag, AST and
preprocessor digests, unchanged C17 artifact digests, current dependency
fingerprints and all R9 outcomes. Only the 33 pending rows change from v27 to v28;
all other rows, including the 453 separated files, remain unchanged.

R9 is byte-identical to the preceding phase's reference. Its 15 source controls
and 61 wrong-artifact rejection controls remain binding evidence. The production
source is also unchanged from the passing full gate: **2,235 tests passed, three
skipped, 87% coverage**, with a fresh 856-file index and no index failures or
coverage issues. Semgrep ran outside the sandbox. This proof/report-only phase
reuses that exact source-bound gate; it does not claim a fresh full benchmark run.

## Durable evidence

Evidence remains under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `c17-next-core-profile-candidates-r1.json`: complete 33-file source-guard cohort;
- `c-builtin-profile-probe-r1/` and `c-builtin-profile-grading-probe-r1/`: initial three actual native probes and unchanged comparisons;
- `c-builtin-profile-native-r1/`: complete actual builtin-mode AST/PP capture, commands and digests;
- `c-builtin-profile-grading-r1/`: complete unchanged R9 comparison;
- `c-builtin-profile-invariants-r1.json`: comparison-count invariants and retained compiler diagnostics;
- `c-builtin-profile-admission-r1.json`: source-bound per-file admission receipt;
- `classification-v28.jsonl`, `classification-v28.csv`, and `classification-summary-v28.json`: complete dispositions and language/version/repository groups.

The original campaigns, preceding profiles and failed measurements remain
untouched. Next work should prioritize larger shared causes, with isolated cases
last; the remaining 23,078 files are not waived.
