# LLVM namespace profile: 282 additional verified original files

The dedicated fix branch now records **1,726 verified fixes**, **453 separately
classified files**, and **23,583 open paths** out of **25,762 original diagnostic
paths**. The accounted share is **8.46%**, up from **7.36%**. Verified fixes alone
are **6.70%**. This phase adds **279 LLVM libc namespace-profile recoveries** and
**3 earlier specifier recoveries** whose complete artifacts remain unchanged
under the current analyzer. No new malformed/future classifications are added.

The authoritative ledger is `classification-v23.jsonl`, with CSV and grouped
summary under `.artifacts/analysis/parser-diagnostics-20261017-r1/`. The 453
separated records retain their language, source-declared language version,
repository, disposition and source evidence. Remaining historical ownership is
**5,897 C** and **17,686 C++** files. The original benchmark evidence and source
corpus remain unchanged. The full objective remains open.

## Fix and explicit profile

Commit `f1587fe` implements portable tree-sitter namespace expansion with original
source mapping, and explicit namespace-name bindings. It preserves original
positions and signatures and introduces no runtime compiler dependency. Logical
C++ analyzer version is **17**, distribution **2.0.13**, official bundle
**2.0.36**, and installer **2.0.4**. See the
[implementation report](analyzer-parser-diagnostics-namespace-macros-2026-10-19.md)
for recovery rules, rejected ambiguities and validation details.

The profile for the 279 libc files, relative to the unchanged LLVM source root,
is:

```toml
[plugins.analyzer-cpp]
include_search_paths = ["libc"]
namespace_macro_definitions = { LIBC_NAMESPACE = "__llvm_libc" }
```

This matches the source-supported namespace override and retained independent
native compilation flag `-DLIBC_NAMESPACE=__llvm_libc`. It is an explicit corrected
profile, rather than evidence that the original default benchmark is now clean.
The three specifier files use their separately captured include profiles.

## Complete original-file comparison

All **928** formerly held originals in the namespace-identity cohort were replayed
through the actual production analyzer. All parse cleanly and expose the expected
namespace, with **zero unresolved aliases and zero exceptions**. Full comparisons
against their retained original-source native ASTs qualify **279** and hold
**649**. The admitted namespace subset matches **304 definitions, 344 callables,
40 prototype parameter lists, 398 lexical calls, and 608 named-type identities**.
These are checked artifact fields, not runtime behavior or full test-harness
execution.

The reference R2 oracle qualifies none of these new artifacts because it cannot
map namespace identifiers supplied through macros. The R3 oracle extends this
specific coverage, requiring the matching explicit configuration and native flag,
command-line spelling origin, exact source invocation, and original namespace
range. It retains all previous callable, parameter, call, prototype and other
named-type checks. Three actual native controls and seven deliberately incorrect
artifact/metadata controls pass. Wrong namespaces, lines, parameters and extra
calls continue to fail.

The three separately admitted libc++ files previously passed the unchanged R2
comparison. Their entire current canonical artifacts match the qualified version
16 bytes exactly. This inherits their original proof without relaxing comparison
rules. The **685 LLVM headers admitted in v22** also retain complete artifact
equality under the final version 17 implementation.

Admission revalidates original source hashes, captured include dependency
identities, current implementation hashes, native tool/compiler identities,
retained native AST and stderr hashes, and complete production payload hashes.
Only previously open files with no comparison issues, unsupported mappings,
future-extension warnings or unresolved negative-harness roles enter v23.
The generator initially failed on evidence serialization/path assumptions; those
failures are retained. No classification files were written before all admission
checks passed.

Qualification covers source-owned callable identities, method kinds, name lines,
mapped parameters, lexical calls, named types, and represented prototype
redeclaration chains. Constants, complete signatures/visibility/attributes,
fully qualified owner resolution, ABI/runtime and implicit constructor/operator
lowering are outside that scope. Host native standard-library compilation does
not establish original test-consumer equivalence.

## Validation and next high-impact work

The full repository gate passes **2,161 tests with 3 skipped**, **87%** aggregate
coverage, and a fresh **845-file index** without failures or coverage issues. All
eight inexpensive preflight checks pass; Semgrep runs outside the sandbox.
An actual registry/configuration/SQLite check verifies initial indexing, unchanged
reuse, and invalidation of both source and header when namespace bindings change.
The failed earlier gate and the separate resume-test precondition fix `de3a365`
remain documented in the implementation report.

The next shared diagnostic group is call extraction/reference coverage. Among the
649 held files, **554** have lexical-call differences and **441** have native
callee mappings that the earlier reference does not support; these overlap.
A source-position counterfactual suggests named-cast correction alone could clear
**43** files after the namespace fix. This is a prioritization estimate, not an
admission.

Actual native controls additionally reproduce two product defects: unqualified
explicit template calls lose their named target, and namespace separators inside
template arguments split the enclosing call name incorrectly. A separate native
reference extension derives explicit template spelling from native callee source
ranges and referenced names. Its controls retain these genuine product failures
and reject deliberately wrong targets, arguments, bases, positions and call
cardinalities. Further corpus measurements remain separate from the v23 ledger;
no constructor or valid call is removed to manufacture agreement.

## Retained evidence

All paths below are relative to the durable analysis root above:

- `classification-v23.jsonl`, `classification-v23.csv`,
  `classification-summary-v23.json`: complete ledger and separated-file groups.
- `admit_namespace_profile_r1.py`, `namespace-profile-admission-r1.json`,
  `namespace-profile-admission-r3.log/.exit`: successful source-bound admission.
- `namespace-profile-production-r1/`: all 928 current production payloads.
- `namespace-profile-grading-r1/`: all native comparisons and R2 reference grades.
- `namespace-oracle-controls-r2/`, `namespace-oracle-review-r1.json`: namespace
  mapping controls and unchanged other comparison metrics.
- `specifier-original-native-r2/`: original native ASTs and execution records.
- `specifier-qualified-cpp17-r1/`, `include-search-qualified-cpp17-r2/`: exact
  complete-payload replay evidence for the three new and 685 prior qualified files.
- `namespace-macros-validation-receipt-r1.json`: gate result, evidence hashes and
  implementation binding at the feature boundary.
- `namespace-profile-index-smoke-r2/`: actual SQLite configuration/reuse check.
- `namespace-profile-next-causes-r1.json`,
  `named-cast-post-namespace-impact-r1.json`: complete held-group prioritization.
- `template-oracle-controls-r1/`, `template-oracle-controls-r2/`: retained native
  reproductions of unqualified and nested-qualified template target defects.
- `template-oracle-controls-r3/`: five actual native controls, including the
  retained nested-target defect, plus seven wrong-artifact rejection controls.
