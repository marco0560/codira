# ADR-004 — Pluggable Backend and Analyzer Migration Plan

**Date:** 28/03/2026
**Status:** Accepted

## Context

`codira` currently has a strong implicit coupling between:

* Python-specific analysis
* SQLite-specific persistence and query execution
* CLI/query surfaces that directly depend on SQLite-oriented helpers

Open issues make the next architectural direction explicit:

* issue `#1` requires a cleaner persistence boundary for embeddings and their
  invalidation metadata
* issue `#2` requires pluggable language analyzers so multi-language
  repositories become a first-class target

The migration needs to preserve determinism and maintainability while
expanding architecture documentation, not just implementation code.

## Decision

Adopt a two-family plugin architecture and execute the migration on a dedicated
branch through a sequence of small, reviewable commits.

### Plugin Families

`codira` will distinguish two separate extension families:

* `IndexBackend`
  Exactly one storage/query backend is active for a given repository index.
* `LanguageAnalyzer`
  Multiple analyzers may be active in the same indexing run so one repository
  can be indexed across multiple languages and dialects.

This asymmetry is intentional:

* storage is an instance-level policy decision
* analyzers are repository-content capabilities

### Documentation and Tests Are First-Class

The migration is not code-only work.

Each architectural step must include, where applicable:

* tests that freeze or extend behavior
* architecture documentation updates
* ADRs for durable decisions that would otherwise be lost in commit history

The documentation scope must expand beyond README usage notes to include:

* architecture overviews
* pipeline documentation
* plugin model documentation
* backend/analyzer extension guidance
* ADRs that preserve and enforce decision history

## Rationale

One active backend per instance avoids a large class of unnecessary complexity:

* competing schema ownership
* inconsistent migration rules
* duplicate query semantics
* split incremental reuse logic
* ambiguous embedding persistence
* reduced determinism

Allowing multiple analyzers in one run is necessary for mixed-language
repositories and is aligned with the explicit goal of supporting them without
treating non-Python files as unsupported noise.

Treating tests and architecture documentation as first-class citizens reduces
the risk that the refactor drifts into undocumented framework churn.

## Consequences

### Positive

* clear separation between language analysis and persistence concerns
* explicit support for mixed-language repositories
* deterministic architectural boundaries for future backend and analyzer work
* durable design history through ADRs
* smaller and safer implementation increments

### Negative

* more upfront design and documentation work before user-visible feature
  expansion
* more commits and branch management overhead
* stronger discipline required to keep the execution ledger current

### Neutral / Trade-offs

* README updates should follow architecture stabilization, not lead it
* some migration phases may need more than one commit to keep changes atomic
* additional ADRs may be created as the migration reveals narrower decisions

## Migration Plan

The migration will proceed through the following phases.

### Phase 1 — Branch and Architecture Skeleton

Create a dedicated branch for this migration.

Add an architecture documentation skeleton covering:

* system overview
* indexing pipeline
* query pipeline
* plugin model
* storage backends
* language analyzers

Add an ADR template if one does not already exist.

### Phase 2 — Characterization Tests

Add or extend tests that freeze current behavior for:

* `index`
* `symbol`
* `calls`
* `refs`
* `embeddings`
* `ctx`
* incremental reuse
* embedding invalidation
* deterministic ordering

These tests are guardrails for the refactor, not optional cleanup.

### Phase 3 — Core Contracts and Normalized Artifacts

Introduce backend-neutral contracts and data structures for:

* `LanguageAnalyzer`
* `AnalysisResult`
* `IndexBackend`
* normalized index artifacts

Document the responsibilities and invariants of those contracts.

Create additional ADRs if symbol identity, artifact ownership, or extension
metadata boundaries require durable decisions.

### Phase 4 — SQLite Backend Encapsulation

Wrap the current SQLite implementation behind a concrete `SQLiteIndexBackend`
without changing observable CLI behavior.

Keep schema semantics stable during this phase.

Add backend contract tests that SQLite must satisfy.

### Phase 5 — Indexer Orchestration Refactor

Refactor `index_repo` into an orchestrator that:

* discovers files
* routes files to analyzers
* collects normalized artifacts
* delegates persistence to the selected backend

