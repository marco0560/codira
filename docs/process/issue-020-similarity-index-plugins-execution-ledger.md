# Issue 20 Similarity-Index Plugins Execution Ledger

## Objective

Deliver GitHub issue #20 as a clean architectural break between authoritative
vector persistence and derived similarity indexing. Introduce an always
available exact similarity index in core and a selectable first-party FAISS
plugin supporting exact flat and HNSW indexes with operator-defined search
profiles.

Issue #59 is not an implementation or acceptance gate for this work. Issue #68
must be narrowed to issue #51, and Qdrant server mode must be specified as a
separate follow-up similarity-index plugin.

## Execution authority

- Approved by the operator on 2026-08-25.
- Approval-time branch: `main`.
- Approval-time base commit: `b8bab69`.
- Required implementation branch: `issue/20-similarity-index-plugins`.
- Scope: GitHub issue #20 and the directly required #68 and Qdrant roadmap
  alignment only.
- Merge policy: auditable atomic branch commits, followed by the repository's
  normal pull-request review and merge policy.
- Compatibility policy: intentional breaking change. Do not add staged
  deprecations, legacy adapters, compatibility aliases, automatic
  configuration translation, or persisted-state migrations.
- A material change to the decisions below, a new public stability promise, or
  scope expansion beyond this ledger stops implementation for operator
  direction.

## Approved decision set

| Area | Approved decision |
| --- | --- |
| Roadmap gate | Reframe #20 to ignore #59 and remove #20 from #68. |
| First packaged plugin | FAISS as `codira-similarity-index-faiss`. |
| Follow-up plugin | Qdrant server mode in a separate dependent issue. |
| Failure policy | Missing, disabled, stale, corrupt, or unreachable configured indexes fail explicitly; no silent fallback. |
| Distribution | Selectable installer component and optional official-bundle extra. |
| Architecture | Durable vector stores and similarity indexes are separate plugin families. |
| Availability | Core provides an always-available exact similarity index. |
| FAISS modes | Exact flat is the FAISS default; HNSW is explicitly selectable. |
| Search control | Operator-defined named profiles selected per query. |
| Profile fields | `ef_search`, `candidate_limit`, `default_result_limit`, and `max_result_limit`. |
| Result-limit policy | Explicit limits above the selected profile maximum fail; they are never clamped. |
| Compatibility | Replace old contracts and formats directly; do not deprecate or migrate them in stages. |
| Versioning | Bump the version of every modified distributable component and reconcile every coordinated pin and manifest. |

## Fixed constraints

- A vector store is the authoritative owner of vector sets, reusable vector
  caches, pending work, materialized vectors, stable-ID bindings, purge state,
  and vector-set revisions.
- A similarity index owns only rebuildable candidate-ranking artifacts and
  runtime search behavior.
- Structural backends remain authoritative for symbol and documentation
  resolution, filtering, and returned records.
- `VectorSetIdentity` continues to identify the embedding engine and durable
  vector store. Similarity-index identity is separate.
- FAISS artifacts are repository-local and derived from one durable vector-set
  revision.
- Different repository roots never share state, daemon caches, manifests, or
  FAISS artifacts.
- Build-time FAISS settings participate in persisted index identity. Runtime
  search profiles do not.
- HNSW is approximate and provides no exactness or recall guarantee.
- The implementation must not run or require the #59 retrieval-quality
  campaign.
- No modified distributable component may retain its pre-branch version.
  Packaged-data changes, including an installer catalog or bundle dependency
  change, count as component changes and require a version bump.

## Breaking-change policy

This work deliberately replaces the current semantic persistence/query
contract instead of preserving it through a transition layer.

Required breakpoints:

- remove `similarity_scores()` from the public `VectorStore` protocol and from
  first-party vector-store implementations;
- add the new snapshot/revision methods as mandatory `VectorStore` methods;
- introduce the mandatory configured `similarity_index` selection in a new
  configuration-contract version;
- reject configurations using the prior contract version instead of merging
  or translating them;
- reject legacy vector-store search settings such as
  `plugins.vector-store-sqlite.candidate_limit` as unknown configuration;
