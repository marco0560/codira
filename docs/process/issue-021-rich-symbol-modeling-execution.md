# Issue 021 Execution

## Purpose

This document records the planned execution order for issue `#21` after the
symbol-modeling ADR has been accepted.

It exists to keep richer symbol work bounded so overload metadata, declaration
ontology changes, schema work, and query-surface changes do not land as one
opaque feature.

## Branch

The long-lived design and integration branch for this issue is:

```text
issue/21-rich-symbol-modeling
```

Concrete implementation slices should still land through short-lived branches
or directly on `main`, then be rebased back into the issue branch as needed.

## Phase 0 Outcome

Phase 0 is complete when both of the following exist and agree with each
other:

1. `docs/adr/ADR-016-richer-symbol-modeling-for-overload-metadata-and-named-declarations.md`
2. this execution document

Phase 0 does **not** change runtime behavior.

## Detailed Implementation Plan

### Phase 1 — Symbol ontology inventory and contract update

Goal:
Inventory current symbol-like artifacts and formalize which categories are
canonical symbols versus subordinate metadata.

Primary files:

* `src/codira/models.py`
* `src/codira/contracts.py`
* `src/codira/normalization.py`
* `tests/test_contracts.py`

Tasks:

1. Enumerate the current first-level symbol categories already exposed by the
   repository.
2. Add contract vocabulary for child declaration metadata.
3. Preserve existing stable IDs for modules, classes, functions, and methods.
4. Keep current declaration artifacts queryable without changing default output
   order.

Exit criteria:

* ontology terms are explicit in code and tests
* current symbol behavior remains deterministic
* no overload child rows exist yet

### Phase 2 — Overload child metadata model

Goal:
Represent overload declarations as subordinate metadata attached to canonical
callables.

Primary files:

* `src/codira/parser_ast.py`
* `src/codira/normalization.py`
* `src/codira/models.py`
* `tests/test_contracts.py`

Tasks:

1. Collect overload declaration metadata without emitting runtime duplicate
   function rows.
2. Define ordered child metadata attached to the canonical callable.
3. Assign deterministic overload stable IDs based on declaration order.
4. Extend regression tests for duplicate-name overloads and callable lookup.

Exit criteria:

* overload metadata exists only as child declaration data
* canonical callable rows remain unchanged
* overload ordering is deterministic and test-covered

### Phase 3 — Storage and schema migration

Goal:
Persist overload child metadata without redefining current callable storage.

Primary files:

* `src/codira/storage.py`
* `src/codira/sqlite_backend_support.py`
* schema or migration helpers
* storage tests

Tasks:

1. Add additive storage for child declaration metadata.
2. Persist explicit parent stable ID links.
3. Define migration behavior for existing indexes.
4. Keep canonical callable identity reuse unchanged.

Exit criteria:

* schema changes are additive
* migrations preserve existing canonical IDs
* storage round-trip tests cover overload metadata

### Phase 4 — `sym` JSON and detail rendering

Goal:
Expose overload metadata only through canonical-callable detail rendering while
keeping default output stable.

Primary files:

* `src/codira/cli.py`
* query/rendering modules
* CLI and JSON output tests

Tasks:

1. Preserve current default plain-text `sym` output.
2. Add the optional `overloads` JSON field on canonical callables when detail
   rendering is requested.
3. Confirm overload variants never appear as default standalone `sym` rows.
4. Add regression coverage for JSON and plain rendering.

Exit criteria:

* default `sym` output remains stable
* overload detail is explicit and opt-in
* rendering behavior is deterministic and tested

### Phase 5 — `ctx` typed metadata integration

Goal:
Let overload metadata contribute bounded typed API evidence without outranking
the canonical callable.

Primary files:

* `src/codira/query/context.py`
* `src/codira/query/signals.py`
* retrieval and ranking tests

Tasks:

1. Add bounded overload-derived scoring inputs.
2. Preserve canonical callable dominance for exact matches.
3. Attribute overload-derived evidence explicitly in explain output.
4. Add regression coverage for signature-oriented queries.

Exit criteria:

* typed metadata can help ranking
* canonical runtime results remain dominant
* explain diagnostics expose provenance clearly

### Phase 6 — `audit` and docstring policy alignment

Goal:
Keep documentation audits centered on the canonical callable while allowing
overload metadata to remain auxiliary.

Primary files:

* `src/codira/docstring.py`
* `src/codira/cli.py`
* audit tests

Tasks:

1. Confirm overload stubs do not create independent docstring obligations.
2. Keep canonical callable doc audits authoritative.
3. Add tests covering overload-bearing callables and audit output.

Exit criteria:

* audit behavior stays stable
* overloads remain auxiliary metadata
* regression tests protect the policy boundary

### Phase 7 — Analyzer-specific named declaration expansion

Goal:
Extend the declaration ontology deliberately for high-signal named
declarations, starting with deterministic analyzer-owned categories.

Primary files:

* analyzer modules
* `src/codira/models.py`
* normalization and query tests

Tasks:

1. Identify candidate declaration kinds that satisfy deterministic extraction.
2. Add one category at a time with explicit analyzer mappings.
3. Keep deferred categories out of scope unless they meet the ADR criteria.
4. Preserve stable query behavior as ontology coverage expands.

Exit criteria:

* new declaration kinds are additive and explicit
* default query behavior remains non-noisy
* analyzer mappings are documented and tested

## Non-Goals

The following remain out of scope unless this ledger and `ADR-016` are updated
explicitly:

* reintroducing overload stubs as ordinary runtime functions or methods
* treating every assignment as a symbol
* making imports or re-exports default first-level symbols
* allowing overload metadata to outrank canonical implementations by default
