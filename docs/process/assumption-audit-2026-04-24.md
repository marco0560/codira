# Assumption Audit — 2026-04-24

## Repository Snapshot

- root: `C:/Users/marco/Documents/Programmazione/codira`
- HEAD: `534c7eef15fdd99dbc3278a06f6d6458bb1e30ad`
- git status at audit time: clean
- ADR location: `docs/adr/`
- config: `pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/*.yml`,
  `mkdocs.yml`, `package.json`
- entry point: `pyproject.toml`, `codira = "codira.cli:main"`
- tests: `tests/`, `packages/*/tests/`

Tracked tree focus:

```text
.github/workflows/{ci.yml,commit-message-check.yml,docs.yml,release.yml}
.githooks/{commit-msg,commit-msg.py,pre-commit,pre-push}
docs/adr/{ADR-001..ADR-014,ADR-016,index.md}
docs/architecture/* docs/process/* docs/release/*
packages/{codira-analyzer-bash,codira-analyzer-c,codira-analyzer-json,codira-analyzer-python,codira-backend-sqlite,codira-bundle-official}
scripts/*.py scripts/*.sh
src/codira/{cli.py,contracts.py,indexer.py,models.py,prefix.py,registry.py,schema.py,storage.py,...}
tests/{test_*.py,memory_backend.py}
```

## ADR Summary

| ADR | Status | Title | Evidence |
|---|---|---|---|
| ADR-001 | Accepted | Rank-based Multi-Channel Retrieval (RRF) | `docs/adr/ADR-001-rrf-multichannel.md:1-4` |
| ADR-002 | Accepted | Prefix-Scoped Query Filtering | `docs/adr/ADR-002-prefix-filtering.md:1-4` |
| ADR-003 | Accepted | JSON Output for Query Subcommands | `docs/adr/ADR-003-query-json-output.md:1-4` |
| ADR-004 | Accepted | Pluggable Backend and Analyzer Migration Plan | `docs/adr/ADR-004-pluggable-backends-migration-plan.md:1-4` |
| ADR-005 | Accepted | Real persisted embeddings with durable symbol identity | `docs/adr/ADR-005-real-persisted-embeddings-durable-symbol-identity.md:1-4` |
| ADR-006 | Accepted | Capability-driven signal layer | `docs/adr/ADR-006-capability-driven-signal-layer.md:1-4` |
| ADR-007 | Accepted | First-party package boundary | `docs/adr/ADR-007-first-party-package-boundary.md:1-4` |
| ADR-008 | Accepted | Batched embedding generation | `docs/adr/ADR-008-batched-embedding-generation-and-tunable-inference-runtime.md:1-4` |
| ADR-009 | Accepted | End-user distribution and publishing model | `docs/adr/ADR-009-end-user-distribution-and-publishing-model.md:1-4` |
| ADR-010 | Under review | Call-graph retrieval producer | `docs/adr/ADR-010-call-graph-retrieval-producer-and-user-surfaces.md:1-4` |
| ADR-011 | Accepted | Packaging and release migration sequence | `docs/adr/ADR-011-packaging-release-migration-sequence-v2-0-0.md:1-4` |
| ADR-012 | Accepted | Phase 2 package set | `docs/adr/ADR-012-phase-2-package-set-default-analyzers-backend.md:1-4` |
| ADR-013 | Accepted | Final multirepo repository set | `docs/adr/ADR-013-final-multirepo-repository-set-release-coordination-policy.md:1-4` |
| ADR-014 | Accepted | Canonical monorepo with generated distribution repositories | `docs/adr/ADR-014-canonical-monorepo-generated-distribution-repositories.md:1-4` |
| ADR-016 | Accepted | Richer symbol modeling | `docs/adr/ADR-016-richer-symbol-modeling-for-overload-metadata-and-named-declarations.md:1-4` |

## Explicit Assumptions

ADR-001:
  decision: RRF rank merge replaces cross-channel score comparison.
  assumptions:
    - Channels are independent retrieval mechanisms.
    - Cross-channel raw scores are not comparable.
  consequences:
    - Stable ranking and no score calibration.
  evidence:
    - `docs/adr/ADR-001-rrf-multichannel.md:21-25`
    - `docs/adr/ADR-001-rrf-multichannel.md:73-77`

