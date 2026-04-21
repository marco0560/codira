# ADR-016 — Richer symbol modeling for overload metadata and named declarations

**Date:** 21/04/2026
**Status:** Accepted

## Context

Issue `#21` asks `codira` to define a richer symbol model that captures
human-facing declarations without regressing the correctness fix that excluded
Python `@overload` stubs from normal runtime function artifacts.

The repository already enforces one critical invariant through regression
tests:

* overload stubs must not appear as ordinary runtime `function` or `method`
  artifacts

That invariant must remain intact. At the same time, the issue identifies two
real gaps in the current symbol surface:

* typed overload declarations carry useful API information that is currently
  discarded entirely
* programmers often mean more than runtime functions and classes when they ask
  for "symbols"

The repository therefore needs an explicit design boundary before any schema,
query, or analyzer work proceeds.

The design must preserve the following constraints:

* existing module, class, function, and method stable IDs remain unchanged
* overload metadata stays subordinate to the canonical runtime callable
* exact runtime implementation matches remain dominant in retrieval
* default plain-text CLI behavior does not become noisier
* analyzer-specific declarations map into a normalized symbol ontology instead
  of bypassing shared contracts

## Decision

Adopt a two-tier symbol model:

1. **canonical symbols** remain the primary query and rendering surface
2. **child declaration metadata** may attach richer declaration detail to a
   canonical symbol without becoming a default peer result

This keeps runtime callables authoritative while allowing future retrieval and
rendering surfaces to recover typed or declaration-oriented metadata
explicitly.

### Overload metadata is child metadata, not a top-level runtime symbol

Python overload stubs must not be reintroduced as ordinary `function` or
`method` artifacts.

Instead:

* the canonical implementation remains the only top-level callable symbol
* overload declarations become child declaration metadata owned by that
  canonical callable
* overload metadata may receive its own durable identity, but that identity is
  subordinate and never replaces the parent callable stable ID

The accepted durable identity rule is:

* callable parent:
  * `python:function:<module>:<name>`
  * `python:method:<module>:<Class.name>`
* overload child:
  * `python:overload:<module>:<qualified-name>:<ordinal>`

Examples:

* `python:function:pkg.sample:build`
* `python:overload:pkg.sample:build:1`
* `python:overload:pkg.sample:build:2`
* `python:method:pkg.sample:Demo.load`
* `python:overload:pkg.sample:Demo.load:1`

`<ordinal>` is the declaration order among overload stubs attached to the same
canonical callable within one module.

The accepted parent-child binding rule is:

* each overload child stores the canonical parent stable ID explicitly
* the parent callable owns an ordered overload collection sorted by source
  line, then ordinal as a deterministic tie-breaker

### Overload output contract

The existing default `sym` output must remain stable and concise.

Accepted contract:

* plain-text `sym` output does **not** emit overload variants as standalone
  rows
* default JSON symbol rows do **not** emit overload variants as standalone peer
  results
* when a callable result is rendered in a detail-capable JSON surface, overload
  metadata appears only under an optional `overloads` field on the canonical
  callable row
* plain-text rendering may later add an indented child section under the
  canonical callable, but only behind an explicit detail-oriented surface and
  never in the current default summary output

Accepted JSON shape for future callable detail rendering:

```json
{
  "kind": "function",
  "name": "build",
  "stable_id": "python:function:pkg.sample:build",
  "path": "pkg/sample.py",
  "lineno": 10,
  "overloads": [
    {
      "kind": "overload",
      "stable_id": "python:overload:pkg.sample:build:1",
      "parent_stable_id": "python:function:pkg.sample:build",
      "ordinal": 1,
      "signature": "build(value: int) -> int",
      "lineno": 4,
      "end_lineno": 4,
      "docstring": null
    }
  ]
}
```

Rules:

* `overloads` is omitted when empty
* overload entries never appear as top-level results in the current default
  `sym` contract
* overload metadata is additive detail, not a replacement for the parent row

### `refs` behavior

Overload metadata does not participate as an independent `refs` target in V1.

Accepted rule:

* references always resolve to the canonical callable
* overload children do not receive separate incoming or outgoing reference
  graphs
* if future tooling needs signature-aware reference refinement, it must be
  introduced as an explicit extension rather than inferred implicitly

