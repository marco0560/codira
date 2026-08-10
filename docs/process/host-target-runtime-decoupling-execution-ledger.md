# Codira Host–Target Runtime Decoupling Execution Ledger

## Objective

Decouple the Python runtime that executes Codira from the Python runtime and
language level of every repository Codira analyzes. Deliver a recommended
standalone Codira installation, explicit named workspace routing for the CLI,
MCP, and managed services, one shared model store, and a host-independent,
version-aware Python analyzer.

The completed architecture must support this product claim:

> Codira's host Python requirement does not constrain the Python version of
> repositories it can analyze.

That claim may be published only after the parser migration and declared Python
compatibility matrix are complete and green.

## Execution authority

- Approved by the operator on 2026-08-10.
- Branch at approval: `fix/mcp-initial-release`.
- Commit at approval: `985599c`.
- Execution is limited to the architecture and ordered slices in this ledger.
- Slices execute in order. A later slice may not start while an earlier slice
  is incomplete or blocked.
- Every slice ends with focused validation, a refreshed Codira index,
  `uv run codira audit`, standalone `uv run python scripts/validate_repo.py`, a
  green validation report, an atomic Conventional Commit, and a clean
  worktree.
- A material design change, destructive migration, new public stability
  promise, target-repository code execution, or scope expansion stops execution
  and returns control to the operator.

## Approved decision set

| Area | Approved decision |
| --- | --- |
| Runtime ownership | Installer-managed per-user Codira runtime with user launchers |
| Workspace layout | One directory per named workspace with `workspace.toml` and optional `config.toml` |
| Workspace state | Per-user state directory by default; repository-local state is opt-in |
| Workspace selection | Explicit `--workspace` or environment selection, mutually exclusive with direct path routing |
| MCP workspace | `codira-mcp --workspace NAME`, resolved once at startup; retain `--root` |
| Installer scope | Standalone runtime plus workspace registration by default; repository-local modes remain Advanced |
| Repository-local mode | Supported indefinitely where compatible, but not recommended |
| Target Python contract | PEP 440 `target_requires_python`; explicit configuration overrides detected project metadata |
| Python source range | Python 3.8 through the newest bundled and tested grammar |
| Parser strategy | Complete migration from host `ast` parsing to Tree-sitter |
| Degraded analysis | Persist only reliable structural results with provenance and coverage diagnostics |
| Service identity | Workspace-scoped services with persisted resolved identity; retain direct paths |
| Python API | Shared typed internal contracts without a public stability promise |
| Migration | Previewed, explicit, non-destructive registration, copying, reuse, or rebuilding |
| Architecture documentation | New ADR supersedes the conflated parts of ADR-017; update all affected guides |
| Rollout | One ordered ledger of atomic validated slices |
| Future repository groups | A workspace owns one repository; a Codira family will aggregate workspace IDs |
| Model storage | One configurable per-user content-addressed store shared by all installations and workspaces |

## Terminology

- **Host runtime**: the Python interpreter and environment that execute Codira.
- **Target repository**: the repository whose files Codira reads and analyzes.
- **Target Python contract**: the Python versions the target repository claims
  to support.
- **Workspace**: a stable named definition for exactly one target repository,
  its state directory, and its configuration source.
- **Direct-path mode**: compatibility mode using `--path`, `--output-dir`, and
  `--config-file` without a registered workspace.
- **Codira family**: a future named aggregate of workspace IDs. A family is not
  a multi-root workspace.
- **Model store**: the shared verified store for large immutable model
  artifacts.
- **Parse support**: whether the bundled grammar can represent a source file.
- **Target compatibility**: whether a source file is valid for the versions
  declared by its target Python contract.

## Architectural plan

### 1. Runtime and repository separation

The preferred deployment model is:

```text
Codira host installation
Python >=3.13
managed runtime + CLI + MCP + plugins
            │
            ├── shared model store
            ├── workspace registry
            └── CLI / MCP / services
                    │
                    ▼
             target repository
             Python 3.8 / 3.9 / ...
```

Codira reads filesystem, Git, configuration, source, documentation, and
repository metadata. Normal analysis must not import or execute target
repository code and must not depend on the target repository's virtual
environment.

The primary internal contracts are:

