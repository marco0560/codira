# Codira TUI Installer Execution Ledger

## Objective

Deliver a cross-platform Textual installer for fresh Codira installation and
subsequent reconfiguration. The implementation provides a standalone
`codira-installer` command and a guarded `codira setup` proxy while preserving
Codira's narrow core, coordinated first-party package set, configuration
hierarchy, and platform-service boundaries.

## Execution authority

- Approved by the operator on 2026-08-09.
- Initial executor: `gpt-5.6-terra`, medium reasoning.
- Branch at approval: `fix/mcp-initial-release`.
- Execution is limited to the approved slices below.
- Every slice requires focused tests, documentation appropriate to its public
  behavior, a refreshed Codira index, `uv run codira audit`, standalone
  `uv run python scripts/validate_repo.py`, an approved commit block, an atomic
  commit, and a clean worktree.
- A new material design choice, destructive package removal, automatic
  privilege elevation, third-party package installation, or scope expansion
  stops execution and returns control to the operator.
- Slice 1 was implemented in the worktree before the TERRA run was
  interrupted; its primary-agent reconciliation preserves that completed scope
  and records the resulting validation and atomic commit below.

## Approved decision set

| Decision | Selection |
| --- | --- |
| Product boundary | Standalone installer and `codira setup` over one engine |
| TUI library | Textual |
| Install target | Existing or newly created environment |
| Package sources | Coordinated PyPI releases and local checkout |
| Selection model | Profiles plus Advanced granular overrides |
| Plugin catalog | Official first-party packages only |
| Configuration scope | User and/or repository |
| Configuration depth | Guided, schema-driven Advanced, optional calibration |
| Optional operations | Models, MCP, indexing daemon, and query daemon |
| Reconciliation | Idempotent activation without automatic uninstall |
| Safety | Preview, confirm, atomic writes, fail-fast resumable execution |
| Platforms | Linux, macOS, and Windows |
| Automation | Versioned JSON plan and explicit headless apply |
| Ledger | Tracked ledger and atomic slice commits |
| Package ownership | `codira-installer` owns engine/UI; core delegates |
| Package manager | uv-primary with bounded pip support |

## Fixed constraints

- `codira-installer` is a coordinated first-party distribution.
- `codira-bundle-official` installs the matching installer distribution.
- Core does not acquire Textual or installer dependencies.
- `uv` is preferred and is required for environment creation and local-checkout
  installation.
- pip is supported only for a coordinated PyPI install into a compatible
  existing environment.
- The installer never installs `uv`, Python, system packages, or arbitrary
  third-party plugins.
- The installer never elevates privileges or uninstalls deselected packages.
- Recommendations are provenance-rich and require review.
- Calibration produces a second proposed configuration delta and never writes
  benchmark-derived values without confirmation.
- Model, MCP, service-install, and service-start operations are individually
  visible in the resolved plan.
- Commands are argument vectors, never shell strings.
- Plans and journals contain no credentials or private environment dumps.

## Status vocabulary

- `pending`: no implementation work accepted.
- `in_progress`: active implementation with no accepted commit yet.
- `validated`: slice gate passed; commit pending.
- `complete`: atomic commit recorded and worktree clean.
- `blocked`: deterministic progress requires operator input.

## Slice ledger

### Slice 1 — Architecture, package boundary, and canonical catalog

Status: `complete`

Scope:

- Add the installer architecture ADR.
- Add the `packages/codira-installer/` distribution skeleton and Textual
  dependency boundary.
- Establish one canonical first-party package manifest.
- Generate the installer's packaged official catalog from the manifest and
  plugin configuration schemas, with a deterministic `--check` mode.
- Reconcile local uv sources, development dependencies, official bundle,
  package inventories, build/rehearsal helpers, and future split manifests.

Acceptance:

- Catalog loading requires neither Textual nor optional plugin imports at
  runtime.
- Every selectable package and local package path is represented exactly once
  in the canonical manifest.
- Generated catalog drift fails deterministically.
- Installer wheel and sdist include their catalog and schemas.
- Existing source-tree installation behavior remains supported.

Evidence:

- Focused tests: `71 passed in 2.83s` for catalog, package-boundary, bundle,
  bootstrap, future-CI, and future-split coverage.
- Generated catalog: `uv run python scripts/generate_installer_catalog.py
  --check` passed.
- Codira index: `Indexed: 3`; `Coverage issues: 0`.
- Codira audit: `No docstring issues found`.
- Repository validation: `uv run python scripts/validate_repo.py` exited 0;
  `667 passed, 1 skipped in 151.49s`.
- Reconciliation: moved the canonical manifest under `packages/` so strict
  JSON analyzer coverage remains enabled; no coverage policy was weakened.
- Commit: `ac4f86b feat(package): add standalone installer foundation`,
  including the operator's MCP-first `AGENTS.md` policy update.

### Slice 2 — Declarative plan engine and environment backends

Status: `complete`

Scope:

- Add typed request, target, feature, step, result, and journal models.
- Add versioned JSON plan schema, stable rendering, validation, ordering, and
  fingerprinting.
- Add `Core only`, `Recommended (detected)`, and `Full official` installation
  profiles plus existing runtime tuning profiles.
- Add current, explicit-existing, and newly created environment targets.
- Add uv execution and bounded pip execution.
- Add preflight, dry-run rendering, idempotent postconditions, fail-fast apply,
  and safe resume.

Acceptance:

- Equivalent inputs produce byte-identical plans.
- Mixed coordinated versions are rejected.
- pip cannot create environments or install from local checkouts.
- Successful reapply/resume is a no-op.
- Deselected packages are reported but never removed.

Evidence:

- Focused tests: `7 passed in 0.04s` for declarative resolution, bounded pip,
  local checkout command vectors, retained deselections, and fail-fast resume.
- Codira index: `Indexed: 1`; `Coverage issues: 0`.
- Codira audit: `No docstring issues found`.
- Repository validation: `uv run python scripts/validate_repo.py` exited 0.
- Commit: `7d113d9 feat(package): add declarative installer plan engine`.

### Slice 3 — Core setup proxy, atomic configuration, and MCP merge

Status: `complete`

Scope:

- Add `codira setup`, its capability contract, guarded provider discovery, and
  compatible missing-provider guidance.
- Add `python -m codira` support.
- Add pure configuration preview, comment-preserving merge, validation, backup
  metadata, and atomic replacement.
- Add deterministic Codex TOML and Claude/Cursor JSON MCP merges that preserve
  unrelated configuration.

Acceptance:

- Core remains independent of Textual.
- Setup delegation and missing-provider behavior are deterministic.
- Invalid configuration leaves original files byte-identical.
- Repeated config and MCP merges are idempotent.

Evidence:

- Focused tests: `69 passed in 2.98s` for setup delegation, missing-provider
  guidance, module execution, configuration preview/replacement/recovery, MCP
  merge preservation, configuration, capabilities, and MCP presets.
- Codira index: `Indexed: 2`; `Coverage issues: 0`.
- Codira audit: `No docstring issues found`.
- Repository validation: `uv run python scripts/validate_repo.py` exited 0.
- Commit: `334eff4 feat(cli): delegate setup to installer provider`.

### Slice 4 — Models, calibration, and platform services

Status: `complete`

Scope:

- Add target-environment embedding-model provisioning.
- Add recommendation-only hardware probing and separately confirmed
  calibration deltas.
- Add explicit indexing-daemon and query-daemon configure/install/start steps.
- Add platform-specific status verification and remediation without automatic
  elevation.

Acceptance:

- Model provisioning is idempotent.
- Calibration cannot write without its second confirmation.
- Service plans are repository-scoped and platform-specific.
- Daemon failures remain isolated and accurately reported.

Evidence:

- Focused tests: `11 passed in 0.05s` for target-environment model
  provisioning, second-confirmed calibration, repository-scoped service plans,
  and isolated remediation.
- Codira index: `Indexed: 2`; `Coverage issues: 0`.
- Codira audit: `No docstring issues found`.
- Repository validation: `uv run python scripts/validate_repo.py` exited 0.
- Commit: `a53da99 feat(package): add installer optional operations`.