### `ctx` ranking behavior

Overload metadata may contribute typed API evidence, but it remains subordinate
to runtime implementation evidence.

Accepted rule:

* an exact canonical callable match always outranks overload metadata
* overload metadata may provide bounded boosting when the query clearly asks
  about accepted signatures or typed call shapes
* overload metadata must not outrank the owning callable by default
* explain diagnostics must attribute any overload-derived boost explicitly to
  child metadata rather than treating it as another exact symbol hit

### `audit` behavior

Overload stubs do not create independent doc-audit obligations.

Accepted rule:

* callable doc audits continue to target the canonical runtime implementation
* overload children may contribute descriptive signature metadata
* overload stubs do not require separate docstrings in V1

### Expanded canonical symbol categories

The repository should distinguish between:

* canonical symbols directly queryable as first-level symbol rows
* subordinate child metadata attached to canonical symbols

The accepted V1 canonical categories are:

* module or package
* class or named type
* function, method, or callable
* named declaration emitted through analyzer normalization

The accepted V1 named declaration bucket includes:

* `typedef`
* `enum`
* `struct`
* `json_schema_definition`
* `json_schema_property`
* `json_manifest_name`
* `json_manifest_script`
* `json_manifest_dependency`
* `json_release_plugin`
* `json_release_branch`

The accepted V1 analyzer-mapping direction is:

* keep runtime callables and classes in their existing dedicated artifact types
* continue modeling non-callable named declarations through normalized
  declaration artifacts
* extend declaration kinds deliberately when a new analyzer can emit stable,
  deterministic named declarations

The accepted V1 additions for future expansion are:

* Python `type_alias`
* enum members when the analyzer can attach them deterministically to the
  parent enum

The following remain deferred:

* arbitrary module-level variables
* every assignment target
* generic constants without a stable declaration rule
* imports and re-exports as default first-level symbols

Deferred categories may be added only when they satisfy all of the following:

* deterministic extraction
* stable identity rules
* non-noisy default query behavior
* clear analyzer-to-ontology mapping

### Storage and schema direction

The repository should not overload current function rows to pretend overload
stubs are runtime callables.

Accepted storage direction:

* keep existing callable storage intact for canonical runtime callables
* add a child declaration storage surface for overload metadata
* persist explicit parent stable ID links
* preserve current stable IDs for modules, classes, functions, and methods

Backward-compatibility rule:

* existing indices may require a schema migration when overload child storage
  lands
* migration must be additive for canonical callable identities and must not
  change existing stable IDs

## Consequences

### Positive

* preserves the correctness fix for overload stub exclusion
* recovers useful typed API metadata without reintroducing duplicate runtime
  symbols
* gives non-Python analyzers a clearer path for named declaration coverage
* keeps default CLI output stable while leaving room for richer detail surfaces

### Negative

* introduces another relation type between canonical symbols and child
  declarations
* richer rendering and retrieval will require schema, normalization, and query
  follow-up work
* some programmer-facing names remain intentionally deferred to avoid noisy
  symbol inventories

### Neutral / Trade-offs

* overload children gain durable identities, but those identities are internal
  detail first rather than default user-visible peer results
* declaration coverage broadens the symbol ontology without redefining every
  declaration as a callable-like symbol
* V1 favors correctness and stable defaults over maximal declaration coverage

## Execution Rules

* Use a dedicated execution ledger for issue `#21` under `docs/process/`.
* Treat this ADR as the design baseline for future implementation slices.
* Do not reintroduce overload stubs as ordinary runtime function rows.
* Do not change existing callable stable IDs without a separate migration ADR.
* Keep default `sym`, `refs`, `ctx`, and `audit` behavior stable until each
  follow-up slice lands with regression coverage.

## Phase Ledger

* [x] Phase 0 — ADR and execution ledger
* [ ] Phase 1 — Symbol ontology inventory and contract update
* [ ] Phase 2 — Overload child metadata model
* [ ] Phase 3 — Storage and schema migration
* [ ] Phase 4 — `sym` JSON/detail rendering
* [ ] Phase 5 — `ctx` typed metadata integration
* [ ] Phase 6 — `audit` and docstring policy alignment
* [ ] Phase 7 — Analyzer-specific named declaration expansion