- `HostRuntime` for the Codira execution environment;
- `WorkspaceDefinition` for persisted workspace data;
- `ResolvedWorkspace` for validated absolute routing;
- `TargetPythonContract` for detected or configured compatibility;
- a Codira-owned normalized Python syntax representation;
- `ModelStore` for verified shared model artifacts.

### 2. Platform filesystem model

All platform locations are derived centrally through `platformdirs`. The
conceptual Linux layout is:

```text
~/.local/share/codira/
    runtimes/
        default/
            .venv/
            installation.toml

~/.config/codira/
    config.toml
    workspaces/
        old-project/
            workspace.toml
            config.toml

~/.local/state/codira/
    workspaces/
        old-project/
            index/
            logs/
            services/

~/.cache/codira/
    models/
        manifests/
        blobs/
        locks/
        providers/
```

`workspace.toml` has a versioned schema and a stable workspace name. It records
one repository root, one output/state root, and an optional configuration file.
Relative descriptor paths resolve relative to the workspace directory. All
effective paths are canonicalized and validated before use.

### 3. Routing and configuration precedence

Workspace mode is explicit:

```bash
codira index --workspace old-project
CODIRA_WORKSPACE=old-project codira sym Example
codira-mcp --workspace old-project
```

`--workspace` or `CODIRA_WORKSPACE` selects repository root, output root, and
workspace configuration as one atomic unit. It cannot be combined with
`--path`, `--output-dir`, `--config-file`, or the corresponding direct-routing
environment variables. Conflicts fail before configuration or storage access.

Direct-path compatibility mode remains supported:

```bash
codira index --path /repo --output-dir /state \
    --config-file /configuration/config.toml
```

Routing is resolved before ordinary configuration layering. Existing system,
user, repository/workspace, and environment configuration precedence remains
intact after the routing source is known.

### 4. Workspace administration

The CLI gains deterministic workspace administration:

```text
codira workspace add NAME --path REPO
codira workspace list
codira workspace show NAME
codira workspace validate NAME
codira workspace update NAME ...
codira workspace remove NAME
codira workspace migrate ...
```

Commands support structured JSON output. Creation and updates are atomic.
Removing a workspace unregisters it and does not delete repository or state
data. Duplicate names, duplicate canonical roots, invalid descriptors, and
unsafe path relationships produce actionable errors.

CLI, MCP, services, migration, and installer surfaces reuse the same typed
internal workspace operations. These contracts do not acquire a public Python
API stability guarantee in this ledger.

### 5. Shared model store

The default model root is the platform user cache under `codira/models`.
Resolution precedence is:

```text
explicit installer or command selection
    ↓
CODIRA_MODELS_DIR
    ↓
global Codira configuration
    ↓
platform default
```

Artifact identity includes provider, model identifier, immutable revision,
checksum, and format/runtime variant. Provisioning uses an artifact-specific
lock, downloads to a sibling temporary location, verifies integrity, publishes
atomically, and records a manifest. All Codira runtimes, plugins, workspaces,
CLI processes, and MCP servers reuse the verified blob.

Models are not installed in a managed virtual environment or workspace state.
Existing Codira-managed copies may be imported by checksum without deleting
their originals. Provider integrations do not silently mutate unrelated global
third-party cache settings.

### 6. Installer architecture

Installer planning separates three concepts:

```text
installation source
    cloned checkout or coordinated package release

Codira runtime destination
    managed standalone / current / existing / new environment

analyzed repository
    optional workspace registration
```

The recommended TUI path installs or repairs the managed standalone runtime,
selects coordinated packages, confirms the shared model store, optionally
registers a workspace, previews one immutable plan, and applies the same plan
used by headless mode.

The existing cases remain supported:

- install from a cloned checkout into its current environment;
- create a new separate environment;
- install into an existing environment associated with another repository;
- detect and modify an existing Codira installation.

Environment-bound cases remain under Advanced and display their host-runtime
compatibility consequences. Managed installations record an installation
receipt and provide deterministic launchers for the CLI, MCP server, and
installer without requiring target-environment activation.

### 7. MCP and service identity

`codira-mcp --workspace NAME` resolves workspace identity, repository root,
state root, and configuration exactly once at process startup. Existing
`codira-mcp --root PATH` remains available and mutually exclusive.

