# Issue 71 Qdrant Similarity-Index Execution Ledger

## Objective

Deliver GitHub issue #71 as `codira-similarity-index-qdrant`: an authenticated,
server-mode, non-authoritative similarity-index plugin. Qdrant collections are
rebuildable candidate-ranking artifacts; vector stores remain the authoritative
owner of durable embedding vectors, vector-set identity, and revisions.

## Execution authority

- Approved by the operator on 2026-08-26.
- Required implementation branch: `issue/71-qdrant-similarity-index`.
- Approval-time target branch: `main`.
- Recorded implementation base:
  `ee749ab4a03c307aaf0c5e5469cabb41f00b579a`.
- Scope: issue #71, its required Codira 2.0 compatibility boundary, and the
  documentation, installer, bundle, tests, release metadata, and lifecycle
  work directly required by that issue.
- Merge policy: atomic branch commits followed by `$git-merge-squash` onto
  `main`. The final commit block must close #71 only after all acceptance
  criteria are verified.
- A material scope or decision change stops implementation for operator
  direction.

## Approved decision set

| Area | Approved decision |
| --- | --- |
| Transport | REST or gRPC, with REST as the default. |
| Credentials | `api_key_env` has precedence when non-empty; otherwise use `api_key_file`. Both configuration keys may exist. |
| Repository identity | Persistent repository UUID plus mandatory namespace. |
| Publication | Plugin-owned immutable revision collections and atomic alias publication. |
| Retention | Retain current and immediately previous revisions. |
| Consistency | Configurable write/read consistency; default medium writes and quorum reads. |
| Remote cleanup | Explicit previewable remote purge and an explicit remote-orphan override for reset recovery. |
| Provenance | Breaking typed `SimilaritySearchResult` envelope preserving query and candidate provenance. |
| Collection settings | Bounded HNSW build settings; cluster topology remains a server concern. |
| Tests | Deterministic fake-client tests only; no live-Qdrant interoperability claim. |
| Distribution | Qdrant plugin is a default `codira-bundle-official` dependency. |
| Versioning | Coordinated 2.0 compatibility boundary for all affected distributions. |

## Fixed safety constraints

- Support authenticated remote Qdrant server mode only.
- Reject embedded, local-path, `:memory:`, anonymous, and unauthenticated
  configurations.
- Do not silently fall back to core exact, FAISS, or any other index when
  Qdrant is selected.
- Bind collections and queries to repository identity, vector-set identity,
  selected similarity-index configuration, object type, and source revision.
- Never store or render API keys, raw credential contents, authorization
  headers, or credential-bearing errors in configuration fingerprints,
  provenance, installer plans, journals, logs, or output schemas.
- Never treat Qdrant points or payloads as authoritative repository records.
- Never delete a remote collection without exact local and remote ownership
  evidence.
- Preserve the repository UUID across `codira emb reset`.

## Status vocabulary

- `pending`: no accepted implementation.
- `in_progress`: active implementation with no accepted commit.
- `validated`: focused and repository gates passed; commit pending.
- `complete`: atomic branch commit recorded and worktree clean.
- `blocked`: deterministic progress requires operator input.

## Detailed implementation plan

### Phase 0 - Branch and execution record

Status: `complete`

- Create the dedicated branch from a clean, synchronized `main` base.
- Create this ledger before implementation changes.
- Record the approved decision set, exact base, slice evidence, risks, and
  fake-client-only test limitation.
- Keep one atomic commit for the baseline and one for its validation evidence.

### Phase 1 - Architecture and safety contract

Status: `complete`

- Add ADR-032 for authenticated Qdrant server-mode similarity indexing.
- Reaffirm that vector stores own durable vectors, vector-set identity, and
  revisions; Qdrant owns only disposable candidate-ranking artifacts.
- Reaffirm that structural backends own repository-record resolution,
  filtering, and final results.
- Support authenticated remote Qdrant server mode only.
- Reject local paths, embedded mode, `:memory:`, anonymous connections, and
  unauthenticated configurations.
- Define strict no-fallback and credential-redaction behavior.
- Define a collision-resistant root identity using a persistent repository UUID,
  mandatory namespace, canonical-root hash, vector identity, index identity,
  object type, and source revision.
- Require all collection names and provenance to expose hashes rather than raw
  repository paths, model names, credentials, or endpoint URLs.
- Index ADR-032 in `docs/adr/index.md` and validate it against ADR-021,
  ADR-025, ADR-026, and ADR-031.

### Phase 2 - Similarity contract v2

Status: `complete`

- Replace `list[VectorSimilarityScore]` from `SimilarityIndex.search()` with
  a typed `SimilaritySearchResult`.
- Define typed candidate records containing stable ID, score, and
  credential-free native candidate provenance.
- Define typed query provenance containing plugin name/version, object type,
  source revision, profile name, candidate limit, artifact or collection hash,
  and transport.
- Preserve Qdrant-native point ID, physical collection identity, resolved
  alias identity, and source revision as candidate provenance.
