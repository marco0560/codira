# Native template-call coverage: 186 additional qualified original files

The current ledger is **v24: 1,912 verified fixes, 453 separately classified
files, and 23,397 open paths** out of **25,762 original diagnostic paths**.
The accounted share is **9.18%**, including **7.42% verified fixes** and **1.76%
separated files**. This phase qualifies **186 additional LLVM libc originals**;
combined with the preceding namespace admission, that is **468 newly verified
files** since v22. Remaining historical ownership is **5,897 C** and **17,500 C++**.
The full parser-diagnostic objective remains open.

Production code remains at commit `f1587fe`, logical C++ analyzer version **17**.
This admission extends independent native reference coverage for existing
production artifacts; it introduces no additional runtime behavior or compiler
dependency. The explicit source-supported namespace/include profile and overall
qualification scope are unchanged from the
[namespace admission](analyzer-parser-diagnostics-namespace-qualified-2026-10-19.md).
No original benchmark evidence or source file is modified, and no additional
malformed/future classification is made. The 453 separated records retain their
language, source-declared language version and repository groups in the complete
v24 summary and CSV.

## Evidence and scope

The preceding R3 native comparison treated explicit template callee spellings as
unsupported because its literal-name mapping recognized bare identifiers and
namespace-qualified identifiers only. The R4 reference maps a template callee
only when its native source range is owned by the original source, neither range
endpoint is a macro location, and the literal name before the template arguments
matches the native referenced name. The accepted native range supplies the exact
template-argument spelling. No product artifact contributes an expected target,
base, position or argument spelling.

The complete **928-original** population is compared again, preserving each R3
reference grade. R4 qualifies **465**, including all **279** previously qualified
namespace files and **186** previously open files. **463** remain held. The new
186 match **188 definitions/callables, 447 lexical calls, and 373 named-type
identities**; they contain no separately checked prototype parameter lists.
All previous namespace, callable, parameter, prototype, other named-type,
negative-harness and future-extension checks remain in force.

Five actual native cases and seven deliberately wrong-artifact rejection controls
exercise the reference extension. Additional controls retain both known product
defects: unqualified explicit-template calls become unresolved, and a namespace
separator inside a template argument incorrectly splits the target. Those
artifacts continue to fail qualification. Changed template arguments, namespace
base, target, line, column, missing calls and extra calls are all rejected.

Admission rechecks source and include identities, final implementation hashes,
compiler/tool identities, native AST/stderr hashes, complete production payload
hashes and R3 reference-record hashes before writing v24. Previously admitted
files remain accounted once. The production full gate remains the examined
**2,161 passed, 3 skipped** result for these unchanged source bytes; subsequent
tracked changes are reports only. The required temporary completed-gate session
and files have been cleaned after examination and reporting; its durable receipt
and the earlier failed gate remain retained.

This qualification checks the artifact fields described in the namespace report.
It does not establish full signature/visibility/attribute correctness, fully
qualified owner resolution, ABI/runtime behavior, implicit constructor/operator
lowering, original test-consumer equivalence, or a clean default full benchmark.

## Next correction batch

The next concrete product fixes are explicit-template call target extraction and
named-cast classification. A source-coordinate counterfactual on the 463 held
files identifies **348 affected files** and **147 potentially unblocked files**
from their combination. The estimate retains all other mismatches and unsupported
mappings. It is a prioritization signal: actual source changes, regression
controls, cache/version invalidation and original-file replay are still required
before admitting any of those files. Valid constructor calls must be preserved.

## Durable evidence

Paths below are relative to
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `classification-v24.jsonl`, `classification-v24.csv`,
  `classification-summary-v24.json`: complete current ledger and separated groups.
- `admit_template_profile_r1.py`, `template-profile-admission-r1.json`,
  `template-profile-admission-r1.log/.exit`: source-bound 186-file admission.
- `template_call_native_oracle_r4.py`: native explicit-template reference mapping.
- `namespace-profile-template-grading-r1/`: all 928 results, R3 reference records,
  immutable input hashes and complete summary.
- `template-oracle-controls-r3/`: controls bound into the grading manifest.
- `template-oracle-controls-r4/`: additional distinct native cases retaining both
  reproduced product defects and the seven wrong-artifact rejection cases.
- `namespace-profile-production-r1/`, `specifier-original-native-r2/`: unchanged
  complete production payloads and independent original-source native evidence.
- `namespace-macros-validation-receipt-r1.json`,
  `namespace-macros-gate-cleanup-r1.json`: source-bound gate and authorized cleanup.
- `template-and-cast-next-fix-impact-r1.json`: next-batch counterfactual, explicitly
  excluded from the verified ledger.
