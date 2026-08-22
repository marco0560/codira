# JSON Facets and Architecture Report Execution Ledger

## Objective

Deliver GitHub issues #70 and #54 together: extend the existing JSON analyzer
with conservative, composable semantic facets and bounded generic-manifest
facts, then render those facts through a complete, analyzer-independent
repository architecture report.

The implementation must preserve generic JSON syntax analysis. It must not
create a separate parser-level manifest format or infer domain semantics from
arbitrary JSON field names.

## Execution authority

- Approved by the operator on 2026-08-21.
- Branch: `feat/json-facets-architecture-report`.
- Base commit: `b520367`.
- Scope: GitHub issues #70 and #54 only.
- Merge policy: make auditable, atomic branch commits; squash merge only after
  every slice and the complete branch gate are green.
- The branch is not a RepoIRBench evaluation baseline. No Codira retrieval
  quality campaign runs before RepoIRBench Slice I10 freezes a Codira revision.
- A material design change, a new public stability promise, or a scope
  expansion beyond this ledger stops implementation for operator direction.

## Approved decision set

| Area | Approved decision |
| --- | --- |
| JSON admission | Claim existing known families and only unknown documents that satisfy conservative generic-manifest evidence. |
| JSON facts | Emit typed, bounded generic declaration artifacts; keep known-family declarations backward compatible. |
| Evidence | Deterministic weighted score with at least one structural signal; filename is supporting evidence only. |
| Report scope | Complete #54 in the same branch: model, DOT, optional SVG, Markdown, statistics, cycles, configured violations, hotspots, and agent-oriented summary. |
| Graph nodes | Module/file nodes with retained symbol evidence for every aggregate edge. |
| Layer rules | Ordered path-prefix layers and explicit forbidden source-to-destination rules. |
| SVG | DOT, Markdown, and JSON always exist; use optional Graphviz `dot -Tsvg` and record absence/failure deterministically. |
| JSON/report boundary | Report renderers consume the shared architecture model, never JSON-analyzer-specific rendering paths. |

## Fixed constraints

- Existing JSON Schema, npm package-manifest, and semantic-release extraction
  remain characterized and backward compatible.
- Unknown manifests may expose bounded structure but may not claim a known
  ecosystem absent an explicit recognizer.
- All generic facts have stable IDs, deterministic ordering, declared limits,
  and observable truncation diagnostics.
- Graph extraction treats unavailable resolution as missing evidence, not a
  negative architectural fact.
- Core does not acquire Graphviz as a dependency; subprocess commands are
  argument vectors.
- JSON analyzer semantic changes require an analyzer-version bump and fresh
  index behavior.

## Status vocabulary

- `pending`: no accepted implementation.
- `in_progress`: active implementation with no accepted commit.
- `validated`: focused and repository gates passed; commit pending.
- `complete`: atomic branch commit recorded and worktree clean.
- `blocked`: deterministic progress requires operator input.

## Slice ledger

### Slice 1 — JSON classification and conservative evidence

Status: `complete`

Scope:

- Replace exclusive family classification with a composable classification
  result containing facets, optional known ecosystem, ordered evidence, and a
  deterministic score.
- Preserve the existing schema, npm, and semantic-release recognizers.
- Add generic-manifest recognition requiring a structural signal plus
  corroborating evidence from schema URI, repository context, or meaningful
  path/URL/value structure.
- Keep lockfiles, VS Code JSONC/workspace inputs, arbitrary blobs, and
  filename-only candidates unclaimed.

Acceptance:

- Repeated classification produces identical facets, evidence order, and
  score.
- A document may carry multiple facets.
- Weak filename-only and arbitrary-configuration fixtures remain rejected.

Evidence:

- Focused tests: `87 passed` for JSON analyzer, contract, and installer-catalog
  coverage.
- Generated installer catalog: `uv run python
  scripts/generate_installer_catalog.py --check` passed after the JSON analyzer
  configuration schema changed.
- Codira index: `Indexed: 0`, `Reused: 341`, `Coverage issues: 0`.
- Codira audit: `No docstring issues found`.
- Repository validation: `uv run python scripts/validate_repo.py` exited 0;
  `776 passed, 1 skipped in 239.69s`; total coverage was 85%.

### Slice 2 — Bounded generic JSON facts and indexed availability

Status: `complete`

Scope:

- Add typed declaration artifacts for top-level keys, nested object paths,
  arrays, `$ref` values, and meaningful URL/path values.
- Define depth, entry, scalar-length, and total-fact limits with deterministic
  truncation diagnostics.
- Extend declaration kinds, capability mappings, configuration schema,
  semantic text, and persistence compatibility.
- Bump the JSON analyzer version and add re-index invalidation coverage.

Acceptance:

- Generic facts are queryable through existing persisted/indexed surfaces.
- Known manifest declarations and capability mappings remain intact.
- No generic field name is assigned a known ecosystem/domain meaning.

Evidence:

- Focused tests: `173 passed` for JSON analyzer, contracts, incremental
  indexing, capabilities, and installer-catalog coverage.
- Generated installer catalog: `uv run python
  scripts/generate_installer_catalog.py --check` passed after adding the
  generic-fact emission configuration.