- expose no `legacy-vector-store` similarity-index adapter;
- bump first-party vector-store storage format versions and reject old
  persisted semantic stores;
- provide an explicit, root-scoped reset and full-reindex procedure instead of
  migrating old vector-store files or rows;
- require third-party plugins to implement the new contracts before they can
  load;
- bump the public core/plugin contract versions that describe the replaced
  interfaces;
- describe every break and required operator action in the changelog, release
  notes, configuration guide, and package documentation.

Old state must never be deleted automatically. When incompatible state is
detected, Codira must identify the repository-local paths, explain that a full
semantic rebuild is required, and require an explicit reset confirmation.

## Status vocabulary

- `pending`: no accepted implementation.
- `in_progress`: active implementation with no accepted commit.
- `validated`: focused and repository gates passed; commit pending.
- `complete`: atomic branch commit recorded and worktree clean.
- `blocked`: deterministic progress requires operator input.

## Slice ledger

### Slice 0 - Create and verify the implementation branch

Status: `complete`

Scope:

1. Verify that `main` is clean and record its full commit ID.
2. Bring `main` to the intended fast-forward base without rewriting local
   history.
3. Create `issue/20-similarity-index-plugins` before roadmap, documentation,
   contract, or implementation edits.
4. Verify that HEAD and every subsequent commit remain on that branch.
5. Record the actual branch base in this ledger if it differs from the
   approval-time base.

Reference command sequence:

```bash
git status --short
git switch main
git pull --ff-only
git switch -c issue/20-similarity-index-plugins
git branch --show-current
git rev-parse HEAD
```

Acceptance:

- `main` is synchronized at the recorded base and has no committed issue #20
  implementation change. Any pre-existing staged approval artifact is recorded
  and carried unchanged to the issue branch.
- The branch name is exactly `issue/20-similarity-index-plugins`.
- An existing branch is not reset, overwritten, or silently reused.
- No issue #20 implementation edit exists on `main`.

Evidence to record:

- branch name;
- full base commit;
- clean-worktree output.

Recorded evidence:

- Fetched `origin/main` on 2026-08-25; `main...origin/main` reported `0 0`.
- `main` and `origin/main` both resolved to
  `b8bab699d068b16ddd11a4f4e55e579069030383`.
- Before branch creation, the only staged change was this approved execution
  ledger. It was carried unchanged; no issue #20 implementation was committed
  on `main`.
- The branch `issue/20-similarity-index-plugins` was newly created at
  `b8bab699d068b16ddd11a4f4e55e579069030383`.
- The active branch after creation is
  `issue/20-similarity-index-plugins`.

### Slice 1 - Align the live roadmap

Status: `complete`

Scope:

- Rewrite #20 around the similarity-index family and first-party FAISS plugin.
- State explicitly that #59 is neither a dependency nor an acceptance gate.
- Remove #20 from #68 and narrow #68's title, body, dependencies, and
  acceptance criteria to #51.
- Remove #59 from #68 when it is not required by the remaining #51 scope.
- Add an owner comment to #20 recording the approved decisions in this ledger.
- Create a Qdrant follow-up issue for `codira-similarity-index-qdrant` in
  authenticated server mode only.
- Make the Qdrant issue depend on #20's contract and prohibit automatic local
  or exact fallback.
- Read back all remotely changed issues and refresh the repository roadmap
  snapshot with the native alias.

Acceptance:

- #20 has no #59 or #68 gate.
- #68 no longer claims #20 scope.
- The Qdrant work is discoverable but not included in this implementation.
- Live issue readback and the refreshed local snapshot agree.

Recorded evidence:

- On 2026-08-25, issue #20 was rewritten as
  `Feature: Similarity-index plugins and first-party FAISS backend` and its
  owner comment records the approved no-gate, strict-failure, profile,
  clean-break, and Qdrant decisions.
- Issue #68 was narrowed to
  `Chore: Define evidence gates for shared-repository deployment`; readback
  confirmed its body contains #51 but neither #20 nor #59.
- Created follow-up issue #71,
  `Feature: Qdrant server-mode similarity-index plugin`, with authenticated
  server mode only, #20 contract dependency, and no fallback.