- Prohibit raw URLs, namespace text, credential-source paths, API keys,
  headers, and server exception payloads in all provenance.
- Introduce typed similarity-index errors for unavailable, authentication
  failure, stale, incompatible, unsafe ownership, publication failure, and
  cleanup failure.
- Replace the purge interface with typed request/result objects that support
  preview and confirmed execution.
- Bump contract, query JSON, daemon IPC, MCP, and capabilities schema versions
  wherever the new result or provenance shape is exposed.
- Add protocol conformance tests for result envelopes, provenance, failures,
  and purge results; reject malformed or credential-bearing provenance.

### Phase 3 - Migrate core exact and FAISS implementations

Status: `complete`

- Update `ExactSimilarityIndex` to return `SimilaritySearchResult` and retain
  deterministic core provenance without fabricating native identifiers.
- Update `FaissSimilarityIndex` to return the new envelope and preserve label
  and native-position provenance where available.
- Update FAISS purge to consume and return the new typed lifecycle contracts.
- Preserve exact/FAISS ranking, candidate limits, stale detection, cache
  semantics, and strict selected-plugin failure behavior.
- Update every core caller to retain provenance until final result assembly
  instead of flattening it during structural resolution.
- Carry a credential-free provenance sidecar through filtering, result limits,
  JSON, and explain surfaces.
- Add regression coverage proving result ordering remains unchanged and
  candidate provenance stays aligned after structural filtering.

### Phase 4 - Qdrant package foundation

Status: `complete`

- Create `packages/codira-similarity-index-qdrant` with `pyproject.toml`,
  `README.md`, `py.typed`, typed implementation modules, and package tests.
- Register `qdrant` in the `codira.similarity_indexes` entry-point group.
- Pin a verified `qdrant-client` version compatible with Python 3.13.
- Keep Qdrant-client imports inside the plugin distribution.
- Introduce an injectable internal client protocol/factory so deterministic
  tests never need a running Qdrant server.
- Provide a strict plugin schema for:
  - `url`;
  - `transport` (`rest` or `grpc`);
  - optional `grpc_port`;
  - `api_key_env` and `api_key_file`;
  - mandatory `namespace`;
  - `timeout_seconds`;
  - `write_ordering` and `read_consistency`;
  - `hnsw_m`, `hnsw_ef_construct`, `on_disk`, and bounded
    `upload_batch_size`.
- Fix vector distance to cosine and reject unsupported keys before network
  access.
- Test discovery, configuration-schema publication, invalid URLs/transports,
  consistency values, namespaces, HNSW values, batch sizes, and accidental
  default selection.

### Phase 5 - Credentials and client initialization

Status: `complete`

- Resolve a non-empty `api_key_env` value first.
- Fall back to `api_key_file` only when the named environment variable is
  absent or empty.
- Require at least one usable credential source.
- Require a credential file to be a readable regular file; reject unsafe
  symlinks and group/world-readable POSIX permissions.
- Strip only terminal line endings from file credentials.
- Exclude credential values and source paths from fingerprints, capabilities,
  errors, installer plans, daemon metadata, journals, and logs.
- Construct `QdrantClient` with normalized remote URL, resolved API key,
  bounded timeout, compatibility checking, REST default, and `prefer_grpc`
  when gRPC is selected.
- Probe server information during initialization and map connectivity and
  authentication failures to typed credential-free Codira errors.
- Cache clients only in existing command-scoped fixed-root plugin instances;
  discard them from `reset_runtime_caches()`.
- Test environment precedence, empty/missing fallback, invalid credential
  sources, redacted errors, and REST/gRPC construction arguments through the
  fake factory.

### Phase 6 - Remote identity and collection naming

Status: `complete`

- Generate `.codira/qdrant-repository-id` atomically before computing remote
  identity and preserve it across semantic reset.
- Exclude credentials and transport from persisted collection identity.
- Include endpoint hash, namespace hash, repository UUID, canonical-root hash,
  vector-set identity, plugin format, HNSW build settings, and object type in
  the collection identity.
- Derive one stable alias per build identity/object type and one immutable
  physical collection name per source revision.
- Use deterministic UUID point IDs from repository UUID, object type, and
  stable ID.
- Store stable ID and identity/revision hashes in candidate point payloads.
- Reserve a deterministic manifest point containing credential-free ownership
  and freshness metadata, and filter it from all candidate queries.
- Keep a credential-free local ownership ledger under
  `.codira/similarity-indexes/qdrant`; treat it only as cleanup evidence, not
  as proof of current remote state.
- Test that repository UUID, namespace, vector store, embedding engine,
  dimension, build parameters, object type, and revision cannot collide; also
  test Qdrant name constraints and absence of raw paths/names from remote IDs.

### Phase 7 - Atomic rebuild and retention

Status: `complete`

- For each symbol and documentation snapshot, create an immutable revision
  collection with cosine vectors and approved HNSW settings.
