# ADR-006 — Capability-driven signal layer for language-agnostic scoring

**Date:** 02/04/2026
**Status:** Accepted

## Context

Issue `#9` asks `codira` to make retrieval scoring genuinely pluggable
without moving final ranking policy into analyzers or channels.

The current repository already has several strong architectural pieces:

* pluggable `LanguageAnalyzer` and `IndexBackend` contracts in
  `src/codira/contracts.py`
* normalized analyzer output through `AnalysisResult` and durable symbol
  identities
* a deterministic query planner in `src/codira/query/classifier.py`
* a multi-channel retrieval merge in `src/codira/query/context.py`
* explain-mode diagnostics that expose planner choices, channel results,
  merge details, diversity selection, and include-graph expansion

That foundation is useful, but it is not yet sufficient to keep future
retrieval signals language-agnostic.

Today, the core scoring path still reasons in terms of current channel names
and feature-specific evidence families such as:

* exact symbol results
* semantic text matches
* embedding-ranked candidates
* test and script bias
* include-graph expansion
* reference enrichment

This works for the current built-in retrieval flow, but it leaves an
architectural gap:

* analyzers can participate in extraction
* backends can participate in persistence and exact lookup
* but there is no explicit contract for declaring which ranking-relevant
  semantic capabilities a language/channel can provide
* and there is no typed internal signal model that lets the core score those
  capabilities generically

Without that missing layer, new analyzers or retrieval channels risk forcing
one of the following undesirable outcomes:

* analyzer-specific branching in core scoring
* ad hoc score wiring for each new evidence family
* reduced explainability because score contributions are encoded indirectly
* tighter coupling between ranking behavior and concrete analyzer identities

The repository should preserve these invariants while fixing that gap:

* exact symbol match dominance remains explicit
* final ranking policy stays in the core
* ordering remains deterministic
* analyzers do not inject arbitrary final scores
* explain output remains stable and attributable
* migration from the current retrieval stack remains incremental

## Decision

Adopt a capability-driven signal layer between retrieval producers and the
core scoring pipeline.

### Capability declaration becomes explicit

Retrieval producers must expose an explicit internal capability contract.

For the current repository, retrieval producers are accepted first as a
retrieval-facing layer beside analyzers rather than as a requirement that all
analyzers implement retrieval directly.

The accepted first model is:

* analyzers remain responsible for extraction and normalized indexing artifacts
* retrieval producers declare query-time capabilities through shared producer
  descriptors
* the core consumes those descriptors generically instead of branching on
  analyzer internals

Analyzer-backed retrieval participation remains possible later, but it is not
required for the first end-to-end migration path.

The capability contract will describe which normalized evidence families a
producer can supply. The core will inspect capabilities generically instead of
branching on analyzer or language names, and it must do so through declared
metadata rather than implementation-specific analyzer knowledge.

### Typed signals become the scoring input

Ranking-relevant evidence will be represented as typed internal signals rather
than as analyzer-local scores or channel-specific ad hoc structures.

A signal must be:

* deterministic
* normalized
* attributable to a producer and capability
* sortable with stable tie-breaking
* compatible with existing durable symbol identities

The signal model must support at least the evidence families already implicit
in the current retrieval stack, including:

* exact symbol evidence
* token or symbolic textual evidence
* call or reference relation evidence
* graph proximity evidence
* repeated evidence reinforcement
* embedding similarity evidence

### The core remains the sole scoring authority

Analyzers and channels may declare capabilities and emit normalized signals,
but they must not define final score policy.

The core remains responsible for:

* enabling or disabling scoring components
* normalizing bounded contributions
* preserving exact-match dominance
* deterministic aggregation
* stable tie-breaking
* explain-mode rendering of signal contributions

This keeps ranking coherent across languages and prevents plugin-defined score
scales from becoming part of the public behavior.

### Migration is incremental, not a rewrite

The existing retrieval flow will be migrated in steps.

The first implementation target is not "new ranking behavior". It is a new
architectural boundary that can represent today's evidence explicitly and
preserve current behavior as closely as possible.

The migration will therefore proceed in this order:

1. inventory the current evidence and scoring entry points
2. define the capability model
3. define the signal model
4. adapt existing evidence into signals
5. let the core collect signals generically
6. move current scoring onto signal aggregation
7. align explain and JSON diagnostics with the new layer
8. only then expand analyzer/channel participation further

### The initial scope is internal

The capability and signal contracts are internal architecture first.

They should not be treated as a stable third-party plugin API until the
repository has completed at least one end-to-end migration path and the
extension semantics are validated in practice.

## Consequences

### Positive

* future analyzers such as JSON and Make can target a more stable scoring
  boundary instead of being retrofitted later
* the core can integrate new evidence families without analyzer-name checks
  or analyzer-internal branching
* explain output can describe ranking in terms of explicit signal provenance
  instead of reverse-engineering channel-specific merge details
* deterministic ranking rules become easier to test because the scoring input
  is explicit
* the existing plugin architecture becomes more credible from a retrieval
  perspective, not only from an extraction perspective

### Negative

* this introduces another internal abstraction layer and therefore more
  conceptual surface area
* migration will touch several core modules, especially
  `src/codira/query/context.py`, `src/codira/query/classifier.py`, and
  `src/codira/contracts.py`
* there is a real risk of premature generalization if too many signal types or
  capabilities are introduced before the first migration path is complete

### Neutral / Trade-offs

* the first capability model should be intentionally small even if it leaves
  some current retrieval behavior represented indirectly
* current channel names may survive as orchestration concepts while signal
  objects become the scoring substrate underneath
* analyzer participation in the new contract may arrive in stages; the first
  migrated producers do not need to include every language analyzer
* the accepted first migration path keeps retrieval producer metadata in a
  shared query-facing layer rather than requiring all analyzers to implement
  `RetrievalProducer`

## Execution Rules

* Use the dedicated issue branch `issue/9-capability-signal-layer`.
* Keep the execution ledger current as work lands.
* Phase 0 is this ADR plus the implementation plan for the remaining work.
* Do not change all analyzers immediately after merging the ADR.
* Freeze vocabulary and normalization rules before introducing score-bearing
  signal objects.
* Preserve exact-match dominance and deterministic ordering at every phase.
* Keep explain output and regression tests in scope for every scoring change.
* Merge back to `main` with a squash commit that closes issue `#9`.

## Phase Ledger

Mark each phase as work lands.

* [x] Phase 0 — ADR and detailed implementation plan
* [ ] Phase 1 — Inventory current evidence and scoring entry points
* [ ] Phase 2 — Minimal capability model
* [ ] Phase 3 — Typed signal model and normalization rules
* [ ] Phase 4 — Adapters from current evidence to signals
* [ ] Phase 5 — Capability-gated signal collection
* [ ] Phase 6 — Core signal aggregation for current ranking behavior
* [ ] Phase 7 — Call and proximity integration through signals
* [ ] Phase 8 — Explain and JSON alignment
* [ ] Phase 9 — Analyzer and channel contract follow-up
* [ ] Phase 10 — Validation matrix and migration hardening