Repository paths remain absent from MCP requests. The fixed-root, local,
read-only security boundary remains unchanged after workspace resolution.

MCP presets prefer workspace identity. Managed services persist workspace name,
canonical repository root, output root, effective configuration source, and a
descriptor fingerprint. A changed descriptor invalidates or refreshes the
service; a running process is never silently retargeted.

### 8. Target Python compatibility

The Python analyzer accepts:

```toml
[plugins.analyzer-python]
target_requires_python = ">=3.10"
```

Resolution order is explicit analyzer configuration, target repository
`[project].requires-python`, then unknown compatibility. PEP 440 requirements
are normalized against the analyzer's tested minor-version set.

Capabilities and diagnostics report host runtime, detected target contract,
tested grammar range, bundled grammar revision, and full, partial, unsupported,
or unknown coverage. Invalid declarations and partially intersecting ranges
are distinct diagnostics.

### 9. Host-independent Python parsing

The official `tree-sitter` Python binding and `tree-sitter-python` grammar are
pinned as a tested compatible pair in `codira-analyzer-python`. Core does not
gain a Python grammar dependency.

The analyzer owns a normalized syntax layer for the constructs required by
current behavior, including definitions, parameters, annotations, assignments,
imports, references, calls, attributes, docstrings, control-flow constructs,
source spans, parse errors, missing nodes, and feature-level minimum Python
versions.

Tree-sitter node names do not leak into persisted backend schemas or core query
APIs. Existing behavior is characterized before migration and ported artifact
category by artifact category. Temporary dual parsing is test-only. Production
migration is incomplete while any analysis path still depends on host
`ast.parse`.

### 10. Version-aware syntax rules

Tree-sitter parse support and target-version compatibility are separate. A
Codira-owned capability table records the minimum Python version of relevant
syntax features. Detected source features are compared with every applicable
minor version in the declared target contract.

The analyzer therefore distinguishes a grammar that can parse a file from a
project claim that the same file runs on Python 3.8, 3.10, or a future version.

### 11. Degraded analysis

Parser errors and grammar gaps do not silently yield apparently complete
output. The analyzer persists only artifacts whose spans and provenance remain
reliable, records the omitted categories and grammar identity, and marks file
coverage partial. Strict coverage fails for the affected file while indexing
continues for unrelated files. Infrastructure and storage failures retain their
existing fail-fast semantics.

Queries may expose reliable partial results only when they also expose degraded
provenance.

### 12. Compatibility matrix

Committed fixtures cover Python 3.8 through the newest bundled and tested
grammar. Each minor includes introduced syntax, inherited syntax, compatible
and conflicting target declarations, invalid or future syntax, normalized
artifacts, and expected diagnostics.

Tests cover an older target than the host, source syntax newer than the host,
unknown target declarations, open and bounded PEP 440 ranges, workspace/direct
parity, CLI/MCP parity, partial persistence, and the absence of production
`ast.parse` use. The maximum supported version is a tested release claim, not
whatever the parser happens to accept.

### 13. Migration policy

Migration is dry-run-first, explicit, atomic, idempotent, and non-destructive.
It may register a repository, copy or continue referencing configuration, reuse
or copy state, rebuild state, and import existing model artifacts. It displays
all sources and destinations, rejects unsafe overlaps, and records provenance.

Original configuration, state, environments, and model files are never deleted
automatically.

### 14. Documentation contract

ADR-028 supersedes the conflated host/target portions of ADR-017 without
rewriting historical decisions. Documentation distinguishes host runtime,
target source compatibility, installation environment, repository environment,
grammar compatibility, and semantic compatibility.

README, getting-started, installer, configuration, MCP, service, analyzer,
package, compatibility, migration, release, and architecture documentation are
updated alongside the slice that changes their behavior.

### 15. Release and compatibility policy

Codira may raise its host Python minimum independently of its declared target
source range. A release must publish both values. Parser dependency upgrades
must update the grammar revision, compatibility fixtures, capability output,
and release evidence together.

Repository-local installation remains a compatible convenience, not the
fundamental runtime contract. CLI and MCP remain equal interfaces over the same
workspace and analyzer contracts.

### 16. Validation and commit policy

Every slice uses the narrowest meaningful tests during development and the full
repository gate once at its coherent boundary. The slice validation report is
green only when it records:

- focused tests for the touched surface;
- relevant generated-artifact and package checks;
- `uv run codira index` with no coverage issues;
- `uv run codira audit` with no findings;
- standalone `uv run python scripts/validate_repo.py` with observed exit code
  `0` and its pytest summary;
- `git diff --check`;
- one reviewed atomic diff;
- one Conventional Commit with root cause, implementation, and validation;
- an empty `git status --short` after the commit.

### 17. Scope boundaries and future evolution

#### Deferred implementation

The following is intentionally postponed but must remain architecturally
possible:

- Actual `codira family` registration, administration, family-wide indexing,
  and multi-workspace query commands.

The family design is constrained now: a family is a named, non-nested list of
workspace IDs; it does not redefine workspace descriptors or weaken fixed-root
MCP identity. Implementing families requires its own approved behavioral plan,
especially for ordering, partial failure, aggregate output, and state
ownership.

#### Architectural non-goals

- A stable public Python API in this ledger. Approved internal contracts may
  evolve until a separate API decision is accepted.
- System-wide multi-user model storage. The approved store is per-user.
- Importing or executing target repository code during ordinary analysis.
- Separate public Python analyzer packages per Python minor version.
- Automatic deletion of original configuration, state, model files, or
  environments during migration.
- Silent retargeting of a running MCP server or managed service.
- Nested families or treating a workspace as a multi-root repository group.

#### Future extension points

- Stable workspace IDs and a versioned descriptor schema allow future family
  manifests to reference workspaces without rewriting them.
- Structured workspace command output supports future orchestration.
- Resolved workspace collections may be added above, not inside,
  `ResolvedWorkspace`.
- Analyzer rule strategies may split internally by Python version without
  creating separate distributions.
- The normalized syntax layer permits future grammar providers without leaking
  provider-specific nodes.
- The model manifest schema permits additional providers and storage backends
  while retaining content identity.
- Typed internal contracts form the candidate surface for a separately
  approved public Python API.

## Status vocabulary

- `pending`: no implementation work accepted.
- `in_progress`: active implementation with no accepted commit.
- `validated`: the slice validation report is green; commit pending.
- `complete`: atomic commit and evidence recorded; worktree clean.
- `blocked`: deterministic progress requires operator input.

## Slice dependency map

```text
1 architecture baseline
└── 2 workspace domain
    ├── 3 workspace registry and CLI
    │   └── 4 CLI/config routing
    │       ├── 6 MCP
    │       ├── 7 services
    │       └── 10 migration
    ├── 8 installer engine
    │   └── 9 installer TUI
    └── 5 shared models

1 architecture baseline
└── 11 target Python contract
    └── 12 normalized Tree-sitter parser
        └── 13 analyzer extraction migration
            └── 14 remaining host-AST removal
                └── 15 version/degraded analysis
                    └── 16 compatibility matrix

All completed branches
└── 17 documentation and release readiness
```

## Slice ledger

### Slice 1 — Architecture baseline and behavioral characterization

Status: `pending`

Goal:

- Establish authoritative terminology, invariants, current behavior, and the
  migration boundary before production contracts change.

Scope:

- Add ADR-028 for host/target runtime decoupling and supersede the relevant
  portions of ADR-017.
- Characterize current path routing, MCP fixed-root startup, installer targets,
  model provisioning, Python artifacts, and production host-AST consumers.
- Add golden fixtures for current Python analyzer outputs without changing
  production behavior.
- Add an explicit production `ast.parse` inventory test or allowlist that must
  shrink to zero by Slice 14.

Primary surfaces:

- `docs/adr/ADR-017-python-runtime-support-policy.md`
- `docs/adr/ADR-028-host-target-runtime-decoupling.md`
- `docs/architecture/`
- `tests/`
- `packages/codira-analyzer-python/tests/`

Acceptance:

- Host runtime and target source compatibility are separate documented
  contracts.
- Golden artifacts capture symbols, spans, calls, references, imports,
  signatures, and docstrings from representative Python files.
- Every production host-AST consumer is identified by a deterministic test.
- No runtime behavior changes.

Commit intent: `docs(architecture): define host target runtime separation`

Evidence: pending.

### Slice 2 — Platform directories and workspace domain