- Upsert the manifest and vector points in bounded batches with `wait=True`
  and configured write ordering.
- Verify completion, readiness, dimension, distance, point count, manifest
  identity, and source revision before publication.
- Preserve the current alias until every verification succeeds.
- Replace aliases atomically in one alias-update operation.
- Update the local ownership ledger atomically after publication.
- Retain only the current and immediately previous physical collection.
- Delete older collections only after successful publication and only when both
  local and remote ownership metadata prove exact ownership.
- On pre-publication failure, retain the old alias and remove incomplete owned
  state only when safe.
- On post-publication retention failure, report successful publication and
  incomplete cleanup separately, retaining evidence for later purge.
- Test first publication, replacement, each pre-publication failure mode,
  retention bounds, foreign-collection protection, cleanup failure, and source
  revision changes during rebuild.

### Phase 8 - Qdrant search

Status: `complete`

- Resolve a stable alias to its concrete physical collection before querying,
  avoiding an alias verification/query race.
- Verify manifest repository identity, namespace, canonical root, vector-set
  identity, plugin build identity, object type, and source revision.
- Reject missing aliases, foreign collections, stale revisions, incompatible
  dimensions, and corrupt manifests.
- Map profile `ef_search` to Qdrant `SearchParams.hnsw_ef`.
- Map `candidate_limit` to the Qdrant query limit and `min_score` to score
  threshold.
- Map configured read consistency to `query_points`.
- Filter for vector records only and convert returned points to typed candidates
  with native point provenance.
- Re-sort returned candidates by descending score and stable ID, and never
  return more than `candidate_limit` candidates.
- Never retrieve durable vectors from Qdrant or treat payloads as authoritative
  repository records.
- Test profile mapping, candidate bounds, deterministic ties, manifest-point
  exclusion, all stale/missing/authentication/unavailability failures, and
  strict absence of exact or FAISS fallback.

### Phase 9 - Remote purge and reset

Status: `complete`

- Add `codira emb similarity-purge` as an explicit remote derived-index cleanup
  surface.
- Default it to a dry-run inventory and require `--yes` for remote deletion.
- Return typed alias/collection inventory, current/previous state, deletable
  owned revisions, and skipped foreign or ambiguous state.
- Invoke remote purge only for exact ownership matches.
- Update `codira emb reset --yes` to attempt Qdrant purge before deleting the
  local ownership ledger.
- Abort reset when remote purge fails unless the operator adds
  `--allow-remote-orphans`.
- When that override is used, report exact credential-free hashes for remote
  state that may remain.
- Preserve existing local reset recovery where no remote ownership record is
  present, including unavailable local-plugin recovery.
- Route purge/reset through the repository index lock.
- Test preview non-mutation, confirmed owned-state deletion, authentication and
  availability failures, default reset blocking, orphan override, and unchanged
  FAISS/local reset behavior.

### Phase 10 - Daemon, MCP, and provenance surfaces

Status: `complete`

- Carry `SimilaritySearchResult` through direct CLI, warm query daemon, and
  MCP paths.
- Preserve startup-root isolation in the daemon and include repository UUID and
  artifact revision in relevant cache identity.
- Keep profile changes per-query; do not mutate shared Qdrant client/index
  state.
- Support daemon credentials through environment or the configured private file.
- Expose credential-free Qdrant provenance through `emb --json`, `docs`
  JSON/explain, `ctx` JSON/explain, daemon responses, and MCP envelopes where
  similarity provenance is present.
- Update output schemas and capability declarations.
- Test direct/daemon equivalence, multi-root isolation, unchanged MCP fixed-root
  enforcement, and every updated schema.

### Phase 11 - Registry, installer, and official bundle

Status: `complete`

- Add Qdrant to `packages/first_party_packages.json` and first-party discovery
  and capability tests.
- Add configuration metadata without valid credential defaults.
- Regenerate and check the installer catalog.
- Keep Qdrant selectable for standalone/core-focused installation plans.
- Add `codira-similarity-index-qdrant` as a default
  `codira-bundle-official` dependency while leaving core exact as the default
  selected index.
- Keep installer plans and journals credential-free.
- Extend isolated release-install rehearsal to import and instantiate Qdrant
  using the fake client factory.
- Validate catalog generation, bundle pin/order, credential-free installer
  plans, and isolated entry-point discovery.

### Phase 12 - Coordinated 2.0 version alignment

Status: `complete`

- Establish a coordinated `2.0.0` compatibility boundary.
- Update core contract/schema compatibility versions.
- Release the new Qdrant package as `2.0.0`.
- Release FAISS as `2.0.0` because it implements the broken protocol.
- Audit every first-party `codira<2` dependency constraint and update affected
  packages to `codira>=2.0.0,<3.0.0`.
- Bump every modified first-party distribution, including installer and bundle,
  to `2.0.0`.
- Align first-party inventory, root extras, package pins, release tooling,
  installer catalog metadata, and `uv.lock`.
