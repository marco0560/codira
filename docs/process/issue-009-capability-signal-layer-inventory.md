# Issue 009 Retrieval Boundary Inventory

## Purpose

This note records the current implicit retrieval contract before the
capability-driven signal layer is introduced.

It exists to answer one question precisely:

> What does the core already assume about retrieval producers today, even
> though that contract is not yet explicit?

## Current Retrieval Producers

The current retrieval path is not analyzer-driven at ranking time. It is built
 from a mix of producer shapes:

1. planner output from `src/codira/query/classifier.py`
2. exact backend-backed lookups from `src/codira/query/exact.py`
3. embedding retrieval from `src/codira/semantic/search.py`
4. context-local channel functions in `src/codira/query/context.py`
5. graph and issue enrichments also implemented in `src/codira/query/context.py`

The active runtime "producer" concept is therefore implicit and currently more
channel-shaped than analyzer-shaped.

## Current Score-Bearing Evidence Families

The core already uses several evidence families during retrieval and ranking.

### 1. Lexical / exact symbol evidence

Sources:

* direct exact lookup through `find_symbol()`
* token-aware symbol fallback scan inside `context.py`

Current assumptions:

* exact name hits are special
* lexical candidate scoring uses hardcoded features and weights
* exact symbol matches dominate broader evidence

### 2. Semantic text evidence

Source:

* `_retrieve_semantic_candidates()` in `context.py`

Current assumptions:

* semantic text matches are computed locally in the context layer
* semantic evidence is merged as a channel named `semantic`
* semantic and embedding evidence currently collapse into one merge family

### 3. Embedding similarity evidence

Source:

* `embedding_candidates()` via `semantic/search.py`

Current assumptions:

* embedding evidence is backend-backed but still exposed to the core only as a
  ranked channel result
* the core knows the channel name `embedding`
* explain output reports backend metadata separately from ranking provenance

### 4. Task-biased evidence

Sources:

* `_retrieve_test_candidates()`
* `_retrieve_script_candidates()`

Current assumptions:

* test and script relevance are represented as separate channels
* those channels are later collapsed into a generic `task` merge family

### 5. Graph-derived evidence

Sources:

* call edges
* callable references
* include-graph expansion

Current assumptions:

* these enrichments are gated by planner flags rather than declared producer
  capabilities
* graph-derived relevance is partially embedded in context-layer orchestration
  rather than represented as an explicit score-bearing contract

### 6. Documentation issue evidence

Source:

* `docstring_issues()` and issue-driven symbol ranking

Current assumptions:

* issue retrieval is planner-gated
* issue-driven relevance is not modeled as a separate explicit capability

## Current Core-Owned Routing Assumptions

The core currently hardcodes the routing model in several places.

### Planner-owned routing

`RetrievalPlan` currently declares:

* ordered channel names
* whether doc issues are enabled
* whether include-graph expansion is enabled
* whether reference collection is enabled

This means routing decisions already belong to the core, not to analyzers.

### Hardcoded channel registry

`_channel_registry()` in `context.py` maps string channel names directly to
retrieval functions.

This is the strongest current signal that a separate retrieval-facing contract
is needed: the core currently assumes producer identity by string literal.

### Hardcoded evidence-family mapping

`_channel_evidence_family()` currently maps channel names into merge families:

* `symbol` -> `lexical`
* `embedding` and `semantic` -> `semantic`
* `test` and `script` -> `task`

This means the core already has an implicit capability taxonomy, but it is
encoded as channel-name branching rather than explicit declarations.

For the first explicit producer-facing capability set, these implicit families
should be named by producer responsibility rather than by core scoring
internals:

* `symbol_lookup`
* `semantic_text`
* `embedding_similarity`
* `task_specialization`
* `graph_relations`
* `issue_annotations`
* `diagnostics_metadata`

This intentionally excludes core-owned aggregation concepts such as repeated
evidence bonuses or merge-family weighting.

## Current Ranking Contract

The merged ranking path currently assumes these normalized inputs:

* ranked per-channel results
* channel weights
* reciprocal-rank fusion
* cross-family evidence bonus
* role-based bias
* diversity caps by file, role, and language

This contract is real, but the producer side is still implicit.

## Current Explain Contract

Explain mode already exposes enough structure to support migration.

It currently renders:

* environment metadata
* planner choices
* enabled channels
* channel priority
* ordered channels
* top channel results
* merge diagnostics
* diversity diagnostics
* expansion diagnostics

The migration therefore does not need to invent diagnostics from scratch. It
needs to replace implicit producer/channel assumptions with explicit producer
and capability provenance.

## Gap Summary

The missing explicit contract today is not "how analyzers parse files". That
already exists through `LanguageAnalyzer`.

The missing contract is:

* which retrieval producer is emitting evidence
* which capability family that evidence belongs to
* which producer and capability versions govern the semantics
* whether the core is consuming native producer metadata or a compatibility layer
* which capabilities are unknown, unsupported, or intentionally ignored

## Consequence For Phase 2

The first new contract should therefore be layered beside `LanguageAnalyzer`
rather than replacing it.

That contract should be general enough to represent:

* analyzer-backed retrieval producers
* channel-backed producers
* future producers that are not analyzers at all

It should also be versioned separately from producer identity so the core can
negotiate capability semantics without overloading producer names.

The accepted implementation direction is:

* query-time producer metadata is shared and declarative
* the core consumes that declared metadata generically
* analyzers are not required to implement `RetrievalProducer` during the first
  migration path
* the core must not learn analyzer internals just to rank retrieval evidence