ADR-002:
  decision: `--prefix` is permanent for supported read/query subcommands.
  assumptions:
    - Prefixes are repo-root-relative.
    - Filtering must be schema-backed and deterministic.
  consequences:
    - Uniform scoping across query surfaces.
  evidence:
    - `docs/adr/ADR-002-prefix-filtering.md:35-36`
    - `docs/adr/ADR-002-prefix-filtering.md:96-100`

ADR-003:
  decision: Add `--json` to exact/query subcommands.
  assumptions:
    - Agent/tool workflows require deterministic machine-readable output.
  consequences:
    - JSON composes with `--prefix`; no schema bump required.
  evidence:
    - `docs/adr/ADR-003-query-json-output.md:26-32`
    - `docs/adr/ADR-003-query-json-output.md:81-84`

ADR-004:
  decision: Two plugin families: analyzers and backends.
  assumptions:
    - Language analysis and persistence must be separated.
    - Migration must be incremental.
  consequences:
    - Mixed-language support and deterministic architectural boundaries.
  evidence:
    - `docs/adr/ADR-004-pluggable-backends-migration-plan.md:26-31`
    - `docs/adr/ADR-004-pluggable-backends-migration-plan.md:84-87`

ADR-005:
  decision: Real persisted embeddings plus analyzer-owned durable symbol identity.
  assumptions:
    - Embeddings are indexed artifacts.
    - Stable symbol identity is required for reuse.
  consequences:
    - Changed files can preserve unchanged symbol embeddings.
  evidence:
    - `docs/adr/ADR-005-real-persisted-embeddings-durable-symbol-identity.md:44-50`
    - `docs/adr/ADR-005-real-persisted-embeddings-durable-symbol-identity.md:119-123`

ADR-006:
  decision: Capability-driven signal layer between producers and core scoring.
  assumptions:
    - Producers declare capabilities.
    - Core remains final scoring authority.
  consequences:
    - New evidence families integrate without analyzer-name checks.
  evidence:
    - `docs/adr/ADR-006-capability-driven-signal-layer.md:64-69`
    - `docs/adr/ADR-006-capability-driven-signal-layer.md:162-166`

ADR-007:
  decision: Explicit first-party package topology.
  assumptions:
    - Core stays narrow.
    - Official optional analyzers move to package-owned distributions.
  consequences:
    - Optional analyzer support is validated through real package installs.
  evidence:
    - `docs/adr/ADR-007-first-party-package-boundary.md:36-42`
    - `docs/adr/ADR-007-first-party-package-boundary.md:104-108`

ADR-008:
  decision: Batched embeddings plus runtime tuning and benchmark helper.
  assumptions:
    - Embedding generation performance matters.
    - Batch order must preserve input order.
  consequences:
    - Duplicate payloads do not force duplicate model work.
  evidence:
    - `docs/adr/ADR-008-batched-embedding-generation-and-tunable-inference-runtime.md:33-39`
    - `docs/adr/ADR-008-batched-embedding-generation-and-tunable-inference-runtime.md:84-88`

ADR-009:
  decision: `codira-bundle-official` is primary end-user install target.
  assumptions:
    - End users should not need monorepo/package-extra knowledge.
  consequences:
    - Published bundle provides stable official capability surface.
  evidence:
    - `docs/adr/ADR-009-end-user-distribution-and-publishing-model.md:41-45`
    - `docs/adr/ADR-009-end-user-distribution-and-publishing-model.md:116-120`

ADR-010:
  decision: Call graph work is bounded relationship retrieval.
  assumptions:
    - It is not a generic repository-wide graph browser.
    - Limits/truncation are part of the contract.
  consequences:
    - UX expansion remains phased and scoped.
  evidence:
    - `docs/adr/ADR-010-call-graph-retrieval-producer-and-user-surfaces.md:29-33`
    - `docs/adr/ADR-010-call-graph-retrieval-producer-and-user-surfaces.md:78-81`

ADR-011:
  decision: Complete package phases before multirepo split and `v2.0.0`.
  assumptions:
    - Release validates final topology, not intermediate state.
  consequences:
    - Split risk separated from package-boundary work.
  evidence:
    - `docs/adr/ADR-011-packaging-release-migration-sequence-v2-0-0.md:41-47`
    - `docs/adr/ADR-011-packaging-release-migration-sequence-v2-0-0.md:116-120`