The orchestrator must stop depending directly on Python parser internals and
raw storage implementation details.

### Phase 6 — Python Analyzer Extraction

Extract the existing Python-specific logic into a `PythonAnalyzer`.

This includes:

* parsing
* symbol extraction
* call extraction
* callable-reference extraction
* import handling
* docstring audit integration

### Phase 7 — Query Abstraction

Refactor exact-query and embedding-query paths so they depend on backend
interfaces rather than raw SQLite access.

Preserve current CLI output contracts.

Add shared query contract tests where practical.

### Phase 8 — Registries and Configuration

Introduce registry and configuration mechanisms so:

* one backend is selected for the index
* multiple analyzers can be registered and activated by file routing

Document defaults, selection rules, and failure behavior.

Create an ADR if configuration semantics become materially architectural.

### Phase 9 — Second Analyzer Proof

Add one non-Python analyzer to validate the abstraction.

C is the preferred first candidate.

The first non-Python analyzer should prioritize:

* symbol extraction
* dependency extraction
* deterministic mixed-language indexing behavior

### Phase 10 — Final Documentation Consolidation

Expand and reconcile the documentation set so contributors can reconstruct the
architecture and the decisions behind it.

This phase should leave behind:

* stable architecture documents
* updated contributor guidance
* updated README references
* a complete ADR trail for the major choices made during the migration

## Post-Phase-10 Retrieval Quality Roadmap

The migration phases above establish the architecture boundary. The following
roadmap defines the preferred order for improving mixed-language retrieval
quality without weakening determinism.

### Phase 11 — C Analyzer Semantic Parity

Expand the C analyzer so it emits richer normalized artifacts.

This phase should prioritize:

* top-level call extraction
* struct, enum, typedef, macro, and global symbol extraction where
  deterministic
* normalized include artifacts with local versus system include classification
* header and source ownership hints
* nearby comment extraction for semantic text construction

This phase may record direct include edges, but the retrieval layer should not
yet depend on them as a first-class graph.

### Phase 12 — File-Role Classification

Introduce deterministic file-role classification for indexed files.

The initial role set should include:

* implementation
* header or interface
* test
* tooling or script

Prefer repository-structure and path-based rules before deeper heuristics.

### Phase 13 — Evidence-Based Ranking Fusion

Replace flat or near-flat channel merging with typed evidence fusion.

The evidence families should include:

* lexical symbol evidence
* semantic text evidence
* graph evidence
* file-role evidence
* language-coverage evidence

Scoring must remain deterministic and explainable.

### Phase 14 — Diversity-Aware Result Selection

Add deterministic diversification after raw ranking.

This phase should prevent one language, module family, or test bundle from
crowding out stronger implementation evidence.

### Phase 15 — Cross-Language Relationship Graph

Promote language-specific relationship artifacts into query-usable graph
structures.

For C, this phase explicitly includes a first-class include graph covering:

* direct include edges
* reverse include edges
* deterministic transitive include expansion
* header-to-source pairing where ownership is resolvable

This phase should also consider:

* test-to-implementation links
* tooling or configuration to implementation links
* generated-source provenance when present

`ctx` and explain surfaces should be able to show when include-graph
neighbors were used to expand or justify mixed-language results.

### Phase 16 — Language-Specific Semantic Text Units

Improve the semantic text indexed for each language family.

For C this should combine:

* signatures
* nearby comments
* include context
* header and source ownership context

For Python this should combine:

* docstrings
* assertions
* fixture or setup context
* symbolic ownership context

### Phase 17 — Intent-Aware Retrieval Planning

Add a deterministic query planner that assembles retrieval bundles by intent.

The initial intents should include:

* behavior or implementation
* test or validation
* configuration
* API surface
* architecture or navigation

The planner should use the lower-layer evidence and graph structures rather
than ad hoc string heuristics in the final rendering layer.

## Post-Phase-17 Plugin-Coverage and Rebuild Roadmap

The migration and retrieval-quality phases above establish the plugin
architecture, but they do not yet make plugin coverage complete at index time.