- Add changelog/release documentation covering the result envelope, purge
  contract, JSON/provenance schema changes, default bundle dependency, and
  reset/rebuild requirements.
- Validate dependency range consistency, package version/bundle pins, and lock
  consistency; ensure no affected package retains an incompatible `<2` bound.

### Phase 13 - User documentation

Status: `complete`

- Update `README.md` first-party plugin inventory first.
- Document the complete Qdrant first-use journey: installation, authenticated
  server prerequisites, namespace, environment/file credentials, REST/gRPC,
  HNSW build settings, profiles, rebuild, query, daemon, purge, and reset.
- Document environment-to-file credential fallback precisely.
- Recommend private credential files for installed query-daemon services.
- Explain immutable collections, aliases, two-revision retention, ownership
  hashes, derived-state ownership, strict failure, and no fallback.
- Explain `--allow-remote-orphans` as an explicit recovery escape hatch.
- Update architecture, storage, packaging, configuration, MCP, installer,
  release, and troubleshooting documentation.
- State that fake-client testing proves only the Codira/client boundary; it
  does not establish live Qdrant interoperability, recall, latency, or
  scalability claims.
- Build documentation strictly and run link/generated-document checks and
  Codira audit to zero findings.

### Phase 14 - Test and quality gate

Status: `complete`

- Run focused Qdrant package tests.
- Run core similarity contract, exact, FAISS, lifecycle, configuration,
  registry, capabilities, CLI, daemon, MCP, installer, bundle, and schema
  tests.
- Run Ruff and formatting checks; if the first Ruff check fails, retry in fix
  mode and report any remaining error.
- Run strict mypy for core and every changed package.
- Run generated catalog checks and isolated wheel rehearsal with fake-client
  injection.
- Refresh the Codira index and run `codira audit` until no findings remain.
- Run `uv run python scripts/validate_repo.py` alone in one PTY and record its
  observed final exit code, summary, and complete failures.
- Record every command, exit code, test summary, and exception in this ledger.
- Require zero Codira coverage issues and zero undocumented Ruff suppressions.

### Phase 15 - Atomic delivery

Status: `pending`

- Keep each coherent implementation slice in an atomic commit with tests,
  documentation, and ledger evidence.
- Use `$commit-block-generator` for each commit.
- After all acceptance criteria pass, use `$git-merge-squash` to squash the
  implementation branch onto `main`.
- Size the final commit block from the source-branch commit count.
- End the final commit block with `Closes: #71`.
- Publish with `git rel` when available; otherwise use the repository's
  documented push command.
- Read back `main`, `origin/main`, ancestry, and issue state.

## Completion acceptance criteria

- Qdrant supports authenticated remote server mode only.
- REST and gRPC are configurable; REST is the default.
- A non-empty environment credential takes precedence, with file fallback for
  missing/empty values.
- Repository UUID plus namespace prevents cross-root collection reuse.
- Rebuilds use immutable collections and atomic aliases.
- Exactly current plus previous revisions are retained.
- Consistency is configurable with medium/quorum defaults.
- Remote purge is previewable, ownership-safe, and explicit.
- Reset cannot silently orphan remote state.
- `SimilaritySearchResult` preserves typed query and candidate provenance.
- Qdrant uses bounded HNSW settings and profile-scoped `hnsw_ef`.
- Selection failures never fall back.
- The official bundle installs Qdrant by default without selecting it.
- Every affected distribution is aligned to the 2.0 compatibility boundary.
- Fake-client coverage is complete, while live-server interoperability remains
  an explicitly unverified limitation.
- Documentation, installer, schemas, release rehearsal, and repository
  validation pass before #71 is closed.

## Slice ledger

### Slice 0 - Create and verify the implementation branch and ledger

Status: `complete`

Scope:

1. Verify a clean local worktree.
2. Verify `main` and `origin/main` resolve to the same commit.
3. Create the exact approved implementation branch without rewriting another
   branch.
4. Record the branch base, the approved decision set, safety constraints, and
   fake-client-only testing limit.
5. Refresh the Codira index after this tracked documentation edit and audit it.

Acceptance:

- `issue/71-qdrant-similarity-index` exists and is checked out.
- Its parent/base is the recorded `main` commit.
- No issue #71 implementation change exists on `main` before branch creation.
- The ledger is the current source of truth for approved decisions and slice
  evidence.

Recorded evidence:

- Before branch creation, `git status --short` was empty.
- `main`, `origin/main`, and `HEAD` all resolved to
  `ee749ab4a03c307aaf0c5e5469cabb41f00b579a`.
- No pre-existing `issue/71-qdrant-similarity-index` branch was listed.
- Created and checked out `issue/71-qdrant-similarity-index` at the recorded
  base.
- The prior Codira index generation was complete but identified commit
  `b289ceda3f9ea5560a077016959d88a55cba36df`; it is intentionally refreshed
  after this documentation edit rather than used as evidence for new changes.
- `git diff --check` completed with no whitespace errors.
- `uv run --no-sync codira index` completed with one indexed file, 383 reused
  files, zero failures, and zero coverage issues.