- Refreshed the ignored local `issues.json` with `git gen-issues` and
  `milestones.json` with `git gen-miles`; both snapshots parsed successfully
  and reflect the live issue titles and scope.

### Slice 2 - Record ADR-031 and the clean-break boundary

Status: `complete`

Scope:

- Create `docs/adr/ADR-031-similarity-index-plugin-family.md`.
- Add ADR-031 to `docs/adr/index.md`.
- Mark ADR-022 as superseded in part without rewriting its historical
  rationale.
- Specify durable-store authority, derived-index identity, artifact freshness,
  fixed-root isolation, warm-daemon caching, strict failure, and the intentional
  compatibility break.
- Record why the exact implementation lives in core: FAISS remains optional,
  so a new valid installation must still have an explicitly selected
  similarity index.

Acceptance:

- The ADR contains no legacy adapter or staged migration path.
- The reset/reindex requirement for old semantic state is explicit.
- ADR links and the strict documentation build pass.

Recorded evidence:

- Added `docs/adr/ADR-031-similarity-index-plugin-family.md` and linked it from
  the ADR index.
- Added ADR-022's narrow partial-supersession note without rewriting its
  historical rationale.
- ADR-031 records durable-store authority, derived artifact identity/freshness,
  fixed-root daemon isolation, exact-core availability, strict failure, and the
  explicit reset-and-reindex compatibility break.
