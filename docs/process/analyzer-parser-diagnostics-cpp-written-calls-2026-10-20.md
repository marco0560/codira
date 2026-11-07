# C++ written-call qualification — 2026-10-20

Ledger v31 adds **39 verified original libc++ headers** under the unchanged C++19
implementation. It contains **2,459 verified fixes, 453 separated files and
22,850 open files** (C: 5,725; C++: 17,125): **11.30% accounted for**.
The full correction objective remains open. The language/version/repository
breakdown of deliberately malformed and future-syntax files is unchanged.

This is an independent reference-coverage correction, not a new production
analyzer change or release. Source commit `ebf61c5` remains byte-identical to its
passing gate. The [macro recovery report](analyzer-parser-diagnostics-cpp-macro-composition-2026-10-20.md)
records the preceding implementation and 189 admitted paths through v30.
Main remains at `91c4e07a3c25e72ee7c3346899f92e551037bf5e`; nothing was pushed
or merged.

## Shared reference gap

The public analyzer contract retains lexical forms such as `Type(value)`.
The preceding native reference considered `CallExpr` and `CXXMemberCallExpr`,
but missed written construction expressions and explicit callable-object
invocations, and could not name several dependent callees. Removing those
product records would have changed the existing lexical contract.

A separate Clang 22 QA tool now captures original-source `TypeLoc` ranges,
explicit `operator()` invocation syntax, dependent declaration/member names,
receiver ranges, opening parentheses and owning body ranges. It does not consult
product artifacts. Braced construction and implicit constructor/operator lowering
are excluded from the added lexical-call facts. Type-like forms retain their
source target spelling; primitive forms retain the analyzer's unresolved shape.
This checks lexical references, not whether those expressions execute at runtime.

R6 uses a receipt only when the native expression kind, owning body, source
span, target bytes, qualifier/receiver and punctuation agree. Missing, ambiguous,
unmatched or altered required receipts prevent qualification. All preceding
parameter, prototype, callable and type comparisons remain in place, together
with exact namespace ownership and qualified symbol ownership checks.

## Validation and admission

- 21 generated native controls: **18 qualify**, three remain explicitly held.
- **22 altered-artifact/evidence controls rejected**, including wrong targets,
  owners, positions, kinds, missing/extra sites, conflicting receipts, and
  simultaneous deletion of a construction call and its required proof.
- All **414 original modern headers** pass the new native capture, retaining
  **563 written-expression receipts**.
- Complete comparisons qualify **227/414**. All **188 earlier modern-header
  qualifications remain qualified**; the **39 additional matches** are admitted.
- Definition, callable, prototype-parameter and type counts, full ownership
  outcomes and non-call issues remain unchanged for all 414 files. Unordered
  missing/extra diagnostic entries are sorted for comparison; parameter order
  and multiplicity are preserved.

| Language | Native validation mode | Repository | Newly admitted files |
| --- | --- | --- | ---: |
| C++ | C++23 | LLVM / libc++ | 39 |

The native standard is the validation mode, not an inferred minimum source
version. Admission rechecks committed analyzer source, current source/header
fingerprints, exact product/AST/PP digests, new tool/source identities and
written-expression evidence. Only 39 pending rows change from v30 to v31.
The 453 separated files and all other rows remain unchanged.

The source-bound gate remains **2,276 passed, three skipped, 87% coverage**,
with a fresh 860-file index, no index failures and no coverage issues. Semgrep
ran outside the sandbox. A 12-file spread of preceding namespace/template/
specifier qualifications has byte-identical complete artifacts. This phase
reuses that exact source-bound gate; it does not claim a new benchmark run.
Data fields, complete native signatures/attributes, ABI/runtime behavior,
template argument identity beyond the existing lexical checks, and original
project-harness equivalence remain outside the qualification.

## Held cases and next bulk work

The controls expose two additional gaps without hiding them:

- The product retains the `template` disambiguator in a dependent target name.
  Exactly two paths among the 414 measured headers contain such targets.
- Native JSON omits a call in a `decltype` template argument. Capturing its
  TypeLoc operand is still required before qualification.

Macro-expanded construction names without an independently proven original
callee range also remain held. These are valid-source/product/reference gaps,
not new malformed or future-syntax classifications. The initial failing control
run is retained alongside the corrected, explicitly scoped control inventory.

The next bulk measurement is the full **343-header legacy C++03 wrapper cohort**:
211 were previously parser-clean, 114 partial and 18 timed out. The declared
legacy root must precede the modern libc++ root. All 16 spread-selected probes
are now parser-clean and native C++03 syntax-clean under that context. The full
checkpointed measurement includes all 343, not only the successful probes.
No C++03 qualification is claimed from syntax success alone.

## Durable evidence

All identities below are under the dedicated worktree's
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `native-written-call-tool-r4/`: tool source, binary and build receipt;
- `template_call_native_oracle_r6.py`: extended independent reference;
- `cpp-written-call-controls-r1/`, `cpp-written-call-controls-r2/`: retained
  initial findings and final scoped native controls;
- `cpp-written-call-negative-r1/`: 22 rejection controls;
- `cpp-written-call-native-r1/`: complete 414-file native capture;
- `cpp-written-call-grading-r1/`: complete unchanged-product comparisons;
- `cpp-written-call-invariants-r1.json`: non-call and prior-proof invariants;
- `cpp-written-call-admission-r1.json`: source-bound 39-file admission receipt;
- `classification-v31.jsonl`, `classification-v31.csv`,
  `classification-summary-v31.json`: complete ledger and grouped report;
- `cpp03-legacy-context-probe-r1/`, `cpp03-legacy-context-replay-r1/`: separate
  legacy-context probe and checkpointed full measurement.