ADR-012:
  decision: Phase 2 package set owns default analyzers/backend.
  assumptions:
    - Core is platform package.
    - Python, JSON, C, Bash, SQLite have package ownership.
  consequences:
    - Package targets fixed before code moves.
  evidence:
    - `docs/adr/ADR-012-phase-2-package-set-default-analyzers-backend.md:36-42`
    - `docs/adr/ADR-012-phase-2-package-set-default-analyzers-backend.md:93-97`

ADR-013:
  decision: Final post-split repository set and release coordination policy.
  assumptions:
    - Initial publish is coordinated.
    - Package ownership aligns with repository ownership.
  consequences:
    - Fixed repository target and explicit bundle ownership.
  evidence:
    - `docs/adr/ADR-013-final-multirepo-repository-set-release-coordination-policy.md:41-47`
    - `docs/adr/ADR-013-final-multirepo-repository-set-release-coordination-policy.md:104-108`

ADR-014:
  decision: Main monorepo remains canonical source of truth.
  assumptions:
    - Split repos are generated distribution artifacts.
  consequences:
    - Export must stay deterministic; split repos are not architectural SOT.
  evidence:
    - `docs/adr/ADR-014-canonical-monorepo-generated-distribution-repositories.md:30-36`
    - `docs/adr/ADR-014-canonical-monorepo-generated-distribution-repositories.md:65-70`

ADR-016:
  decision: Two-tier symbol model: canonical symbols plus child declaration metadata.
  assumptions:
    - Runtime callables remain authoritative.
    - Overload metadata must not become default peer results.
  consequences:
    - Default CLI output remains stable while richer metadata is available.
  evidence:
    - `docs/adr/ADR-016-richer-symbol-modeling-for-overload-metadata-and-named-declarations.md:40-46`
    - `docs/adr/ADR-016-richer-symbol-modeling-for-overload-metadata-and-named-declarations.md:250-254`

## Implicit Assumptions

ENV-001:
  category: environment
  description: Runtime and first-party packages assume Python `>=3.13`; CI uses Python `3.13`.
  evidence:
    - `pyproject.toml:8`
    - `.github/workflows/ci.yml:26`
  confidence: high

ENV-002:
  category: environment
  description: CI validation assumes Ubuntu/Linux as the only CI OS.
  evidence:
    - `.github/workflows/ci.yml:15`
  confidence: high

TOOL-001:
  category: tooling
  description: CI requires pre-commit, black, ruff, mypy, pytest, and bash release audit.
  evidence:
    - `.github/workflows/ci.yml:48-65`
  confidence: high

TOOL-002:
  category: tooling
  description: Plugin discovery assumes entry-point groups `codira.analyzers` and `codira.backends`.
  evidence:
    - `src/codira/registry.py:33-34`
    - `packages/codira-backend-sqlite/pyproject.toml:23`
  confidence: high

WORKFLOW-001:
  category: workflow
  description: Read/query commands may auto-rebuild missing or stale indexes and write `.codira` state.
  evidence:
    - `src/codira/cli.py:2874-2875`
    - `src/codira/cli.py:3026-3210`
  confidence: high

WORKFLOW-002:
  category: workflow
  description: Target/output path precedence includes CLI flags, env vars, then current working directory.
  evidence:
    - `src/codira/path_resolution.py:1-6`
    - `src/codira/path_resolution.py:171-177`
  confidence: high

WORKFLOW-003:
  category: workflow
  description: First-party package set is version-pinned in the official bundle.
  evidence:
    - `pyproject.toml:18-24`
    - `packages/codira-bundle-official/pyproject.toml:13-17`
  confidence: high

DATA-001:
  category: data
  description: SQLite schema version and stable IDs are compatibility contracts.
  evidence:
    - `src/codira/schema.py:20`
    - `src/codira/schema.py:346`
  confidence: high

DATA-002:
  category: data
  description: Normalized analysis results require module, class, function, declaration, overload, and enum-member structures.
  evidence:
    - `src/codira/models.py:394-423`
    - `src/codira/models.py:461-475`
  confidence: high

