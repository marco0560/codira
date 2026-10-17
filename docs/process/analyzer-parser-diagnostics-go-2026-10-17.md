# Go parser diagnostics: expression allocations

The five Go files in the frozen analyzer main-r1 diagnostic population are valid
VictoriaMetrics tests. Native Go 1.27.1 accepts their syntax. Their use of
`new(expression)`, introduced in Go 1.26, encounters the bundled
Tree-sitter Go 0.25.0 grammar's special handling of `new(type)`. These files stay
in the fix population: the Go analyzer does not declare an older language ceiling.
The [Go 1.26 release notes](https://go.dev/doc/go1.26) document the expression form.

## Correction and source fidelity

Go analyzer distribution 2.0.3, logical analyzer version 4, adds a restricted
parser compatibility path. Clean trees use the original parser result. When a
tree contains errors, erroneous call expressions whose function is the `new`
identifier receive a three-byte parser-only alias. Error fragments with a `new`
identifier followed by an opening parenthesis are also handled, including
composite literal arguments. Comments between those tokens are allowed.

The candidate is accepted only if its whole tree parses cleanly. Otherwise the
original partial result and diagnostics survive. Clean type allocations are not
rewritten. Extraction reads the original bytes; the alias is never used as
artifact text. Equal byte lengths preserve line and byte-column coordinates.
The logical version advances so existing cached partial results are invalidated.
Root development/bundle pins and the official bundle distribution are aligned.
The generated installer catalog is verified unchanged because its input manifest
does not encode these distribution versions or this parser implementation.

## Frozen-source replay

Direct corrected-analyzer replay recovers complete symbol indexing for all five
files. Every source SHA-256 matches the frozen inventory. A separate native
`go/parser` AST probe verifies the complete function-declaration inventory and
the source coordinates of every direct `new` call inside those functions.

| VictoriaMetrics path | Functions | Matched `new` calls |
| --- | ---: | ---: |
| `app/vmauth/auth_config_test.go` | 18 | 1 |
| `app/vmauth/target_url_test.go` | 10 | 6 |
| `apptest/tests/ingestprotocols_test.go` | 4 | 28 |
| `lib/protoparser/opentelemetry/pb/pb_test.go` | 3 | 3 |
| `lib/protoparser/opentelemetry/stream/streamparser_test.go` | 22 | 11 |
| **Total** | **57** | **49** |

This is native syntax and artifact extraction evidence. It does not claim
semantic compilation, test execution, backend persistence, or a complete
benchmark rerun.

Focused regressions cover nested calls, expression and composite arguments,
ordinary type allocations, comments/string contents, an existing `n_w` call,
Unicode byte positions, source preservation, and retention of unrelated syntax
damage. The new complete-coverage regression failed before the correction; all
eight Go package tests pass afterward.

The final metadata-focused run passes all ten selected tests. The complete
workflow-quality preflight passes outside the sandbox, including Semgrep with
21 rules and zero findings. The full repository gate also passes outside the
sandbox: 1,716 tests pass, three are skipped, total coverage is 86%, and the
fresh structural index reports 784 indexed files, zero failures and zero
coverage issues. The gate runs with embeddings deferred, as prescribed by the
validator; this is not embedding-completeness evidence. The sandbox preflight's
stalled Semgrep attempt remains recorded separately from the successful checks.

Evidence is retained under the worktree-relative
`.artifacts/analysis/parser-diagnostics-20261017-r1/`: `go-replay-r1.json`,
`go-native-oracle.go`, `go-native-oracle.json`, and the baseline evidence database.
The [initial separation report](analyzer-parser-diagnostics-separation-2026-10-17.md)
remains an immutable initial classification; this correction addresses five of
its 25,334 remaining investigation paths. Other languages remain open.
