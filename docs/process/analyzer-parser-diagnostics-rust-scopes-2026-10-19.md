# Rust nested item extraction and ownership

The parser-recovery phase left 19 original Rust diagnostic paths open because
the extractor omitted 565 native items. It visited root declarations and methods
under root traits/impls, but skipped declarations in inline modules and local or
associated scopes. The original source corpus and benchmark identity remain
unchanged; this correction lives in the dedicated diagnostic worktree.

## Correction

The extractor now visits written item scopes throughout the same source file.
Inline modules, local types/functions/constants/macros, associated constants,
nested trait/impl containers and foreign function signatures are included.
Out-of-file module declarations remain declarations: no module loading, Cargo,
macro expansion, cfg selection or compiler execution enters the analyzer.

Module and enclosing declaration scopes qualify identities. Repeated written
occurrences retain deterministic declaration suffixes. A method belongs to its
nearest trait/impl without crossing an inline module. Nested impl methods are
not duplicated in outer containers. Method flags use the nearest callable/class
scope rather than the existence of any outer function. Unaffected root identities
are preserved; corrected nested identities can change, requiring reindexing.

Call extraction stops at separately declared bodies, while closure calls stay in
their lexical callable. Local helper calls therefore stop appearing both on the
helper and its enclosing method. Enum member extraction visits the owning enum's
direct variant list, so an enum declared in a discriminant block no longer adds
its variants to the outer enum. Documentation and enum parent identities continue
through the existing occurrence disambiguation and attachment pipeline.

The Rust distribution advances to **2.0.3**, logical analyzer **5**, and official
bundle **2.0.27**. Root pins, package assertions and the generated lockfile agree.
Other analyzer versions and storage schemas do not change. No release is published.

## Verification

The focused Rust/bundle suite passes **44 tests**. Four added controls cover module
namespaces and associated constants, nested callable bodies and closure calls,
duplicate block-local names and nested impls, and enum member ownership. All four
original control sources also pass the unexpanded native edition-2024 parser;
their public analyzer payloads and native ASTs are retained.

The complete replay covers **3,870 Rust sources** against commit `df7f72a`.
All remain parser-clean, with zero exceptions and zero parsing-status regressions.
Complete canonical payloads stay identical for **2,283 files**; **1,587 change**
because of newly extracted items, corrected scopes, call ownership or documentation
attachments. These changes are intentional, not presented as byte preservation.

Every changed payload has an independent native item comparison: **1,587 of 1,587
files match, with 90,113 named declarations**, zero compiler rejections, zero missing
or extra graded items and zero native-reader limitations. Compiler editions come
from the nearest Cargo package and its workspace metadata. Original native ASTs
are reused only when source hashes and editions match; other ASTs are captured
with their exact commands and hashes.

The original 46-file diagnostic cohort independently matches **4,145 native items**,
including all 565 previously omitted items. The 19 newly qualified files account
for 3,581 of those declarations. Classification-v14 admits those 19 after the full
gate: **646 verified recoveries**, **24,673 original paths still open**, and no
remaining Rust paths in this frozen diagnostic cohort. This does not declare all
Rust semantics or the complete analyzer benchmark clean.

Native grading checks named callable, macro, struct, enum, trait, impl, constant
and module identities and physical declaration lines. Impl comparison uses kind
and start line. Anonymous underscore constants have no name binding and are
excluded from the broader comparison. Type aliases, statics, use trees, fields,
full call resolution and expanded/type-checked semantics remain outside this
native oracle. Focused ownership tests separately check the call and enum repairs.

Real SQLite and DuckDB indexing probes use three byte-identical native-qualified
corpus copies. Both route all files to Rust logical version 5, persist 121 checked
native symbol rows, reuse all three files incrementally and reproduce identical
checked symbol rows after a full rebuild. This is persistence/routing validation,
not retrieval or expanded Rust execution grading.

## Durable evidence and remaining objective

Retain the following under
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `rust-native-items-r4/`: complete original-cohort identity comparisons;
- `rust-scopes-full-replay-r1/`: canonical before/after payloads and source bindings;
- `rust-scopes-changed-native-r1/`: native comparisons for every changed payload;
- `rust-scopes-controls-native-r1/`: native control sources, ASTs and public results;
- `rust-scopes-backend-probe-r1.json`: real backend routing/reuse/rebuild checks;
- `rust-scopes-quality-r1.log`: inexpensive validation with Semgrep outside the sandbox;
- `classification-v14.jsonl` and its CSV/summary: source-bound admission ledger;
- `rust-scopes-validation-receipt-r1.json`: examined full gate, source hashes and
  immutable evidence bindings, retained before successful temporary gate cleanup.

The complete goal remains open. C/C++, Bash, JavaScript and supported-version
Python diagnostics still require investigation and correction; deliberately
malformed and future-version exclusions remain separately classified.
