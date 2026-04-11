# Issue 009 Execution

## Purpose

This branch-local document records the execution plan for issue `#9` after the
architectural ADR has been accepted and before the implementation phases land.

## Branch

The implementation branch for this issue is:

```text
issue/9-capability-signal-layer
```

## Phase 0 Outcome

Phase 0 is complete when both of the following exist and agree with each
other:

1. `docs/adr/ADR-006-capability-driven-signal-layer.md`
2. this execution document

Phase 0 intentionally does **not** change runtime scoring behavior.

## Phase 1 Outcome

Phase 1 produced a concrete inventory note:

* `docs/process/issue-009-capability-signal-layer-inventory.md`

That note records the current implicit retrieval boundary, including:

* current retrieval producer shapes
* current score-bearing evidence families
* current planner and channel routing assumptions
* current explain-mode diagnostics already available for migration

## Phase 2 Outcome

Phase 2 introduces the first internal retrieval-facing contract beside
`LanguageAnalyzer`.

The first version is intentionally minimal:

* versioned producer identity through `producer_name`, `producer_version`, and
  `capability_version`
* declared retrieval capabilities
* deterministic partitioning of known versus unknown capabilities for future
  diagnostics

This phase still does **not** change runtime scoring behavior.

The current branch first introduced a query-layer compatibility bridge for
channel-shaped retrieval paths. That compatibility layer has since been
collapsed into direct query producer specs so the runtime no longer depends on
synthetic `RetrievalProducer` objects.

The accepted architecture at this point is the "good Option 1" model:

* analyzers continue to satisfy `LanguageAnalyzer`
* retrieval-facing capability metadata lives in a shared query producer layer
* the core must consume declared producer metadata rather than analyzer
  internals
* analyzers may adopt `RetrievalProducer` later where that is genuinely useful,
  but this is not required for the main migration path

Phase 3 now has an initial schema scaffold as well:

* `src/codira/query/signals.py`

That module defines immutable retrieval signals and deterministic sort keys,
but does not yet change runtime aggregation.

## Detailed Implementation Plan

### Phase 1 — Inventory current evidence and scoring entry points

Goal:
Build a source-grounded inventory of the current ranking inputs before adding
new abstractions.

Primary files:

* `src/codira/query/context.py`
* `src/codira/query/classifier.py`
* `src/codira/query/exact.py`
* `src/codira/semantic/search.py`
* `src/codira/contracts.py`
* `docs/architecture/query-pipeline.md`

Tasks:

1. Enumerate every current evidence source used by `context_for`.
2. Separate orchestration concepts from score-bearing concepts.
3. Record current merge inputs, diversity inputs, and explain outputs.
4. Identify where current logic branches on channel names, evidence families,
   or language-specific features.
5. Identify current invariants already protected by tests.

Deliverables:

* implementation notes embedded in code comments or docs as appropriate
* an updated execution ledger if the discovered boundary differs from the ADR

Exit criteria:

* every current score-bearing path is accounted for
* no hidden scoring entry point remains unlisted

### Phase 2 — Minimal capability model

Goal:
Introduce a small internal capability representation without changing
behavior.

Primary files:

* `src/codira/contracts.py`
* `src/codira/query/classifier.py`
* `src/codira/query/context.py`
* `tests/test_contracts.py`
* `tests/test_context_rendering.py`

Tasks:

1. Define the minimal capability vocabulary needed for current retrieval.
2. Decide whether capabilities attach first to analyzers, channels, or a new
   retrieval-producer abstraction.
3. Keep the first contract internal and deterministic.
4. Ensure missing capabilities degrade to absence rather than failure.

Accepted direction:

* keep the retrieval-facing contract beside `LanguageAnalyzer`
* do not require built-in analyzers to implement `RetrievalProducer` yet
* centralize shared producer metadata in query-side descriptors
* forbid core scoring from depending on analyzer implementation details

Initial capability candidates:

* `symbol_lookup`
* `semantic_text`
* `embedding_similarity`
* `task_specialization`
* `graph_relations`
* `issue_annotations`
* `diagnostics_metadata`

Exit criteria:

* the core can inspect capabilities generically
* no ranking behavior changes yet

### Phase 3 — Typed signal model and normalization rules

Goal:
Define the internal signal objects that become the future scoring substrate.

Primary files:

* `src/codira/query/` (new module likely required)
* `src/codira/contracts.py`
* `tests/test_context_rendering.py`
* `tests/test_retrieval_merge.py`

Tasks:

1. Create a typed signal model with deterministic ordering fields.
2. Define normalized properties for contribution strength, distance, and
   attribution.
3. Reuse durable symbol identities already emitted by analyzers.
4. Keep final scores out of the signal contract.

Recommended signal kinds for the first pass:

* exact symbol
* token/symbol text
* embedding similarity
* relation
* proximity
* repeated evidence

Exit criteria:

* signal schema is explicit and test-covered
* normalization semantics are documented in code and consistent with the ADR

### Phase 4 — Adapters from current evidence to signals

Goal:
Represent existing retrieval evidence as signals without changing intended
ranking behavior.

Primary files:

* `src/codira/query/context.py`
* `src/codira/query/exact.py`
* `src/codira/semantic/search.py`
* `tests/test_retrieval_merge.py`
* `tests/test_characterization_phase2.py`

Tasks:

1. Wrap exact symbol candidates as signals.
2. Wrap embedding candidates as signals.
3. Wrap current semantic/textual candidates as signals.
4. Preserve existing ranking characteristics while both representations may
   temporarily coexist.

Exit criteria:

* current evidence can be represented entirely as signal objects
* old and new representations can be compared during migration

### Phase 5 — Capability-gated signal collection

Goal:
Collect signals through generic capability checks rather than implicit
feature-specific assumptions.

Primary files:

* `src/codira/query/context.py`
* `src/codira/query/classifier.py`
* `tests/test_context_rendering.py`
* `tests/test_retrieval_merge.py`

Tasks:

1. Add a deterministic signal collection step.
2. Use capability declarations to decide which signal families can be built.
3. Preserve current planner ordering while changing the internal substrate.
4. Keep unsupported capability families silent and deterministic.

Exit criteria:

* the core assembles a per-query signal set generically
* the current planner remains understandable and explainable

### Phase 6 — Core signal aggregation for current ranking behavior

Goal:
Move scoring from current channel/evidence-specific merge helpers onto signal
aggregation while preserving behavior as closely as possible.

Primary files:

* `src/codira/query/context.py`
* `tests/test_retrieval_merge.py`
* `tests/test_characterization_phase2.py`
* `tests/test_context_rendering.py`

Tasks:

1. Define central aggregation rules over signals.
2. Preserve exact symbol dominance explicitly.
3. Preserve deterministic ordering and stable tie-breaking.
4. Keep current diversity and role-bias semantics compatible.

Exit criteria:

* merged ranking reads normalized signals rather than ad hoc evidence bundles
* ranking-sensitive tests remain green

### Phase 7 — Call and proximity integration through signals

Goal:
Migrate graph-derived relevance into the signal layer instead of leaving it as
special-case query logic.

Primary files:

* `src/codira/query/context.py`
* `src/codira/query/exact.py`
* `tests/test_call_graph.py`
* `tests/test_retrieval_merge.py`

Tasks:

1. Represent call-graph and include-graph evidence as signals where
   appropriate.
2. Normalize direct relation versus proximity semantics.
3. Bound graph-derived contributions centrally.
4. Avoid language-name branching in the final aggregation step.

Exit criteria:

* call/proximity relevance participates through signals
* language-specific extraction remains outside final scoring policy

### Phase 8 — Explain and JSON alignment

Goal:
Make the new architecture visible in explain mode and structured output.

Primary files:

* `src/codira/query/context.py`
* `src/codira/schema/context.schema.json`
* `tests/test_json_schema.py`
* `tests/test_context_rendering.py`
* `tests/test_characterization_phase2.py`

Tasks:

1. Replace channel-only merge diagnostics with signal-aware explain output.
2. Preserve explain stability and readability.
3. Decide whether JSON output can evolve in place or requires versioned
   additions.
4. Keep current planner metadata while adding signal contribution tracing.

Exit criteria:

* explain mode can attribute ranking to signal families and capabilities
* JSON schema and tests are updated intentionally

### Phase 9 — Analyzer and channel contract follow-up

Goal:
Adopt the new capability contract at the producer boundary in a disciplined
way.

Primary files:

* `src/codira/contracts.py`
* `src/codira/analyzers/python.py`
* `src/codira/analyzers/c.py`
* `src/codira/analyzers/bash.py`
* `examples/plugins/codira_demo_analyzer/...`
* `tests/test_contracts.py`
* `tests/test_plugins.py`

Tasks:

1. Extend the producer-side contract with explicit capability declaration.
2. Update built-in analyzers incrementally.
3. Update the demo analyzer plugin example.
4. Avoid forcing third-party API stability prematurely; keep the new surface
   documented as internal until it has proven out.

Exit criteria:

* at least one clean end-to-end producer path uses the new contract
* built-ins and plugin tests agree on the new expectations

### Phase 10 — Validation matrix and migration hardening

Goal:
Prove the architecture preserves current guarantees and is safe for follow-on
analyzer work such as JSON and Make.

Validation categories:

1. deterministic ordering
2. exact-match dominance
3. capability-gated behavior
4. cross-language consistency
5. explain stability
6. regression compatibility for current retrieval behavior
7. bounded aggregation complexity

Primary files:

* `tests/test_retrieval_merge.py`
* `tests/test_context_rendering.py`
* `tests/test_characterization_phase2.py`
* `tests/test_call_graph.py`
* `tests/test_json_schema.py`

Exit criteria:

* the ADR invariants are covered by tests
* JSON and Make analyzer work can target the new boundary instead of the old
  merge internals

## Suggested PR Sequence

1. ADR + execution plan
2. evidence/scoring inventory + minimal capability scaffolding
3. signal model
4. signal adapters for current evidence
5. signal aggregation for existing ranking behavior
6. graph/proximity migration
7. explain and schema alignment
8. producer-side contract adoption and hardening