Status: `pending`

Depends on: Slice 1.

Goal:

- Introduce typed, versioned workspace contracts and central platform paths
  without changing existing CLI defaults.

Scope:

- Add workspace definition, resolved workspace, schema version, validation,
  serialization, and deterministic error types.
- Centralize config, data, state, cache, runtime, workspace, and model paths.
- Resolve descriptor-relative paths, symlinks, containment, missing roots, and
  unsafe overlaps.
- Reserve stable workspace identity for future family references.

Primary surfaces:

- `src/codira/path_resolution.py`
- new focused workspace/platform-path modules under `src/codira/`
- workspace JSON/TOML schemas where repository conventions require them
- `tests/`

Acceptance:

- One descriptor represents exactly one canonical repository root.
- Platform path behavior is deterministic under isolated test directories on
  Linux, macOS, and Windows path models.
- Descriptor round trips are stable and reject unknown schema versions.
- Existing direct-path behavior is unchanged.

Commit intent: `feat(config): add workspace domain contracts`

Evidence: pending.

### Slice 3 — Workspace registry and administration CLI

Status: `pending`

Depends on: Slice 2.

Goal:

- Make workspaces safely registrable and inspectable by humans and automation.

Scope:

- Implement atomic registry operations for add, list, show, validate, update,
  and remove.
- Add CLI parsing, human output, structured JSON output, capability metadata,
  and help text.
- Detect duplicate names and canonical roots.
- Ensure remove unregisters only and reports retained state.

Acceptance:

- Repeated equivalent registration is idempotent.
- Conflicting registration fails without partial writes.
- Structured output has a versioned deterministic shape.
- Workspace removal never deletes repository, config, state, or models.

Commit intent: `feat(cli): add workspace administration`

Evidence: pending.

### Slice 4 — Workspace-aware CLI and configuration routing

Status: `pending`

Depends on: Slice 3.

Goal:

- Make every repository-scoped CLI operation use one shared routing decision.

Scope:

- Add `--workspace` and `CODIRA_WORKSPACE` to repository-scoped commands.
- Resolve workspace routing before effective configuration loading.
- Reject workspace selection mixed with direct path/config routing.
- Preserve direct flags, environment variables, and current-directory defaults.
- Propagate resolved workspace identity into index/query provenance and
  diagnostics where schemas permit it.

Primary surfaces:

- `src/codira/cli.py`
- `src/codira/path_resolution.py`
- `src/codira/config.py`
- capabilities and output schemas
- CLI/config/path tests

Acceptance:

- Workspace and equivalent direct-path runs resolve identical effective
  repository, output, and configuration paths.
- Mixed routing fails before reading an index or configuration.
- Existing invocations remain compatible.
- All repository-scoped commands use the shared resolver rather than local
  path logic.

Commit intent: `feat(cli): route commands through named workspaces`

Evidence: pending.

### Slice 5 — Shared content-addressed model store

Status: `pending`

Depends on: Slice 2.

Goal:

- Guarantee that an identical model artifact is downloaded once per user and
  reused across Codira installations and workspaces.

Scope:

- Add model identity, manifest, verified blob, lock, and atomic publication
  contracts.
- Implement default/global/environment/explicit model-root resolution.
- Adapt ONNX and Sentence Transformers providers to Codira-owned artifacts.
- Add offline reuse, interrupted-download recovery, checksum failure, and
  concurrent provisioning tests.
- Add non-destructive import of existing Codira-managed model copies.

Primary surfaces:

- `src/codira/` model/config contracts
- `packages/codira-embedding-onnx/`
- `packages/codira-embedding-sentence-transformers/`
- installer model planning
- provider and installer tests

Acceptance:

- Two isolated runtimes resolving the same identity use the same verified blob.
- Concurrent provisioning performs at most one successful publication.
- Corrupt or partial artifacts are never exposed as installed.
- No model payload is stored inside a workspace or managed virtual environment.

Commit intent: `feat(embedding): add shared verified model store`

Evidence: pending.

### Slice 6 — MCP workspace startup and presets

Status: `pending`

Depends on: Slice 4.

Goal:

- Start the read-only MCP server from stable workspace identity without
  weakening its fixed-root boundary.

Scope:

- Add mutually exclusive `codira-mcp --workspace NAME` and `--root PATH`.
- Resolve workspace root, output, and config once before server construction.
- Include safe workspace identity and descriptor fingerprint in provenance.
- Extend Codex, Claude, and Cursor preset generation for workspace mode.
- Preserve path-only presets and startup behavior.

Primary surfaces:

- `src/codira/mcp/server.py`
- `src/codira/mcp/presets.py`
- MCP capability schemas
- `tests/test_mcp_server.py`
- `tests/test_mcp_presets.py`

Acceptance:

- MCP requests cannot select or change repositories.
- Workspace and direct-root servers have equivalent read-only behavior for the
  same resolved paths.
- Descriptor changes require restart and cannot retarget a live process.
- Existing path-based client configurations remain valid.

Commit intent: `feat(mcp): support workspace scoped startup`

Evidence: pending.

### Slice 7 — Workspace-scoped services and daemons

Status: `pending`

Depends on: Slices 4 and 6.

Goal:

- Give managed indexing/query services a stable workspace identity and
  deterministic stale-definition behavior.

Scope:

- Extend service specifications with workspace name, canonical paths,
  effective config, and descriptor fingerprint.
- Render platform service definitions using workspace startup where selected.
- Detect descriptor drift in install/start/status operations.
- Preserve direct-path services and current platform security behavior.

Primary surfaces:

- `src/codira/daemon/`
- query-daemon CLI and runtime modules
- service installer adapters and tests
- service documentation

Acceptance:

- Services never infer a different repository from their working directory.
- Descriptor drift is reported and requires explicit regeneration/restart.
- Service install/start remains previewable and does not elevate privileges.
- Direct-path service definitions remain supported.

Commit intent: `feat(service): bind managed services to workspaces`

Evidence: pending.

### Slice 8 — Installer runtime/repository domain separation

Status: `pending`

Depends on: Slices 2, 3, and 5.

Goal:

- Make installation source, Codira runtime destination, and analyzed repository
  independent plan dimensions.

Scope:

- Add managed per-user runtime target and installation receipt contracts.
- Refactor installer requests and plans so workspace registration is not an
  environment target.
- Add deterministic launchers, detection, install, update, repair, and modify
  planning.
- Retain current, existing, and new environment targets as Advanced modes.
- Integrate shared model-store selection and optional workspace registration.

Primary surfaces:

- `packages/codira-installer/src/codira_installer/`
- installer schemas and catalog
- package metadata and bundle coordination
- installer engine tests

Acceptance:

- A target repository with an incompatible Python environment can be
  registered without installing Codira into that environment.
- Equivalent inputs still produce byte-identical plans.
- Existing four installation cases remain representable.
- Repair/update uses receipts and cannot silently change install source or
  package profile.

Commit intent: `feat(installer): separate runtime and repository targets`

Evidence: pending.

### Slice 9 — Standalone-first TUI and headless parity

Status: `pending`

Depends on: Slice 8.

Goal:

- Present the decoupled architecture as the recommended installer experience.

Scope:

- Update TUI screens for install/repair/modify, runtime destination, shared
  models, and optional workspace registration.
- Move environment-bound installation choices under Advanced.
- Show host and target compatibility consequences in review output.
- Preserve one immutable plan across TUI export and headless apply.
- Add navigation, cancellation, resume, failure, and success coverage.

Acceptance:

- Default flow creates or repairs a managed standalone runtime.
- TUI and headless requests resolve the same plan and fingerprint.
- No widget performs filesystem or subprocess mutations directly.
- Final instructions work without activating the target repository environment.

Commit intent: `feat(installer): make standalone workspace flow default`

Evidence: pending.

### Slice 10 — Explicit non-destructive migration tooling

Status: `pending`

Depends on: Slices 4, 5, and 8.

Goal:

- Move existing users toward standalone workspaces without risking repository,
  configuration, state, model, or environment data.

Scope:

- Implement dry-run and apply migration plans.
- Support register-in-place, config copy/reference, state reuse/copy/rebuild,
  and model import choices.
- Add provenance journals, idempotent resume, overlap rejection, and atomic
  destination writes.
- Integrate migration preview into the installer where appropriate.

Acceptance:

- Dry-run lists every source, destination, retained original, and estimated
  large-data action.