### Slice 5 — Textual application and headless parity

Status: `complete`

Scope:

- Add source, target, repository, profile, feature, configuration, model, MCP,
  service, review, progress, and result screens.
- Keep widgets free of subprocess and filesystem mutations.
- Add keyboard navigation, resizing, cancellation, worker-based progress, and
  resumable failure presentation.
- Add default TUI, plan export, headless apply, and resume entry points over the
  same plan engine.

Acceptance:

- TUI and headless requests resolve identical plans.
- Apply stays disabled until the complete plan validates.
- Cancellation preserves the journal and cannot interrupt atomic replacement.
- Headless Textual tests cover navigation, confirmation, failure, resume, and
  success.

Evidence:

- Focused tests: `16 passed in 3.83s` for Textual navigation and confirmation,
  shared TUI/headless plan resolution, source/target persistence, plan export,
  failure/resume, cancellation, and optional-operation regression coverage.
- Headless command: `uv run codira setup --source local-checkout --target
  existing --environment /tmp/codira-installer-target --plan
  /tmp/codira-slice5-plan.json` wrote a validated local-checkout plan with the
  cloned repository and explicit target environment.
- Codira index: `Indexed: 4`; `Coverage issues: 0`.
- Codira audit: `No docstring issues found`.
- Repository validation: `uv run python scripts/validate_repo.py` completed
  cleanly after ruff, formatting, mypy, hooks, Semgrep, and the full pytest
  coverage suite.
- Commit: `85fd674 feat(package): add Textual installer workflow`.

### Slice 6 — Cross-platform CI, release rehearsal, and documentation

Status: `complete`

Scope:

- Add Linux, macOS, and Windows installer smoke coverage.
- Add no-network temporary-environment integration tests with local artifacts.
- Rehearse standalone, official-bundle, selected-feature, and core-only
  installations.
- Complete user, configuration, MCP, service, release, contributor, and
  changelog documentation.
- Build and check the installer and official-bundle artifacts.

Acceptance:

- Published installation rehearsal requires no monorepo knowledge.
- Local-checkout plans do not contaminate PyPI plans.
- All three platform families exercise installer smoke coverage.
- Generated catalog, package metadata, docs, and release tooling agree.

Evidence:

- Focused tests: `21 passed in 5.34s` for no-index/no-dependency wheel
  installation, four installer plan exports, Windows virtual-environment path,
  build-byproduct cleanup, and Linux/macOS/Windows CI coverage.
- Documentation: `uv run mkdocs build --strict` passed; the installer guide,
  bundle README, release checklist, and changelog agree on the standalone
  workflow and release evidence.
- Generated catalog: `uv run python scripts/generate_installer_catalog.py
  --check` passed.
- Artifact build/check: installer and official-bundle wheels and sdists built
  with `--no-isolation`; `uv run python -m twine check` passed for all four
  artifacts.
- Installation rehearsal: `scripts/rehearse_installer_installs.py` created a
  disposable environment, installed only local installer and bundle wheels with
  `--no-index --no-deps`, verified bundle metadata, and exported standalone,
  selected-feature, core-only, and local-checkout plans.
- Codira index: `Indexed: 4`; `Coverage issues: 0`.
- Codira audit: `No docstring issues found`.
- Repository validation: standalone `uv run python scripts/validate_repo.py`
  completed cleanly after Ruff, formatting, mypy, hooks, Semgrep, and the full
  pytest coverage suite. A final direct full pytest rerun completed cleanly
  with 694 collected test nodes.
- Final worktree: clean after the atomic Slice 6 commit.
- Commit: `7c7fef8 feat(release): rehearse installer artifacts`.

## Final completion gate

- All six slices are `complete`.
- Every commit hash and validation result is recorded above.
- Installer and official-bundle wheels/sdists build and pass artifact checks.
- Fresh standalone, bundle, selected-feature, and core-only rehearsals pass.
- The final standalone `uv run python scripts/validate_repo.py` exits `0`; its
  pytest summary and any complete failures are recorded.
- `git diff --check` passes.
- `git status --short` is empty.