DATA-003:
  category: data
  description: Canonical tracked files are audited for analyzer coverage.
  evidence:
    - `src/codira/indexer.py:410-422`
    - `src/codira/indexer.py:437-441`
  confidence: high

API-001:
  category: api
  description: Query JSON output has stable envelope fields and no-match status behavior.
  evidence:
    - `src/codira/cli.py:1018-1024`
    - `tests/test_prefix_filtering.py:639-643`
    - `tests/test_prefix_filtering.py:1090-1092`
  confidence: high

API-002:
  category: api
  description: Prefix filtering is repo-root-relative and prevents paths outside root.
  evidence:
    - `src/codira/prefix.py:24-31`
    - `src/codira/prefix.py:59-62`
    - `tests/test_prefix_filtering.py:1-6`
  confidence: high

API-003:
  category: api
  description: Analyzer/backend plugin APIs are structural protocols with required discovery and backend methods.
  evidence:
    - `src/codira/contracts.py:55-65`
    - `src/codira/contracts.py:82-95`
    - `src/codira/registry.py:50-77`
  confidence: high

PERF-001:
  category: performance
  description: Embedding backend assumes fixed local sentence-transformers model metadata and env-tunable batching/device/threading.
  evidence:
    - `src/codira/semantic/embeddings.py:64-71`
    - `src/codira/semantic/embeddings.py:448-453`
    - `tests/test_embeddings.py:160-161`
  confidence: high

PERF-002:
  category: performance
  description: Retrieval ranking assumes deterministic dedupe, provenance, graph enrichment, and diversity caps.
  evidence:
    - `tests/test_retrieval_merge.py:191-200`
    - `tests/test_retrieval_merge.py:555-556`
    - `tests/test_retrieval_merge.py:827-863`
  confidence: high

## Coverage Matrix

| Assumption | ADR coverage | Classification |
|---|---|---|
| ENV-001 | NONE | NOT_COVERED |
| ENV-002 | NONE | NOT_COVERED |
| TOOL-001 | ADR-011 | PARTIALLY_COVERED |
| TOOL-002 | ADR-004, ADR-007, ADR-012 | COVERED_BY_ADR |
| WORKFLOW-001 | NONE | NOT_COVERED |
| WORKFLOW-002 | NONE | NOT_COVERED |
| WORKFLOW-003 | ADR-009, ADR-012, ADR-014 | COVERED_BY_ADR |
| DATA-001 | ADR-005, ADR-016 | COVERED_BY_ADR |
| DATA-002 | ADR-016 | COVERED_BY_ADR |
| DATA-003 | ADR-004 | PARTIALLY_COVERED |
| API-001 | ADR-003 | COVERED_BY_ADR |
| API-002 | ADR-002 | COVERED_BY_ADR |
| API-003 | ADR-004, ADR-006 | COVERED_BY_ADR |
| PERF-001 | ADR-005, ADR-008 | PARTIALLY_COVERED |
| PERF-002 | ADR-001, ADR-006, ADR-010 | COVERED_BY_ADR |

## High-Risk Hidden Assumptions

ENV-001:
  risk: HIGH
  reason: Python `>=3.13` affects portability and installability.
  evidence: `pyproject.toml:8`, `.github/workflows/ci.yml:26`

ENV-002:
  risk: HIGH
  reason: Ubuntu-only CI leaves cross-platform behavior unvalidated.
  evidence: `.github/workflows/ci.yml:15`

WORKFLOW-001:
  risk: HIGH
  reason: Query/read commands can perform index mutation and expensive rebuilds.
  evidence: `src/codira/cli.py:2874-2875`, `src/codira/cli.py:3026-3210`

## Suggested ADR Candidates

- `Python Runtime Support Policy`
  - rationale: Document why `>=3.13` is required and whether older supported
    Python versions are intentionally excluded.
- `CI Platform Coverage Policy`
  - rationale: Decide whether Linux-only CI is sufficient or whether Windows
    and macOS are required portability contracts.
- `Index Freshness and Automatic Rebuild Policy`
  - rationale: Decide when read/query commands may mutate `.codira` state and
    how that interacts with manual indexing expectations.