- `NO_MKDOCS_2_WARNING=1 uv run mkdocs build --strict` completed successfully
  on 2026-08-25 (with only the repository's pre-existing nav warnings).

### Slice 3 - Replace the core contracts

Status: `completed` (2026-08-25)

Scope:

- Narrow `VectorStore` to durable vector lifecycle responsibilities.
- Remove `similarity_scores()` immediately from the protocol.
- Add deterministic materialized-vector snapshots and vector-set revisions.
- Add typed contracts equivalent to `StoredVectorRow`,
  `VectorSnapshotMetadata`, and `VectorSnapshotRequest`.
- Add `SimilarityIndexSpec`, `SimilarityIndexIdentity`,
  `SimilaritySearchProfile`, and the `SimilarityIndex` protocol.
- Give `SimilarityIndex` explicit initialize, rebuild, search, purge, and
  runtime-cache-reset operations.
- Keep generic result-policy fields typed in core; keep FAISS-only values typed
  and validated by the FAISS plugin.

Required invariants:

- `candidate_limit >= max_result_limit`;
- `max_result_limit >= default_result_limit`;
- all limits are positive integers;
- profile names are non-empty and unique;
- an explicit result limit above the maximum is an error;
- build configuration participates in index identity;
- runtime profiles do not create new persisted index identities.

Acceptance:

- No production contract presents vector persistence and similarity search as
  one responsibility.
- Contract tests reject old vector-store implementations.
- There is no compatibility protocol or adapter for the old method set.

Execution evidence:

- `VectorStore` now owns only durable vector lifecycle operations; its public
  protocol has no similarity-search method.
- Typed ordered snapshots, source revisions, index identity/specification,
  search profiles, and the complete `SimilarityIndex` lifecycle are in core.
- `uv run pytest -q tests/test_contracts.py tests/test_similarity.py` passed.
- `uv run mypy src/codira/contracts.py src/codira/similarity.py
  tests/test_contracts.py tests/test_similarity.py` passed.

### Slice 4 - Add discovery, mandatory configuration, and exact search

Status: `completed` (2026-08-25)

Scope:

- Add `similarity-index` to the plugin-family literal and diagnostics.
- Add the `codira.similarity_indexes` entry-point group.
- Add active similarity-index discovery, configuration, caching, package
  hints, capabilities, and schema coverage.
- Bump the configuration contract version.
- Require `[embeddings].similarity_index` in configurations written for the new
  version.
- Set newly generated configurations to the core-owned `exact` index.
- Reject old configuration versions and legacy vector-store search keys.
- Implement the exact index in core using authoritative vector snapshots,
  exhaustive scoring, stable tie ordering, and revision-keyed runtime caches.

Acceptance:

- Fresh configuration always has an available exact index.
- Explicit FAISS selection never falls back to exact.
- Old configuration fails with a concrete regeneration/edit instruction.
- Plugin, capability, and configuration tests cover the new family.

Execution evidence:

- Core-owned `exact` is registered in `codira.similarity_indexes`; unavailable
  explicit `faiss` selection raises an install-hinted error and never falls
  back to exact.
- Configuration version 2 requires `embeddings.similarity_index`; version 1
  and retired vector-store candidate limits fail with concrete remediation.
- Capability schema is `1.10`; the SQLite and DuckDB vector-store packages are
  `1.56.0`, and the official bundle is `1.67.1`, with coordinated root/bundle
  pins and lockfile updates.
- `uv run pytest -q tests/test_plugins.py tests/test_config.py
  tests/test_contracts.py tests/test_capabilities.py tests/test_similarity.py
  packages/codira-vector-store-sqlite/tests
  packages/codira-vector-store-duckdb/tests` passed: 185 passed.
- `uv run python scripts/generate_installer_catalog.py --check` passed.
- `uv run python scripts/validate_repo.py` passed with observed exit 0:
  849 passed, 1 skipped.

### Slice 5 - Replace SQLite and DuckDB vector-store formats

Status: `completed` (2026-08-25)

Scope:

- Remove store-owned similarity methods from both first-party vector stores.
- Add mandatory deterministic snapshot iteration ordered by object type and
  stable ID.
- Add vector-set revision metadata and increment it transactionally when
  materialized membership or content changes.
- Update ordinary and full-index writes to publish coherent final revisions.
- Bump both vector-store format versions.
- Detect and reject the prior persisted formats.
- Do not alter, copy, translate, or migrate old vector-store rows.
- Add an explicit reset path that removes only confirmed repository-local
  semantic state and derived indexes, after which `index --full` recomputes
  vectors.

Acceptance:

- Old semantic state fails closed with paths and recovery instructions.
- No automatic destructive action occurs.
- Fresh SQLite and DuckDB stores expose equivalent snapshot/revision behavior.
- Package tests prove that no migration code path exists.

Execution evidence:

- SQLite format 4 and DuckDB format 2 expose ordered authoritative snapshots
  and transactional vector-set revisions; their previous formats fail closed
  with `codira emb reset --yes` followed by `codira index --full`.
- Store-owned similarity search was removed without a compatibility adapter.
- The SQLite and DuckDB vector-store distributions were bumped from 1.56.0 to
  1.57.0; root and official-bundle pins were updated. The generated installer
  catalog was refreshed and its distribution was bumped from 1.55.0 to 1.55.1;
  the official bundle was consequently bumped from 1.67.1 to 1.67.3.
- Package coverage is included in the 202 focused passing tests recorded for
  slices 5 through 7.

### Slice 6 - Route queries and warm daemons through SimilarityIndex

Status: `completed` (2026-08-25)

Scope:

- Replace direct vector-store similarity calls in semantic search.
- Resolve one named profile for each query.
- Use an explicit caller limit when it is within the profile maximum;
  otherwise use `default_result_limit`.
- Ask the active similarity index for `candidate_limit` candidates.
- Resolve and filter candidates through the structural backend.
- Emit at most the effective result limit.
- Add `--search-profile` and the equivalent MCP and daemon request field.
- Report effective index, mode, profile, search effort, limits, source revision,
  and artifact revision in structured diagnostics.
- Key warm caches by fixed root, vector-set identity, similarity-index
  identity, source revision, and object type.

Acceptance:

- Prefix/structural filtering occurs after candidate discovery.
- Values above `max_result_limit` fail rather than clamp.
- Profile switching does not rebuild or reload an unchanged index.
- Query, MCP, and daemon contracts contain no vector-store search path.

Execution evidence:

- Semantic search now reads one durable snapshot and delegates candidate
  ranking to the selected similarity index; structural resolution remains
  outside the index.
- Named profiles carry `ef_search`, candidate, default-result, and maximum
  result limits. CLI, MCP, and warm query-daemon requests accept the same
  `search_profile` field; oversize limits fail rather than clamp.
- Core exact warm caches remain bound to the fixed root, vector-set/index
  identity, snapshot revision, and object type.
- Capability schema is 1.11 and describes the profiled similarity-index query
  surface.

### Slice 7 - Add explicit rebuild and reset maintenance

Status: `completed` (2026-08-25)

Scope:

- Add `codira emb rebuild` to rebuild the configured derived index without
  recomputing embeddings.
- Add an explicitly confirmed semantic reset operation for incompatible old
  vector-store and similarity-index state.
- Reuse the repository maintenance lock.
- Build artifacts against source revision `R`, recheck `R`, and atomically
  publish only if the source remains unchanged.
- Preserve the previously published artifact when a rebuild fails, but treat it
  as stale if its revision no longer matches.

Strict query failures:

- missing artifact;
- corrupt artifact;
- artifact revision behind durable state;
- unavailable or disabled configured plugin;
- unsupported persisted format.

Acceptance:

- Every failure identifies a deterministic repair command.
- No repair silently switches index implementations.
- Reset is root-scoped, confirmed, and documented as unrecoverable except by
  reindexing or external backup.

Execution evidence:

- `codira emb rebuild` rebuilds snapshots for symbols and documentation while
  holding the repository index lock, then verifies their durable revisions.
- `codira emb reset --yes` removes only known root-local semantic-store files
  and runtime similarity caches; it never migrates or silently changes an
  index selection. Recovery is `codira index --full`.
- `uv run pytest -q tests/test_capabilities.py tests/test_call_graph.py
  tests/test_config.py tests/test_similarity.py tests/test_contracts.py
  tests/test_mcp_contract.py tests/test_query_daemon_contract.py
  packages/codira-vector-store-sqlite/tests
  packages/codira-vector-store-duckdb/tests` passed: 202 passed.

### Slice 8 - Implement codira-similarity-index-faiss

Status: `complete`

Scope:

- Create `packages/codira-similarity-index-faiss/` with typed implementation,
  package-local tests, README, `py.typed`, and the
  `codira.similarity_indexes` entry point.
- Resolve and lock a supported `faiss-cpu` version for the repository's Python
  support range.
- Support exact flat search as the package default.
- Support explicitly selected HNSW with typed `M` and `efConstruction` build
  settings.
- Validate operator-defined named profiles containing `ef_search`,
  `candidate_limit`, `default_result_limit`, and `max_result_limit`.
- Use FAISS per-query search-parameter objects so different profiles never
  mutate shared warm-index state.
- Keep separate symbol and documentation artifacts and deterministic label
  maps.
- Build under temporary names and publish the index, label map, and manifest
  atomically.

Build identity includes:

- index type;
- similarity metric;
- vector dimension;
- `M` and `efConstruction` for HNSW;
- FAISS package version;
- Codira FAISS format version.

Manifest data includes:

- vector-set and similarity-index identities;
- source vector revision;
- object counts;
- metric and dimensions;
- deterministic label-map checksum;
- implementation and format versions.

Initial update policy:

- rebuild the affected artifact coherently whenever vector membership or
  content changes;
- do not add HNSW tombstones, in-place deletion, or incremental compatibility
  machinery in this issue.

Acceptance:

- Exact FAISS results match the core exact implementation.
- HNSW search is characterized as approximate.
- Stable ties, corrupt artifacts, stale revisions, concurrent profiles, cache
  reset, and atomic publication are tested.

Execution evidence:

- Added the typed `codira-similarity-index-faiss` 1.68.0 package with its
  `py.typed` marker, README, `codira.similarity_indexes` entry point, and
  pinned `faiss-cpu==1.15.0` dependency.
- Flat inner-product/cosine ranking matches core exact ranking. HNSW uses the
  explicit `M` and `efConstruction` build settings and per-query FAISS HNSW
  parameter objects for profile `ef_search`; it never mutates the warmed HNSW
  index's shared `efSearch` value.
- Revisioned symbol and documentation artifacts contain an atomic current
  pointer, FAISS index, deterministic stable-ID label map, and checked
  manifest. Missing, corrupt, stale, mismatched, or cross-root artifacts fail
  with `codira emb rebuild`; a failed write preserves the old pointer.
- `rebuild_active_similarity_index` publishes both object types only after
  rechecking their durable revisions. Index mutation and embedding-only
  recomputation call it under the existing maintenance lock.
- Focused FAISS, lifecycle, registry, vector-store, MCP, daemon, installer,
  bundle, and inventory tests passed: `302 passed, 1 skipped in 45.37s`.
- Atomic commit recorded on `issue/20-similarity-index-plugins`.


### Slice 9 - Complete first-party distribution integration

Status: `complete`

Scope:

- Add the package to root dependencies and uv workspace sources.
- Update `packages/first_party_packages.json` with family
  `similarity-index`.
- Update coordinated package versions and `uv.lock`.
- Add a selectable installer component and regenerate the installer catalog.
- Add a `faiss` optional extra to the official bundle without adding FAISS to
  mandatory bundle dependencies.
- Inventory every distributable component changed by the branch and record its
  before/after version in this ledger before the slice is committed.
- Bump the core release target and every modified first-party distribution,
  including at minimum the SQLite vector store, DuckDB vector store, installer,
  official bundle, and new FAISS similarity-index package.
- Give the new FAISS package the coordinated initial release version selected
  for the issue rather than an unrelated placeholder version.
- Bump any additional first-party package whose production code or packaged
  data changes during implementation, even if it was not anticipated by this
  plan.
- Reconcile all exact dependency pins, root extras, uv sources, coordinated
  package metadata, release manifests, bundle assertions, installer catalog
  versions, and `uv.lock` after the version inventory is final.
- Update release, split-repository, artifact-build, isolated-install, and CI
  coverage.
- Extend registry, capability, installer, bundle, bootstrap, and package
  inventory tests.

Acceptance:

- Selecting FAISS installs every required dependency.
- New semantic installations without FAISS use explicitly configured core
  exact search.
- Configuring absent FAISS fails with an actionable package hint.
- No modified distribution reports its pre-branch version.
- Package metadata, runtime `__version__` values where present, dependency
  pins, generated catalog entries, bundle expectations, and the lock agree.
- Generated catalog checks and isolated wheel installation pass.

Version inventory for the branch (final intended release versions):

| Component | Before branch | After this issue | Reason |
| --- | --- | --- | --- |
| Core `codira` | `1.67.1` | `1.68.0` release target | Replaced public vector/similarity contracts and query lifecycle. |
| `codira-vector-store-sqlite` | `1.56.0` | `1.57.0` | Breaking durable snapshot/revision format. |
| `codira-vector-store-duckdb` | `1.56.0` | `1.57.0` | Breaking durable snapshot/revision format. |
| `codira-installer` | `1.55.0` | `1.55.2` | Generated catalog now exposes the selectable FAISS package and schema. |
| `codira-bundle-official` | `1.67.1` | `1.67.4` | Reconciled vector-store/installer pins and optional FAISS extra. |
| `codira-similarity-index-faiss` | new | `1.68.0` | Initial coordinated first-party similarity-index release. |
| First-party manifest/catalog coordination | `1.55.0` | `1.68.0` | Records the core release target used by installer plans. |

The FAISS distribution requires `codira>=1.68.0,<2.0.0`; it cannot resolve to
the older public core that lacks the new similarity-index contracts. The root
checkout keeps the plugin in the development group rather than defining a
self-referential optional extra; the published official bundle is the
user-facing optional-extra path.

Execution evidence:

- Added the package to the canonical first-party manifest, root development
  dependencies and workspace sources, generated installer catalog, bootstrap
  inventory, first-party factory coverage, and the official bundle's optional
  `faiss` extra. FAISS is not a mandatory bundle dependency.
- Installer plan coverage proves an explicit FAISS feature selection emits
  `codira-similarity-index-faiss==1.68.0`; its generated schema exposes
  `index_type`, `M`, and `efConstruction` for the configuration review.
- `uv lock --check` and `uv run python
  scripts/generate_installer_catalog.py --check` passed after final metadata
  reconciliation.
- A clean temporary environment installed the co-released local
  `codira-1.68.0` and `codira-similarity-index-faiss-1.68.0` wheels; the
  plugin factory imported with `faiss=1.15.0`.
- Atomic commit recorded on `issue/20-similarity-index-plugins`.

### Slice 10 - Documentation and operator journey

Status: `complete` (commit `2c997d0`)

Scope:

- Update `README.md`, configuration, plugin-model, storage, packaging, MCP,
  query-daemon, package, changelog, and release documentation.
- Document the breaking configuration and persisted-state reset requirements
  prominently.
- Cover installation, exact/HNSW selection, named profiles, rebuild, reset,
  querying, diagnostics, purging, and fixed-root daemon operation.
- Explain that `ef_search` controls graph exploration effort rather than score
  fuzziness.
- Explain candidate limit before structural filtering and result limit after
  filtering.
- State that profile changes do not rebuild an index, while `M` and
  `efConstruction` changes do.

Acceptance:

- A user can complete the new first-use journey without relying on old
  configuration or state.
- All breaking changes and recovery actions appear in both user-facing and
  release documentation.
- Strict MkDocs and documentation audit pass.

Execution evidence:

- Updated README, first-use, configuration, plugin, storage, packaging, MCP,
  query-daemon, package, changelog, and release documentation for exact and
  FAISS/HNSW similarity indexes.
- Documented configuration v2 as an intentional break, with explicit
  `config init --force`, `emb reset`, rebuild, reindex, and no-migration
  recovery actions.
- Documented named profiles, profile selection on `emb`, `docs`, and `ctx`,
  `ef_search` graph-exploration semantics, candidate-before-filter and
  result-after-filter limits, and HNSW build versus profile-only changes.
- Closed a coverage-audit parity gap: `ctx --search-profile` now reaches its
  embedding/documentation channels in both direct and warm-daemon execution.
- Focused lint, format, mypy, and query-daemon tests passed. Strict MkDocs,
  installer-catalog checks, refreshed `codira index`, and clean `codira audit`
  passed. `uv run --no-sync python scripts/validate_repo.py` completed with
  exit code 0 in an observed PTY run (275 files formatted, mypy clean, Semgrep
  0 findings, pytest suite passed).

### Slice 11 - Characterization and complete branch gate

Status: `complete` (2026-08-25)

Scope:

- Add a deterministic synthetic corpus for exact/HNSW characterization.
- Record exact top-k reference, HNSW recall@k, build time, cold/warm query
  latency, and artifact size.
- Treat these as non-gating implementation characteristics, not #59 quality
  thresholds.
- Build and install the FAISS wheel in an isolated environment.
- Exercise exact and HNSW indexes, multiple profiles, a stale artifact, reset,
  rebuild, and a warm query.

Focused validation:

```bash
uv run pytest -q tests/test_contracts.py tests/test_config.py tests/test_plugins.py
uv run pytest -q tests/test_capabilities.py tests/test_mcp_contract.py
uv run pytest -q tests/test_query_daemon_contract.py tests/test_query_daemon_ipc.py
uv run pytest -q packages/codira-vector-store-sqlite/tests
uv run pytest -q packages/codira-vector-store-duckdb/tests
uv run pytest -q packages/codira-similarity-index-faiss/tests
uv run pytest -q tests/test_installer_catalog.py tests/test_bootstrap_scripts.py
```

Repository validation:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
NO_MKDOCS_2_WARNING=1 uv run mkdocs build --strict
uv run python scripts/generate_installer_catalog.py --check
uv run python scripts/validate_repo.py
uv run codira index
uv run codira audit
```

The full repository gate must run alone in one PTY and be polled to an observed
exit. Repeat index and audit until there are no freshness, coverage, or
documentation findings.

Acceptance:

- Focused and full gates pass with observed exit codes.
- The isolated package smoke test passes.
- The worktree is clean after the final atomic commit.
- Issue #20 acceptance evidence is posted without claiming #59 completion.

Execution evidence:

- Added `scripts/characterize_similarity_indexes.py` and its deterministic
  synthetic corpus test. The runner records exact top-k reference, flat/HNSW
  recall@k, median build time, cold/warm median query latency, and artifact
  size without making those host-specific measurements a quality gate.
- Recorded the reproducible run and host context in
  `docs/process/issue-020-similarity-index-characterization-2026-08-25.md`.
  The 128-vector/16-query corpus observed flat and HNSW recall@10 of `1.0000`;
  those observations are explicitly non-guarantees.
- Enhanced `scripts/rehearse_release_installs.py`; an isolated `/tmp` wheel
  rehearsal built `codira-1.68.0` and
  `codira-similarity-index-faiss-1.68.0`, installed both outside the checkout,
  and verified installed-wheel exact, flat, HNSW, two profiles, stale failure,
  cache reset, rebuild, and warm reload behavior.
- The complete focused matrix listed in this slice passed, together with
  strict MkDocs and installer-catalog checks. A refreshed `codira index` had
  zero coverage issues and `codira audit` was clean. The observed PTY run of
  `uv run --no-sync python scripts/validate_repo.py` exited 0: 277 files were
  formatted, mypy was clean, Semgrep had 0 findings, and the full pytest suite
  passed.
- Posted and read back the final [issue #20 acceptance evidence](https://github.com/marco0560/codira/issues/20#issuecomment-5416660015), which explicitly records that the measurements are non-gating and #59 is outside this issue's scope.

## Commit sequence

Use one atomic, hook-validated commit for each coherent boundary:

1. roadmap snapshot and ADR;
2. core contracts, registry, mandatory configuration, and exact index;
3. SQLite and DuckDB breaking format and snapshot changes;
4. query, MCP, daemon, profile, rebuild, and reset surfaces;
5. FAISS package and package-local tests;
6. first-party inventory, bundle extra, installer, lock, release, and CI;
7. documentation, characterization, and final acceptance evidence.

Use `commit-block-generator` for every commit. Each commit body records the
root cause, breaking change, implementation, validation, and issue references.
Do not use subject-only commits.

## Completion criteria

Issue #20 is complete only when:

- all work exists on `issue/20-similarity-index-plugins`;
- the old configuration version is rejected;
- old vector-store formats are rejected and require explicit reset/reindex;
- `VectorStore` no longer exposes similarity search;
- the new similarity-index family is the only production query path;
- core exact search is always available for new valid configurations;
- FAISS flat and HNSW work from a clean installation;
- named profiles implement the approved default/maximum limit policy;
- warm concurrent queries safely use different profiles;
- unavailable, corrupt, or stale FAISS fails explicitly;
- purging and reset coordinate durable and derived state;
- installer and optional bundle-extra paths are tested;
- every modified distributable component has a verified version bump and all
  coordinated pins and generated metadata agree;
- Qdrant has a separate follow-up issue;
- #20 is not gated by #59 or #68;
- every slice and the complete branch gate carry observed validation evidence.

## Coverage audit (2026-08-25)

| Plan area | Status | Evidence / remaining work |
| --- | --- | --- |
| Slices 0-9 implementation | implemented | Branch commits `fd8d927` and `a36771e`; contracts, core exact, durable stores, profile routing, FAISS, bundle, installer, catalog, CI, and package tests are present. |
| Slice 10 operator journey | implemented | Commit `2c997d0`; documentation and `ctx --search-profile` direct/warm parity repair are recorded above. |
| Slice 11 characterization and branch gate | complete | Deterministic corpus/record, isolated-wheel rehearsal, final index/audit, and full gate are recorded above. |

The implementation and verification evidence cover every approved slice. The
branch has one atomic commit for Slice 10 and one for Slice 11; the latter also
records the final plan-wide gate evidence.

## Non-goals

- implementing Qdrant;
- completing or gating on #59;
- GPU FAISS;
- automatic HNSW tuning;
- raw per-query `efSearch` controls;
- incremental HNSW deletion or tombstone management;
- compatibility adapters for old vector-store plugins;
- staged configuration deprecation;
- automatic configuration or persisted-state migration.