- `uv run --no-sync codira audit` completed with no docstring issues.

### Slice 1 - Record Qdrant server-mode architecture and contract v2

Status: `complete`

Scope:

1. Add ADR-032 and index it in the ADR index.
2. Record authenticated-server-only Qdrant ownership, strict no-fallback, and
   credential-redaction rules.
3. Define the repository UUID, namespace, opaque remote-identity, publication,
   retention, lock, and fixed-root daemon boundaries.
4. Validate its relationship to ADR-021, ADR-025, ADR-026, and ADR-031.

Acceptance:

- ADR-032 states that vector stores remain authoritative for durable vectors,
  vector-set identity, and revisions, and that structural backends own final
  record resolution and filtering.
- It rejects local, embedded, anonymous, and unauthenticated Qdrant modes and
  forbids all selected-plugin fallback.
- Its remote identity requires persistent repository UUID, namespace,
  canonical-root hash, vector/index identity, object type, and source revision
  while exposing only opaque hashes in names and provenance.
- It preserves ADR-021 configuration validation, ADR-025 mutation locking,
  ADR-026 fixed-root daemon isolation, and ADR-031 similarity-index ownership.

Recorded evidence:

- Added `docs/adr/ADR-032-authenticated-qdrant-server-similarity-index.md` and
  linked it from `docs/adr/index.md`.
- ADR-032 records authenticated remote REST-by-default/gRPC-by-explicit-choice
  server mode, strict selection failure, credential redaction, opaque
  repository-scoped identity, immutable alias publication, two-revision
  retention, ownership-safe cleanup, and fixed-root daemon/lock constraints.
- Manual cross-ADR review confirmed ADR-021 configuration precedence and
  strict schema validation, ADR-025's sole mutation coordinator, ADR-026's
  fixed-root warm daemon, and ADR-031's non-authoritative similarity-index
  boundary remain authoritative.
- `NO_MKDOCS_2_WARNING=1 uv run mkdocs build --strict` completed successfully;
  the existing wildcard ADR nav emitted its expected informational absolute-path
  notice and no error.
- `uv run --no-sync codira index` completed with one indexed file, 384 reused
  files, zero failures, and zero coverage issues.
- `uv run --no-sync codira audit` completed with no docstring issues.

### Slice 2 - Migrate core exact and FAISS result/provenance contracts

Status: `complete`

Scope:

1. Replace flattened similarity-score results and untyped purge requests with
   validated result-envelope, provenance, error, and purge lifecycle contracts.
2. Migrate exact, FAISS, structural backend resolution, semantic retrieval,
   CLI, MCP, daemon, and context explain paths without discarding provenance.
3. Version every exposed result shape and prove provenance remains credential
   safe and aligned to the ranked candidate after structural filtering.

Acceptance:

- `SimilarityIndex.search()` returns a deterministic, immutable
  `SimilaritySearchResult`; each candidate has a stable ID, score, and
  credential-free native provenance, and each query has typed provenance.
- Exact carries deterministic core provenance without inventing a native ID;
  FAISS carries only its label/native-position sidecar and typed purge results.
- SQLite and DuckDB resolve typed candidates while preserving that sidecar;
  semantic, CLI, MCP, daemon, JSON, and context explain outputs retain it.
- Unsafe provenance and malformed result ordering are rejected, and typed
  failure classes cover unavailable, authentication, stale, incompatible,
  unsafe-ownership, publication, and cleanup boundaries.

Recorded evidence:

- Added validated `SimilaritySearchResult`, candidate/query provenance,
  resolved-candidate, typed-error, and typed-purge contracts in
  `src/codira/contracts.py`; provenance rejects credential, URL, namespace,
  path, header, and server-payload shaped values.
- Exact and FAISS now return the envelope; exact has no fabricated native
  candidate identity, while FAISS exposes the opaque artifact hash and
  `faiss_label` only. Their ordering, limits, stale checks, and strict
  selection semantics remain covered by focused tests.
- Structural resolution and semantic/context result containers preserve the
  original typed candidate through filtering and limits. CLI/MCP JSON and
  context explain output expose a credential-free query envelope plus an
  aligned candidate sidecar.
- Bumped query/context JSON schemas to `2.0`, MCP contract to `2.0.0`, daemon
  IPC protocol to `2`, and capabilities schema to `2.0`.
- Focused contract, FAISS, backend, semantic/context, daemon, CLI/MCP, schema,
  capability, and characterization suites completed with 202 passed and one
  expected skip; the separate backend lifecycle suite completed with 157
  passed. `uv run ruff check .`, `uv run ruff format --check .`, and
  `uv run mypy src tests scripts/characterize_similarity_indexes.py` completed
  successfully.
- `uv run python scripts/validate_repo.py` completed with 871 passed and one
  expected skip; its Ruff, format, mypy, pre-commit hygiene, and Semgrep stages
  completed successfully with zero Semgrep findings.
