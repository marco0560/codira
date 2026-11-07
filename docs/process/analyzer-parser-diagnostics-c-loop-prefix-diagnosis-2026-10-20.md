# PostgreSQL C loop-prefix diagnosis — 2026-10-20

An independent census of all **951 still-open PostgreSQL originals attributed
to C** identifies another shared parser cause. The current, unmodified public
C analyzer (logical version 17) under its default profile produces **133 clean and 818 partial
results**, with **zero exceptions**. All original bytes match classification
v37. These are parser-state measurements, not new qualifications or fixes.

A separate direct-source parser inventory finds missing semicolons in 424
files. Examples occur after PostgreSQL's statement-shaped `foreach(...)`,
`forboth(...)` and related macros, before their written statement or compound
body. Direct-source parser state is not identical to public-analyzer state:
the latter also captures local includes and applies conditional views.

## Causal grammar probe

`src/include/nodes/pg_list.h` supplies the macro definitions. Direct replacements
begin with one or more `for` headers; wrappers such as `foreach_ptr` forward to
those replacements. This is different from ordinary calls such as
`foreach_delete_current`, which is excluded from the loop-prefix inventory.

Among the 951 originals, 294 have recognized loop-macro call nodes and all 294
currently produce partial public-analyzer results. A counterfactual grammar view
replaces only those callee tokens with equal-width `while` tokens, preserving
original byte and line coordinates. **151** then have entirely clean
direct-source trees; 143 still have other errors. This is a diagnostic grammar
probe, not an implementation, native equivalence claim or recovery forecast.
It neither selects conditional branches nor expands the macro replacements.

The counterfactual cannot be shipped as-is: the changed grammar no longer
contains the original macro-call node. A correction must preserve that written
invocation as source call evidence and retain calls in its arguments and body.
No generated loop variables or calls from a replacement body should be invented.

## Independent native and call-preservation controls

Clang 22 accepts four unchanged originals under the retained source-configured
PostgreSQL C17 context:

- `src/backend/tsearch/dict_simple.c` — `foreach`;
- `src/backend/utils/misc/queryenvironment.c` — `foreach`;
- `src/backend/nodes/multibitmapset.c` — `forboth`;
- `src/test/modules/test_plan_advice/test_plan_advice.c` — `foreach_node`.

The fourth initially failed because its extension-specific header search root
was missing from the QA command. Its Makefile explicitly supplies
`-I$(top_srcdir)/contrib/pg_plan_advice`. Adding that exact declared root in a
fresh native probe succeeds. The failed probe is retained; it is not evidence
of a product error or malformed source. Other compiler/context inputs and
generated headers are checked against the retained context manifest hashes.

A separate isolated monkeypatch experiment runs the current artifact builder
against the counterfactual syntax while keeping original source bytes. The
unchanged R9 compiled-AST/preprocessor reference rejects the naive variant in
all four cases for missing written loop-macro calls. Restoring only the original
call nodes at their original positions eliminates those added call mismatches.
`dict_simple.c` and `multibitmapset.c` then match all represented native metadata.
The other two remain held for the same pre-existing issues or limitations:
an assertion argument without native coverage, and generated nonliteral module
magic declarations. No reference check is removed or relaxed.

The actual current analyzer can already extract matching metadata from the two
matching cases despite marking their parse partial. The reference's artifact
comparison alone does not qualify a file: parser completeness and current
production provenance are separate admission requirements. All measurements
above remain outside the classification ledger.

## Correction requirements

Recover a source-proven statement-prefix role while retaining the written macro
call, its source coordinates, argument calls and following body. Require
contained reaching definitions, compatible alternatives, valid arity and an
appropriate statement position. Unknown names, incompatible replacements,
keyword overrides, undefinitions, late definitions and unrelated syntax errors
must remain held. Do not infer compiler conditions or generate declarations from
potential macro expansion. This keeps the source-evidence boundary of ADR-030.

Production C code and its logical/package versions remain unchanged. The C++
expansion-capability proposal is a separate pending decision. The next C step is
to implement and validate this source-level structural recovery, then measure
and independently qualify originals before admitting any additional files.

## Retained evidence

Under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `postgres-c-default-census-r1/`: all 951 actual default artifacts, complete
  source identities, parser-error inventory and checkpoint/resume script;
- `postgres-c-loop-prefix-probe-r1/`: exact header definitions, source-coordinate
  substitutions, all counterfactual views and the 294/151 parser measurements;
- `postgres-c-loop-prefix-native-probe-r1/`: native commands, ASTs and stderr,
  including the missing-extension-root failure;
- `postgres-c-loop-prefix-native-probe-r2/`: the corrected extension-root probe
  with the source Makefile identity and exact declared flag;
- `postgres-c-loop-call-preservation-probe-r1/`: actual and isolated
  counterfactual artifacts, native macro events and unchanged R9 comparisons.

The ledger remains v37: **2,672 verified fixes, 453 separated, 22,637 open**.