The following roadmap defines the next architectural steps required so
third-party analyzers can participate in discovery, repository coverage can be
audited deterministically, and the index can become stale when plugin
availability changes.

### Phase 18 — Analyzer-Declared Discovery Metadata

Replace hard-coded source-file discovery with analyzer-declared discovery
metadata.

This phase should:

* extend the analyzer contract so each analyzer declares the file suffixes or
  globs it owns
* make scanner discovery derive supported files from the active analyzer set
  rather than from a core-owned tuple such as `("*.py", "*.c", "*.h")`
* keep routing deterministic when multiple analyzers could plausibly accept
  the same path
* document the discovery contract for third-party analyzer authors

This phase should preserve current built-in behavior for Python and C while
removing the hard-coded discovery limitation that prevents future analyzers
from participating in indexing.

### Phase 19 — Canonical-Directory Coverage Audit

Add deterministic repository coverage auditing against tracked files in
canonical source directories.

The initial canonical directories should include:

* `src/`
* `tests/`
* `scripts/`

This phase should:

* inspect tracked files under those directories even when no currently
  installed analyzer claims them
* classify each relevant file as covered, optionally coverable, or uncovered
* report missing analyzer families for uncovered suffixes or globs
* make `codira index` surface this coverage state before or during indexing

The goal is for `codira` to say, deterministically, that a repository
appears to need analyzers for languages such as Rust, assembly, Lua, or Pascal
when tracked canonical-source files indicate that coverage is incomplete.

### Phase 20 — Persisted Plugin Inventory and File Ownership

Persist the plugin inventory used for one indexing run and record analyzer
ownership of indexed files.

This phase should add metadata for:

* active backend name and version
* active analyzer names and versions
* analyzer discovery metadata snapshot
* per-file analyzer ownership for indexed files
* whether the repository was fully covered at index time

This inventory becomes the durable source of truth for deciding whether an
existing index still matches the currently installed plugin set.

### Phase 21 — Plugin-Aware Staleness and Rebuild Policy

Make indexing detect when plugin availability changes the validity or
completeness of the current index.

This phase should handle at least:

* a new analyzer becoming available for previously uncovered files
* an analyzer version change that should reindex files it owns
* an analyzer being removed after it previously indexed files
* a backend or analyzer inventory mismatch between the database and the current
  process

The first implementation may conservatively force a broader rebuild, but the
policy must remain deterministic and explainable.

### Phase 22 — Coverage Commands, Policy Flags, and Documentation

Expose the new coverage model clearly through CLI and documentation.

This phase should include:

* a dedicated coverage inspection command or equivalent explain surface
* `index` behavior that can warn on incomplete coverage by default
* a strict mode such as `--require-full-coverage` that fails when canonical
  directories contain uncovered tracked files
* dedicated plugin-author and operator documentation describing:
  * analyzer discovery metadata
  * coverage semantics
  * plugin-aware rebuild triggers
  * the distinction between partial and full repository coverage

This phase should leave contributors and plugin authors with a direct route to
understand how plugin installation affects indexing completeness.

## Execution Rules

* Use a dedicated branch for the migration.
* Make multiple commits, with at least one commit per phase.
* Split large phases into smaller atomic commits when needed.
* Keep tests and documentation in-scope for every phase.
* Preserve deterministic behavior unless a later ADR explicitly changes it.

## Phase Ledger

Mark each phase as work lands.

* [x] Phase 1 — Branch and Architecture Skeleton
* [x] Phase 2 — Characterization Tests
* [x] Phase 3 — Core Contracts and Normalized Artifacts
* [x] Phase 4 — SQLite Backend Encapsulation
* [x] Phase 5 — Indexer Orchestration Refactor
* [x] Phase 6 — Python Analyzer Extraction
* [x] Phase 7 — Query Abstraction
* [x] Phase 8 — Registries and Configuration
* [x] Phase 9 — Second Analyzer Proof
* [x] Phase 10 — Final Documentation Consolidation
* [x] Phase 11 — C Analyzer Semantic Parity
* [x] Phase 12 — File-Role Classification
* [x] Phase 13 — Evidence-Based Ranking Fusion
* [x] Phase 14 — Diversity-Aware Result Selection
* [x] Phase 15 — Cross-Language Relationship Graph
* [x] Phase 16 — Language-Specific Semantic Text Units
* [x] Phase 17 — Intent-Aware Retrieval Planning
* [x] Phase 18 — Analyzer-Declared Discovery Metadata
* [x] Phase 19 — Canonical-Directory Coverage Audit
* [x] Phase 20 — Persisted Plugin Inventory and File Ownership
* [x] Phase 21 — Plugin-Aware Staleness and Rebuild Policy
* [x] Phase 22 — Coverage Commands, Policy Flags, and Documentation