- A fresh `uv run --no-sync codira index` completed with two indexed and 384
  reused files, zero failures, and zero coverage issues; the subsequent
  `uv run --no-sync codira audit` reported no docstring issues.

### Slice 3 - Add authenticated Qdrant package, configuration, and identity

Status: `complete`

Scope:

1. Add the typed, separately distributed Qdrant similarity-index foundation
   with a deterministic fake-client seam.
2. Register Qdrant as a selectable first-party similarity index without
   making it the default or adding it to the official bundle.
3. Validate strict, pre-network configuration admission and fail-closed
   lifecycle placeholders.

Recorded evidence:

- Added `codira-similarity-index-qdrant==2.0.0`, pinned to
  `qdrant-client==1.19.0`, with package-local imports only, typed client
  settings/factory injection, cosine-only specification, and `py.typed`.
- The schema rejects unsupported keys and unsafe URL forms before client
  construction; it validates REST/gRPC selection, namespace, bounded timeout,
  consistency, HNSW, on-disk, and upload-batch settings. Credentials remain
  unconfigured and lifecycle methods fail closed pending later phases.
- Qdrant is discoverable as a selectable first-party package and appears in
  generated installer configuration metadata, but Phase 11 remains pending:
  it is not a default `codira-bundle-official` dependency yet.
- The focused root/package suite completed with 656 passed and one expected
  skip after the synchronized editable package set was rebuilt.

### Slice 3a - Coordinate the 2.0 compatibility boundary

Status: `complete`

Scope:

1. Align every first-party distribution, root extra, official-bundle pin,
   inventory/catalog value, and core lower bound to `2.0.0`.
2. Preserve Phase 11 as the only authority to add Qdrant to the default
   official bundle.
3. Regenerate the lockfile and record release-facing breaking-contract notes.

Recorded evidence:

- All 28 first-party distribution metadata versions are `2.0.0`; every
  plugin that depends on core now declares `codira>=2.0.0,<3.0.0`.
  FAISS's package runtime version, installer package pin, and optional bundle
  extra were aligned as part of the broken-protocol release boundary.
- Root development and curated extras, the official bundle dependencies,
  `first_party_packages.json`, and generated installer catalog now use the
  same coordinated value. Qdrant remains absent from the official bundle until
  Phase 11.
- `uv lock` and `uv sync` resolved the full workspace, adding the pinned
  Qdrant client and its gRPC transitive dependencies. `uv lock --check` and a
  release-inventory assertion confirmed all 28 package projects are aligned.
- Updated `CHANGELOG.md` with result-envelope, provenance, purge, reset, and
  coordinated-package release notes.
- Delivered with the atomic commit `feat(package)!: add Qdrant index
  foundation`; Phase 11 remains pending for its later official-bundle default
  dependency and follow-up version recheck.

### Slice 3b - Resolve credentials and initialize Qdrant clients

Status: `complete`

Scope:

1. Resolve Qdrant API credentials with environment precedence and private-file
   fallback without serializing a credential or source path into runtime output.
2. Construct and probe a command-scoped, fixed-root client with the approved
   REST/gRPC, timeout, and compatibility settings.
3. Map client failures to credential-free typed Codira errors and clear all
   client state from `reset_runtime_caches()`.

Recorded evidence:

- A non-empty configured environment variable takes precedence; missing or
  blank values fall back to a readable regular, non-symlink credential file.
  On POSIX, group- and world-accessible files are rejected. Only one terminal
  CRLF, CR, or LF ending is removed from file content.
- `initialize` binds a successful client and `info()` probe to one resolved
  repository root. Repeated initialization for that root reuses the
  command-scoped client; reset releases it. Neither error messages nor object
  representations include credential values.
- Qdrant HTTP 401/403 responses become `SimilarityIndexAuthenticationError`;
  client construction, connection, and other probe failures become
  `SimilarityIndexUnavailableError` without server exception text.
- Delivered in the atomic `feat(plugins): initialize Qdrant clients` commit.

### Slice 3c - Establish remote identity and ownership evidence

Status: `complete`

Scope:

1. Create and retain a repository-local Qdrant UUID across semantic reset.
2. Derive opaque aliases, immutable collection names, point IDs, and manifest
   IDs from every required root, vector, index, Qdrant-build, namespace,
   endpoint, object-type, and source-revision identity component.
3. Create a credential-free local ownership-ledger location for later remote
   publication and cleanup evidence.

Recorded evidence:

- The repository UUID is atomically created as a regular non-symlink file and
  is not under the semantic-state directory removed by `codira emb reset`.
- Collection and alias names contain only fixed prefixes and opaque hashes;
  deterministic UUIDv5 point IDs never render stable IDs, paths, endpoint
  URLs, namespaces, or credentials.
- Initialization creates a versioned empty ownership ledger under
  `.codira/similarity-indexes/qdrant`. Publication and retention records are
  deliberately deferred to Phase 7 so an empty ledger never claims remote
  ownership.
