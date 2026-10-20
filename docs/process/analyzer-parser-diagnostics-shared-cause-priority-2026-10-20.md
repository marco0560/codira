# Analyzer remediation: native admissions and shared-cause priority

The immutable original population is 25,762 files. Classification v55 has
**4,136 verified fixes, 680 separated inputs and 20,946 open files**: 16.05%
fixed and 18.69% accounted for. The original v38 baseline remains 2,786 fixes,
453 separated inputs and 22,523 open files. The full objective is incomplete
and remains active. No new exclusions were made in this phase.

## Committed production correction

Commit `5baf2ac4cc27761cd705c205e94d6de3d0c60487` excludes fundamental-type
functional conversions from C++ call records. Previously `int(argument())`
created a phantom unresolved call, and several primitive spellings created
phantom named calls. Operand calls, named class construction and indirect calls
remain. Native Clang controls cover twelve fundamental spellings. The C++
logical version is 26, its distribution is 2.0.27, and the official bundle is
2.0.53. Schema 24 and generated-provenance format 1 remain applicable.

The focused checks passed (24 tests), all nine workflow preflight checks passed,
and the full outside-sandbox repository gate passed: 2,716 tests, 3 skipped,
88% coverage, 908 indexed files, zero index failures and zero coverage issues.
All 2,646 production cases for the 1,323 earlier macro admissions are byte-for-byte
unchanged. The commit, staged tree and frozen runtime are bound to these results.

## Actual-file qualification

Current-source metadata was captured for 203 open originals in their retained
native preprocessing profiles, covering 406 packaging-mode cases. A controlled
native oracle now proves explicit parenthesized class construction and explicit
destruction while retaining argument calls and conservative unsupported holds.
It does not infer implicit variable initialization as a source call.

Twenty-seven originals passed in both packaging modes: nine under the primary
profile, five under the syscall profile, six under official-header profiles and
seven under the remaining official-header profile. Real CLI indexing used DuckDB
and SQLite; every persisted function, overload, call and generated-provenance
record was compared with frozen production metadata. Twenty-four real CLI
retrieval commands also passed across the four groups.

Admission reran native comparisons from retained raw ASTs and checked source,
header, profile, compiler, control, gate and persistence identities. Totals across
54 cases are 54 definitions, 27 prototypes, 27 aliases, 134 lexical calls,
16 explicit constructions, two explicit destructions and 18 macro hints.
These 27 admissions combine improved independent qualification with the
production correction; they are not all attributed to the primitive-conversion
patch. Helper controls and clean syntax alone contributed zero admissions.

The first admission attempt failed when Python tuple spans were compared
directly with JSON arrays. A separate replay proved complete JSON value equality
for all 54 stored projections. The corrected attempt compares the full normalized
values, without dropping fields. Failed attempts and their raw evidence remain.
An independent full-ledger audit proves exactly the 27 intended rows changed,
all original identities survived, all 680 exclusions are unchanged, and the CSV
matches the JSONL export. The existing v51 separated-input export remains valid.

## Larger shared cause selected from the full remaining population

A fresh join against v54 checked source hashes for all 20,973 then-open files
and reused historical measurements without treating them as current qualification.
LLVM accounts for 18,745 of those files. The largest three-level directory groups
were 2,417 libc++ standard-library tests, 1,093 LLVM headers and 986 Clang C CodeGen
tests. Directory and token counts are candidate rankings, not proven causes.

The libc++ selection contains 603 open sources using `ASSERT_SAME_TYPE`, directly
including `test_macros.h`, and without the screened diagnostic/C++20 exclusion
markers. Its source-backed variadic definition produces `static_assert` with type
arguments. Three unchanged originals fail production parsing but pass native
Clang C++20 syntax checks using repository test support and the host standard
library. Expanding only that macro makes all three parser trees clean; all nine
expansions match native preprocessing tokens. This is not a full libc++ harness
or runtime claim.

An isolated raw-parser counterfactual over all 603 candidates changes zero clean
inputs to 383 clean inputs. Two expansion cases retain explicit unsupported
holds; other incomplete inputs remain incomplete. This measures potential syntax
impact only. **None of the 383 is a newly verified file fix.**

Next implement generic source-backed static-assert statement macro handling,
using the accepted ADR-034 expansion/mapping foundation. Preserve source macro
hints, argument call coordinates, original artifact identities, include ordering
and ambiguity holds. Do not hard-code this macro name or erase its arguments.
Then qualify actual originals in batches with native metadata and production
indexing. This larger family takes priority over the remaining wrapper tail.

## Durable evidence

All identities below are under
`.artifacts/analysis/parser-diagnostics-20261017-r1/` in the dedicated worktree.
They retain raw and failed attempts; none is moved or overwritten.

- `classification-v55.jsonl`, `classification-v55.csv`,
  `classification-summary-v55.json` and `cpp26-r5-27-admission-v55-r1.json`.
- `admit_cpp26_r5_27_r2.py`, `audit_cpp26_v55_r1.py` and
  `cpp26-r5-27-admission-audit-v55-r2.json`.
- `cpp-primitive-cast-gate-result-r1.json`,
  `cpp-primitive-cast-commit-binding-r1.json` and
  `cpp-primitive-cast-prior1323-regression-r1/`.
- `cpp-primitive-functional-cast-native-r1/`,
  `cpp-native-explicit-construction-controls-r1/` (failed parity retained),
  `cpp-native-explicit-construction-controls-r2/` and `cpp_native_call_sites_r5.py`.
- `cpp26-open-native-ready-r1/`, `cpp26-open-native-r5-grading-r1/`,
  `cpp26-r5-projection-replay-audit-r1.json` and
  `cpp26-r5-qualified27-index-batch-r1/` (links all four CLI/storage identities).
- `current-open-impact-ranking-r1/`,
  `libcxx-assert-same-type-root-probe-r1/` (failed harness invocation retained),
  `libcxx-assert-same-type-root-probe-r2/`, `libcxx-assert-only-census-r1/`
  and `libcxx-assert-statement-integration-plan-r1.md`.

Stay on the dedicated branch. No merge, push, main changes, cleanup or sub-agents
are authorized. Full validation and Semgrep outside the sandbox remain authorized.