## Notes

Expected follow-up ADR topics include:

* one active backend per repository instance
* multiple analyzers per indexing run
* C include-graph semantics and header-to-source ownership rules
* normalized artifact model and symbol identity
* embedding persistence and invalidation ownership
* query surfaces depending on backend contracts rather than backend internals

Phase 10 leaves the branch with:

* architecture pages updated to reflect the implemented registry, backend, and
  analyzer model
* contributor guidance reconciled with the architecture workflow
* README references updated to the current capability set

Phases 11 through 13 extend that baseline with:

* a tree-sitter-backed C analyzer with richer normalized call, declaration,
  include-kind, and semantic-text artifacts
* deterministic file-role classification used by retrieval and explain output
* explicit merge diagnostics for evidence families, reciprocal-rank fusion,
  merge-time role contribution, and final merged score

Phase 14 adds deterministic diversity selection across:

* per-file caps
* file-role caps
* mixed-language caps so one language family cannot monopolize the primary
  context block when another indexed language is also available

Phase 15 adds a first-class include-graph slice for C through:

* exact include-edge queries backed by persisted include artifacts
* deterministic direct and transitive local-include expansion in
  `ctx`
* explain-mode diagnostics showing when include-graph edges contributed to
  module expansion

Phase 16 completes language-specific semantic text units through:

* C embedding payloads that combine signatures, declaration comments, include
  context, and header-to-source pairing context
* Python callable embedding payloads that combine docstrings with module
  summaries, symbolic ownership, assertion presence, decorator names, and
  fixture or setup context

Phase 17 completes intent-aware retrieval planning through:

* deterministic primary intent families for behavior, test, configuration,
  API-surface, and architecture or navigation queries
* an explicit retrieval plan that owns channel routing and explain-mode
  diagnostics
* planner-driven gating for docstring issue enrichment, include-graph
  expansion, and reference collection while preserving earlier retrieval
  contracts

Phase 18 replaces hard-coded scanner discovery with analyzer-declared metadata
through:

* `LanguageAnalyzer.discovery_globs` as the stable discovery contract
* scanner discovery derived from active analyzer metadata for both Git-backed
  and filesystem-backed indexing
* third-party analyzer validation that rejects entry points missing discovery
  metadata

Phase 19 adds canonical-directory coverage auditing through:

* deterministic inspection of tracked files under `src/`, `tests/`, and
  `scripts/`
* uncovered-file reporting when no active analyzer claims a canonical file
* index summaries that surface partial repository coverage without yet making
  it fatal

Phase 20 persists plugin inventory and file ownership through:

* analyzer ownership columns on `files` rows
* backend runtime metadata stored in the database
* analyzer inventory rows carrying version and discovery-glob snapshots
* coverage-complete state recorded alongside the backend runtime snapshot

Phase 21 activates that persisted metadata in rebuild policy through:

* unchanged-file reindexing when analyzer ownership no longer matches
* automatic rebuilds when stored backend runtime inventory changes
* automatic rebuilds when stored analyzer inventory changes

Phase 22 completes the operator-facing surface through:

* a dedicated `codira cov` inspection command
* strict indexing preflight via `codira index --require-full-coverage`
* plugin and operator documentation describing partial versus full coverage

Phases 18 through 22 now provide the core indexing-side mechanics needed to
make the plugin model index-aware rather than only discovery-aware:

* analyzer-driven file discovery instead of hard-coded core suffixes
* deterministic repository coverage auditing for canonical source directories
* persisted plugin inventory and analyzer ownership metadata in the index
* CLI and documentation surfaces that distinguish partial from full coverage