- Delivered in the atomic `feat(plugins): derive Qdrant remote identities`
  commit.

### Slice 4 - Implement atomic collection publication, search, and retention

Status: `complete`

Recorded evidence:

- Rebuild now creates an immutable cosine/HNSW collection, writes a reserved
  manifest and bounded confirmed point batches, verifies count/readiness/vector
  contract, then replaces the stable alias in one Qdrant alias-operation batch.
- The ownership ledger records the current and immediately previous opaque
  collection evidence. A third-old collection is deleted only when the local
  record and its retrieved reserved remote manifest agree on artifact,
  repository, root, and source-revision hashes; ambiguous or unavailable state
  is retained.
- Focused fake-client publication coverage completed with 37 passed. The full
  repository gate completed with 910 passed and one expected skip; subsequent
  index/audit reported zero failures, coverage issues, and docstring issues.
- Delivered in the atomic `feat(plugins): publish Qdrant revisions atomically`
  commit.

### Slice 5 - Implement remote purge/reset, daemon/MCP provenance, and schemas

Status: `in_progress`

Phase 9 recorded evidence:

- Added explicit `codira emb similarity-purge`: it inventories by default and
  requires `--yes` for deletion, under the repository index lock.
- Qdrant deletion requires both local ledger evidence and an exact retrieved
  remote manifest match; ambiguous state is skipped. Reset attempts confirmed
  remote cleanup before deleting the local ledger, blocks by default on failure,
  and `--allow-remote-orphans` reports only opaque local artifact hashes.
- Focused Qdrant/lifecycle suites completed with 43 passed. The observed
  standalone `uv run --no-sync python scripts/validate_repo.py` exit was 0:
  913 passed, one expected skip, zero Semgrep findings, and 87% total coverage.
- `uv run --no-sync codira index` indexed 5 files with zero failures and zero
  coverage issues; `uv run --no-sync codira audit` found no docstring issues.

Phase 11 recorded evidence:

- Qdrant remains selectable but not the default selected index. It is now a
  default `codira-bundle-official` dependency, while the root development
  dependency and first-party inventory remain aligned at `2.0.0`.
- The README names the installed-but-opt-in authenticated Qdrant plugin and
  preserves the strict no-fallback boundary. Bundle metadata coverage now
  asserts its exact dependency placement.
- `uv lock`, `uv lock --check`, and the installer catalog check completed.
  The focused bundle test passed.
- The observed standalone repository gate exit was 0: 913 passed, one expected
  skip, zero Semgrep findings, and 87% total coverage. A subsequent Codira
  index completed with zero failures and coverage issues; audit found no
  docstring issues.

Phase 13 recorded evidence:

- Replaced the package's stale foundation-only README with the full
  authenticated remote first-use journey: configuration, environment/file
  credential precedence, REST/gRPC, HNSW/profile settings, rebuild, query,
  immutable aliases, retention, purge, reset, and orphan recovery.
- Updated the getting-started guide and root plugin inventory so the official
  bundle's installed-but-opt-in Qdrant behavior and no-fallback boundary are
  discoverable. The documentation explicitly limits fake-client evidence to
  the Codira/client boundary rather than live-server claims.
- `NO_MKDOCS_2_WARNING=1 uv run --no-sync mkdocs build --strict` passed; the
  existing nav informational notices remained non-failing. The Qdrant focused
  suite completed with 40 passed.
- The observed standalone repository gate exit was 0: 913 passed, one expected
  skip, zero Semgrep findings, and 87% total coverage. A subsequent Codira
  index completed with zero failures and coverage issues; audit found no
  docstring issues.

Phase 10 recorded evidence:

- The Phase 2 typed similarity envelope is retained by direct CLI, warm query
  daemon, and MCP `emb`/`docs` paths. Existing MCP coverage verifies query and
  candidate provenance is rendered through those envelopes; Qdrant supplies
  opaque artifact, alias/collection, point, revision, and transport metadata.
- The Qdrant client is command-scoped and fixed-root; profile `ef_search` is
  supplied only to `query_points` and does not mutate shared plugin state.

Phase 14 recorded evidence:

- Added installed-wheel rehearsal coverage that imports Qdrant and constructs
  it with its fake client seam, without a live server. Focused rehearsal tests
  completed with 6 passed.
- The observed standalone repository gate exit was 0: 913 passed, one expected
  skip, zero Semgrep findings, and 87% total coverage. Codira index and audit
  completed with zero coverage/docstring findings.

### Slice 4a - Implement verified Qdrant search

Status: `complete`

Recorded evidence:

- Search resolves the stable alias once, requires its exact immutable physical
  collection for the requested source revision, then verifies the reserved
  manifest, cosine dimension, repository/root/namespace hashes, and opaque
  build artifact before querying. Missing and stale aliases fail closed.
- The remote query requests vector payloads only, never vectors; it maps
  profile `ef_search`, candidate limit, minimum score, and configured read
  consistency to Qdrant `SearchParams`, `limit`, `score_threshold`, and
  `consistency`. Returned candidates are bounded and ordered by descending
  score then stable ID with opaque native point provenance.