- Apply never deletes originals.
- Interrupted migration can resume without duplicating state or model blobs.
- Reapplying a completed plan is a no-op.

Commit intent: `feat(cli): add non destructive workspace migration`

Evidence: pending.

### Slice 11 — Target Python detection and capability contract

Status: `pending`

Depends on: Slice 1.

Goal:

- Represent target-language compatibility independently of the host
  interpreter before changing parsers.

Scope:

- Add typed PEP 440 target contracts and supported-minor normalization.
- Add explicit analyzer configuration and `[project].requires-python`
  detection.
- Define override, invalid, unknown, partial, and unsupported outcomes.
- Extend analyzer declarations, capabilities, provenance, and schemas.
- Keep existing AST extraction behavior during this slice.

Acceptance:

- Explicit configuration overrides repository metadata deterministically.
- Open, bounded, excluded, invalid, and non-intersecting specifiers are tested.
- Capability output reports host and target compatibility separately.
- No claim is made that host AST supports future syntax.

Commit intent: `feat(analyzer): declare target Python compatibility`

Evidence: pending.

### Slice 12 — Tree-sitter parser and normalized syntax layer

Status: `pending`

Depends on: Slice 11.

Goal:

- Add the host-independent parser behind a Codira-owned syntax contract without
  yet changing persisted analyzer results.

Scope:

- Pin compatible `tree-sitter` and `tree-sitter-python` dependencies in the
  Python analyzer package and coordinated lock/release metadata.
- Implement parser construction, byte handling, traversal, error/missing-node
  capture, spans, and normalized nodes.
- Map the constructs needed by Slice 1 golden fixtures.
- Add parser concurrency/reentrancy tests consistent with analyzer capability
  declarations.
- Keep comparison with host AST in tests only.

Acceptance:

- Python source parses independently of host `ast.parse`.
- Provider-specific node names remain internal to the adapter.
- Unicode byte/column and line spans are correct.
- Error and missing nodes produce deterministic normalized diagnostics.
- Core has no Tree-sitter Python dependency.

Commit intent: `feat(analyzer): add normalized Tree-sitter syntax layer`

Evidence: pending.

### Slice 13 — Python analyzer artifact migration

Status: `pending`

Depends on: Slice 12.

Goal:

- Produce all persisted Python analyzer artifacts from the normalized
  Tree-sitter layer.

Scope:

- Port module, class, function, method, constant, type-alias, import,
  documentation, call, and reference extraction.
- Preserve qualified names, signatures, decorators, annotations, source spans,
  and provenance.
- Compare all migrated artifacts against characterized fixtures.
- Update analyzer version and invalidation fingerprint.

Acceptance:

- Python analyzer production code no longer invokes host AST.
- Golden artifacts are equivalent except for explicitly reviewed improvements.
- Incremental indexing invalidates prior Python analyzer results safely.
- Backend contracts and non-Python analyzers remain unchanged.

Commit intent: `feat(analyzer): migrate Python artifacts to Tree-sitter`

Evidence: pending.

### Slice 14 — Remove remaining production host-AST consumers

Status: `pending`

Depends on: Slice 13.

Goal:

- Complete host grammar independence across core CLI and query behavior.

Scope:

- Replace module documentation, CLI inspection, context-query, and other
  production AST consumers with analyzer artifacts or generic contracts.
- Move Python-specific logic out of core where required by plugin ownership.
- Remove obsolete parser utilities and dependencies.
- Reduce the Slice 1 production AST inventory to zero.

Acceptance:

- No production source calls `ast.parse` or relies on host AST node classes for
  target analysis.
- Query behavior remains covered by existing and new fixtures.
- Core can operate without the Python analyzer installed, with capability-based
  degradation rather than import failure.
- Python grammar dependencies remain isolated to the Python analyzer package.

Commit intent: `refactor(core): remove host AST target parsing`

Evidence: pending.

### Slice 15 — Version rules and degraded-analysis persistence

Status: `pending`

Depends on: Slice 14.

Goal:

- Distinguish grammar support, target-version validity, and trustworthy partial
  analysis throughout indexing and querying.

Scope:

- Add feature/minimum-version rules for relevant Python syntax.
- Compare detected features with normalized target-version sets.
- Persist grammar identity, target contract, parser diagnostics, reliable
  artifact categories, omitted categories, and partial coverage.