- Codira index: `Indexed: 5`, `Reused: 336`, `Coverage issues: 0`.
- Codira audit: `No docstring issues found`.
- Repository validation: `uv run python scripts/validate_repo.py` exited 0;
  `780 passed, 1 skipped in 147.27s`; total coverage was 85%.

### Slice 3 — Architecture domain model and graph extraction

Status: `complete`

Scope:

- Introduce immutable architecture models for module inventory, aggregate
  dependencies, retained symbol evidence, SCCs/cycles, metrics, hotspots,
  violations, and analyzer facts.
- Aggregate imports, calls, and references into deterministic module/file
  edges.
- Include JSON facets and generic facts as analyzer-owned architecture inputs
  without report-rendering coupling.

Acceptance:

- The model is analyzer-independent and its serialized output is deterministic.
- JSON facts reach the model through ordinary indexed artifacts.

Evidence:

- Focused architecture-model tests: `3 passed`.
- Module inventory retains analyzer-owned JSON declaration facts without
  report-specific interpretation; aggregate dependencies retain sorted symbol
  evidence and exclude unresolved destinations.
- Atomic commit: `eb8557c feat: add deterministic architecture graph model`.

### Slice 4 — Layer policies, metrics, cycles, and hotspots

Status: `complete`

Scope:

- Add strict configuration for ordered path-prefix layers and explicit
  forbidden dependency rules.
- Implement deterministic fan-in/fan-out statistics, SCC/cycle detection,
  and transparent hotspot ranking based on reported metrics.
- Emit violations with rule ID, source, destination, edge kind, severity, and
  retained evidence.

Acceptance:

- Configuration validation rejects invalid/ambiguous rules deterministically.
- Tests cover ordering, overlap, allowed/forbidden edges, unlayered modules,
  cycles, and stable ranking ties.

Evidence:

- Focused architecture-model tests: `7 passed`.
- Ruff and targeted mypy checks passed for the architecture module and tests.
- Codira index: `Indexed: 3`, `Reused: 340`, `Coverage issues: 0`.
- Codira audit: `No docstring issues found`.
- Repository validation: `uv run python scripts/validate_repo.py` exited 0;
  `787 passed, 1 skipped in 203.34s`; total coverage was 85%.

### Slice 5 — CLI and architecture artifact renderers

Status: `complete`

Scope:

- Add `codira architecture-report` with default repository-local output and
  explicit `--output` routing.
- Render one common architecture model into `architecture.dot`,
  `architecture.md`, `dependencies.json`, `hotspots.json`, `violations.json`,
  and an artifact manifest.
- Render SVG through optional Graphviz; preserve all non-SVG artifacts and
  record a stable warning if `dot` is absent or fails.
- Include JSON facets/manifest facts in the Markdown and JSON inventory.

Acceptance:

- DOT, Markdown, and JSON replay byte-identically from one fixture index.
- SVG availability and absence are both tested paths.
- Renderers contain no JSON-analyzer-specific behavior.

Evidence:

- Focused CLI, extraction, and renderer tests: `11 passed`.
- Manual CLI smoke test produced the complete artifact set, including SVG when
  Graphviz was available.
- Atomic commit: `9c084d7 feat: render repository architecture reports`.

### Slice 6 — Documentation, integration characterization, and branch gate

Status: `complete`

Scope:

- Add an integration fixture with recognized schema/npm/release documents, a
  recognized project manifest, and weak decoys.
- Document the command, artifacts, optional Graphviz behavior, layer rules,
  JSON facets, evidence limits, and architectural limitations.
- Exercise SQLite and DuckDB where the architecture extraction depends on
  persisted query behavior.

Acceptance:

- JSON facts appear in structured and Markdown architecture outputs.
- Existing JSON behavior remains characterized.
- The complete validation gate below is green.

Evidence:

- Focused architecture, JSON analyzer, backend, bundle, contract, and MCP
  tests: `164 passed`.
- SQLite and DuckDB integration fixtures retain claimed JSON facts and a
  resolved Python import edge while excluding weak manifest decoys.
- `uv run codira index` reported `Indexed: 344`, `Coverage issues: 0`; two
  architecture-report replays had byte-identical required artifacts.
- `uv run codira audit` reported no docstring issues; strict MkDocs and the
  generated installer-catalog check passed.
- Repository validation: `uv run python scripts/validate_repo.py` exited 0;
  `794 passed, 1 skipped in 176.85s`; total coverage was 86%.

## Complete branch validation gate

For every completed slice, run focused tests appropriate to the changed
surface. Before squash merge, run all of the following with observed outcomes:

1. focused JSON analyzer, architecture-model, CLI, persistence, and renderer tests;
2. `uv run codira index` and a deterministic architecture-report replay;
3. `uv run codira audit`;
4. strict documentation build;
5. `uv run python scripts/validate_repo.py` as one standalone observed process;
6. generated-schema/configuration checks where changed;
7. diff and clean-worktree inspection.

Use `commit-block-generator` to prepare each branch commit and the final squash
commit. The final squash commit closes #70 and #54 with separate closing
footers.