- Fake-client Qdrant tests completed with 39 passed. Package Ruff, formatting,
  and mypy completed successfully.
- `uv run --no-sync python scripts/validate_repo.py` completed with 912 passed
  and one expected skip; the observed process exit was 0. Its Ruff, format,
  mypy, pre-commit hygiene, and Semgrep stages completed successfully with
  zero Semgrep findings and total coverage was 87%.
- `uv run --no-sync codira index` reused 389 files with zero failures and zero
  coverage issues; `uv run --no-sync codira audit` reported no docstring
  issues.
- Delivered in the atomic `feat(plugins): search verified Qdrant revisions`
  commit.

### Slice 6 - Align installer, bundle, coordinated 2.0 metadata, and docs

Status: `pending`

### Slice 7 - Run focused, package, repository, and release-rehearsal gates

Status: `pending`

## Validation record

| Slice | Command | Exit | Result |
| --- | --- | --- | --- |
| 0 | `git status --short` | 0 | Clean before branch creation. |
| 0 | `git rev-parse HEAD main origin/main` | 0 | All resolved to the recorded base. |
| 0 | `git switch -c issue/71-qdrant-similarity-index` | 0 | New branch created and checked out. |
| 0 | `git diff --check` | 0 | No whitespace errors. |
| 0 | `uv run --no-sync codira index` | 0 | One ledger file indexed; zero failures and coverage issues. |
| 0 | `uv run --no-sync codira audit` | 0 | No docstring issues. |
| 1 | `git diff --check` | 0 | No whitespace errors before validation. |
| 1 | `NO_MKDOCS_2_WARNING=1 uv run mkdocs build --strict` | 0 | Documentation built strictly; only the pre-existing wildcard ADR-nav information was emitted. |
| 1 | `uv run --no-sync codira index` | 0 | One file indexed, 384 reused, zero failures and coverage issues. |
| 1 | `uv run --no-sync codira audit` | 0 | No docstring issues. |
| 3/3a | `uv lock && uv sync && uv lock --check` | 0 | Resolved the aligned 28-distribution workspace and recorded Qdrant client dependencies. |
| 3/3a | `PYTHONPATH=packages/codira-similarity-index-qdrant/src uv run --no-sync python scripts/generate_installer_catalog.py --check` | 0 | Generated installer catalog matches the first-party inventory. |
| 3/3a | `uv run --no-sync pytest -q tests/test_contracts.py tests/test_capabilities.py tests/test_mcp_server.py tests/test_plugins.py tests/test_bootstrap_scripts.py packages/*/tests` | 0 | 656 passed, 1 skipped. |
| 3/3a | `uv run --no-sync ruff check . && uv run --no-sync ruff format --check . && uv run --no-sync mypy src tests packages scripts` | 0 | Lint, formatting, and typing passed. |
| 3/3a | `uv run --extra docs mkdocs build --strict` | 0 | Strict documentation build passed; existing MkDocs informational warnings remained non-failing. |
| 3/3a | `uv run --no-sync python scripts/validate_repo.py` | 0 | 902 passed, 1 skipped; Semgrep reported zero findings and total coverage was 87%. |
| 3/3a | `uv run --no-sync codira index && uv run --no-sync codira audit` | 0 | 30 indexed, 356 reused, zero failures/coverage issues; no docstring issues. |
| 3b | `uv run --no-sync pytest -q packages/codira-similarity-index-qdrant/tests/test_qdrant_similarity_index.py` | 0 | 34 passed. |
| 3b | `uv run --no-sync ruff check --fix packages/codira-similarity-index-qdrant && uv run --no-sync mypy packages/codira-similarity-index-qdrant` | 0 | Initial Ruff hygiene findings were fixed; final lint and typing passed. |
| 3b | `uv run --no-sync python scripts/validate_repo.py` | 0 | 907 passed, 1 skipped; Semgrep reported zero findings and total coverage was 87%. |
| 3b | `uv run --no-sync codira index && uv run --no-sync codira audit` | 0 | 3 indexed, 386 reused, zero failures/coverage issues; no docstring issues. |
| 3c | `uv run --no-sync pytest -q packages/codira-similarity-index-qdrant/tests/test_qdrant_similarity_index.py` | 0 | 36 passed. |
| 3c | `uv run --no-sync ruff check --fix packages/codira-similarity-index-qdrant && uv run --no-sync mypy packages/codira-similarity-index-qdrant` | 0 | Initial Ruff import hygiene findings were fixed; final lint and typing passed. |
| 3c | `uv run --no-sync python scripts/validate_repo.py` | 0 | 909 passed, 1 skipped; Semgrep reported zero findings and total coverage was 87%. |
| 3c | `uv run --no-sync codira index && uv run --no-sync codira audit` | 0 | 3 indexed, 386 reused, zero failures/coverage issues; no docstring issues. |