- Extend backend logical contracts and both first-party structural backends as
  required.
- Surface degraded provenance in coverage, capabilities, CLI, and MCP queries.

Acceptance:

- A parseable file using syntax newer than its declared target produces a
  compatibility diagnostic.
- A grammar error persists no untrustworthy artifact and fails strict coverage
  without aborting unrelated files.
- SQLite and DuckDB expose equivalent logical behavior.
- Existing complete-analysis queries retain their output contract.

Commit intent: `feat(analyzer): persist version aware partial analysis`

Evidence: pending.

### Slice 16 — Python 3.8-to-latest compatibility matrix

Status: `pending`

Depends on: Slice 15.

Goal:

- Turn target-language support into a tested release claim independent of the
  host interpreter.

Scope:

- Add fixtures for every supported Python minor from 3.8 through the bundled
  grammar maximum.
- Cover introduced/inherited syntax, compatible/conflicting requirements,
  future syntax, invalid syntax, and partial artifacts.
- Test the minimum Codira host against older and newer target syntax.
- Add grammar-upgrade checklist and deterministic maximum-version metadata.

Acceptance:

- Every advertised minor has explicit passing fixtures.
- Future syntax beyond the host interpreter is analyzable when present in the
  bundled grammar fixtures.
- Capability output exactly matches the tested matrix.
- Raising the advertised maximum without fixtures fails validation.

Commit intent: `test(analyzer): enforce target Python compatibility matrix`

Evidence: pending.

### Slice 17 — Documentation, packaging, and release readiness

Status: `pending`

Depends on: Slices 1–16.

Goal:

- Make standalone host/target separation the coherent public deployment model
  and prove coordinated packages can deliver it.

Scope:

- Update README, getting started, installer, configuration, MCP, services,
  analyzer, architecture, package, compatibility, migration, and release docs.
- Document repository-local installation as Advanced compatibility mode.
- Document workspace/direct routing, model storage, offline reuse, target
  Python declarations, partial analysis, and parser support.
- Update package metadata, generated catalogs, bundle coordination, build
  scripts, CI matrix, and release rehearsal.
- Rehearse standalone installation, workspace registration, old-target
  analysis, MCP startup, shared-model reuse, and compatible repository-local
  installation from built artifacts.

Acceptance:

- Primary documentation no longer recommends installing Codira into every
  target repository environment.
- Runtime and target compatibility are published separately.
- Built packages install and operate without monorepo knowledge.
- Two isolated Codira runtimes reuse one model artifact in rehearsal.
- CLI and MCP analyze an older-Python fixture through a standalone host runtime.
- Deferred family work and architectural non-goals remain explicit.

Commit intent: `docs(release): publish standalone host target architecture`

Evidence: pending.

## Per-slice evidence template

Replace `pending` only with observed results:

```text
Validation report: green | red
Focused tests: <commands and summaries>
Generated/package checks: <commands and summaries or not applicable>
Codira index: <indexed/reused/coverage summary>
Codira audit: <summary>
Repository validation: <command, observed exit code, pytest summary>
Diff check: <result>
Commit: <hash and subject>
Final worktree: <clean status>
Notes: <reviewed deviations, retries, or none>
```

## Global completion gate

- All seventeen slices are `complete` in order.
- Every slice records a green validation report and atomic commit.
- Workspace and equivalent direct-path runs have tested parity.
- Managed standalone CLI, MCP, and services do not use target environments.
- Shared model tests and rehearsal prove one verified per-user artifact across
  installations and workspaces.
- Production target analysis contains no host `ast.parse` dependency.
- Python 3.8 through the advertised grammar maximum has explicit fixtures.
- Partial analysis is provenance-rich and strict coverage detects it.
- Migration is idempotent and never deletes originals.
- Documentation and packages state host and target compatibility separately.
- Deferred family implementation, architectural non-goals, and future
  extension points remain accurately documented.
- Final `uv run codira index` reports no coverage issues.
- Final `uv run codira audit` reports no findings.
- Final standalone `uv run python scripts/validate_repo.py` exits `0` with its
  pytest summary recorded.
- `git diff --check` passes and `git status --short` is empty after the final
  commit.
