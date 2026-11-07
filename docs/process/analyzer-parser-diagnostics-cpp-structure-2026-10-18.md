# C++ parser follow-up: linkage, records and callable identity

This phase follows the
[source-local annotation correction](analyzer-parser-diagnostics-cpp-local-annotations-2026-10-17.md).
It addresses extraction defects exposed by independent comparison of the 88
recovered C++ files. Main, the original campaign and pinned corpus remain
unchanged. Header-dependent annotation recovery and the wider parser goal
remain unfinished.

## Reproduced problems and correction

| Problem | Observed consequence | Correction |
| --- | --- | --- |
| Linkage specifications were not visited | MLIR runtime and ORC witnesses had clean trees but zero extracted functions | Visit direct declarations and braced linkage blocks, preserving namespace, comments and original signatures |
| Only class-specifier bodies supplied method owners | Struct/union methods and records declared with variables were omitted | Visit explicit record specifiers, preserve their declaration kinds and create method containers when methods exist |
| Nested type and template wrappers were skipped | Nested records and explicit member specializations disappeared | Preserve record scope and traverse successive template wrappers |
| Callable slots used parameter names | Same-named parameters collapsed const/non-const operators and typed overloads | Bind by source parameter syntax, cv/ref/constraint qualifiers and lexical branch identity |
| Function types were treated as callable owners | Function-pointer variables could become functions | Follow declared-name binding; preserve real functions returning pointers/references or callbacks |
| Whitespace removal changed type/operator names | Allocation operators lost their required space; comments entered specialization names | Normalize syntax tokens while preserving lexical word boundaries and literal contents |

Record declarations remain `struct` or `union` artifacts. Their class-like
method containers represent ownership, following the existing normalized model;
this does not change a source struct into a C++ class declaration. Data-only
records retain their existing declaration representation. Out-of-class members
use the explicitly written owner, including template arguments. Function-local
records and literal text are not flattened into exported declarations.

Parameter names, nested callback parameter names and default values do not
distinguish redeclarations. Empty parameter lists and explicit `void` markers
remain equivalent. Ellipsis, const/ref qualifiers and source type tokens remain
distinct. Type aliases and compiler-dependent equivalence are not inferred.
Definitions in different preprocessor branches survive as separate source
variants; the analyzer does not select a build configuration. Original source
bytes continue to supply signatures and source coordinates.

## Independent verification scope

The retained native comparison replays all 88 annotation-recovered paths against
Clang. With the recorded host flags, 56 files are accepted and all 385 explicit
callable targets match by normalized source name and physical name line. Native
template instantiations are deduplicated by their written source occurrence;
function-local classes and implicit declarations are excluded. Explicit
destructors are included. These refinements align the oracle with source
declarations rather than compiler-generated or function-local artifacts.

Two accepted files contain additional static-source targets in inactive
branches. Retained Clang token dumps independently establish that all 11 extra
target lines are inactive under the selected host flags. They remain available
to the analyzer as source variants. The comparator rejects unexplained active
extras or missing targets; it does not silently discard them.

The other 32 files are rejected with these host flags. They still need their
target/build/harness context or expected-diagnostic attribution. A host-mode
rejection does not classify a file as malformed, and this is not execution of
LLVM's lit harness. Production call edges beyond the earlier explicitly stated
oracle checks, type resolution, backend persistence and program execution are
not verified by this comparison.

The full frozen C++ parser cohort is separately replayed with original source
hash checks. That replay covers 18,780 investigation paths, 242 separated
malformed fixtures and four future C++26 fixtures. The final counts, product
digests and examined repository-gate outcome are recorded in
`cpp-structure-validation-receipt-r1.json`. Direct analyzer replay completed
all 19,026 C++ paths without exceptions; 88 investigation paths parse cleanly.
The 242 malformed and four future-syntax fixtures remain partial.

Focused validation passes 107 tests. The full repository gate exits zero with
1,773 tests passed, three skipped, 87% coverage, 796 files freshly indexed,
zero failed files and zero coverage issues. Semgrep runs outside the sandbox
and reports zero findings. Clang also accepts all 13 positive literal
regression fixtures with the retained helper declarations.

Classification v8 admits 54 additional independently checked paths, retaining
the two already checked annotation witnesses. The overall ledger now contains
442 verified corrected paths and 24,877 paths requiring investigation. These
are file counts, not distinct defect counts; the 32 host-mode rejections remain
in the investigation population.

## Regression coverage and retained evidence

Package tests reproduce both linkage forms, nested and conditional declarations,
struct/union methods and access, declaration wrappers, nested records, template
specializations, pointer-variable exclusions, callback-returning functions,
overload merging, const/ref variants, branch preservation, literal contents,
word boundaries, callback parameters and void/empty parameter equivalence.
Malformed linkage syntax remains partial. Header-routing and existing native
scanner contracts are included in focused validation.

The C++ distribution advances to 2.0.3, logical analyzer version 8. Root extras,
their contract assertion, lockfile and official bundle 2.0.19 are aligned. No
header or compiler is added as a product analysis dependency.

Durable evidence lives under the worktree-relative
`.artifacts/analysis/parser-diagnostics-20261017-r1/` directory:

- `cpp-linkage-block-attribution-r1.json` retains the original clean-tree,
  zero-function observations.
- `cpp-annotation-native-triage-r10.json`, its script, AST JSON, stderr and token
  dumps retain the final native comparison and product-source digests.
- `cpp-structure-product-replay-r1.jsonl` and its summary retain the full frozen
  C++ cohort and normalized recovered artifacts.
- `cpp-structure-full-analyzer-replay-r1.jsonl` and its summary retain direct
  analyzer outcomes for all 19,026 C++ paths.
- `cpp-structure-unit-native-r1.json` retains native fixture syntax checks.
- `cpp-structure-quality-r2.log` and `.exit` retain the final quality preflight;
  Semgrep runs outside the sandbox.
- `cpp-structure-validation-receipt-r1.json` retains the examined full gate,
  source fingerprints and validation limits.

Earlier native attempts remain available; their mismatches exposed the product
and oracle issues described above. The separate malformed/future-language
inventory remains authoritative for exclusions. This phase does not claim a
benchmark-wide clean bill.
