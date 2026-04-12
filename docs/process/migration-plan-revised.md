# Codira Rebrand Migration Plan

## Version

Document version: `0.1.16`

Status: active migration ledger.

This document supersedes the root-level draft `migration-plan.md` for the
`repoindex` to `codira` rebrand.

## Change Log

- `0.1.0`: Record the corrected target name, the accepted `v1.0.0` version
  reset, the `pre-rebrand-snapshot` tag, the complete package/API rename scope,
  the repository validation contract, the tool-usability prerequisite, and the
  CLI subcommand-shortening requirement.
- `0.1.1`: Complete the Phase 0 local and split-repository tool smoke checks,
  add split-package-root support to the first-party install helper, and record
  the remaining `.typed` coverage classification.
- `0.1.2`: Complete the Phase 1 local state audit, verify
  `pre-rebrand-snapshot`, remove cleanup-tool-managed artifacts, and record
  PyPI namespace status for the old and new package names.
- `0.1.3`: Complete Phase 2 issue classification and defer actual issue
  transfer to Phase 9, after the new `codira` repository exists.
- `0.1.4`: Clarify that cleanup-tool protected paths remain `repoindex`
  only until the local rebrand slice, then must move to `codira`.
- `0.1.5`: Complete Phase 3 by creating the empty public
  `marco0560/codira` GitHub repository.
- `0.1.6`: Complete the Phase 4 local code/package rename and Phase 5
  subcommand-shortening implementation in one validated local slice.
- `0.1.7`: Complete Phase 6 drift audit for stale old project names,
  environment variables, package metadata, entry-point groups, and old
  subcommand references.
- `0.1.8`: Complete Phase 7 local validation, including extended package and
  example checks, distribution builds, twine validation, installed-wheel
  rehearsal, and CLI/plugin discovery smoke tests.
- `0.1.9`: Complete Phase 8 by publishing fresh `marco0560/codira` history
  from a prepared copy and pushing tag `v1.0.0`.
- `0.1.10`: Complete Phase 9 by transferring the selected open issues from
  `marco0560/repoindex` to `marco0560/codira`, verifying issue metadata, and
  confirming GitHub redirects for sampled old issue URLs.
- `0.1.11`: Complete Phase 10 by adding the old-repository archive notice,
  preserving public visibility, and archiving `marco0560/repoindex` on GitHub.
- `0.1.12`: Sync the Phase 8 through Phase 10 ledger into the active
  `codira` checkout and correct remaining ledger references where historical
  `repoindex` package names were accidentally rewritten to `codira`.
- `0.1.13`: Complete Phase 11 by uploading all seven `1.0.0` distributions to
  TestPyPI and validating a fresh `codira-bundle-official` install from the
  package index.
- `0.1.14`: Record the Phase 12 real-PyPI blocker: the first upload attempt
  was rejected with `403 Forbidden`, and PyPI still reported the attempted
  project name as absent afterward.
- `0.1.15`: Complete Phase 12 by retrying real PyPI uploads with TestPyPI
  `TWINE_*` environment variables unset, then validating a fresh
  `codira-bundle-official` install from PyPI.
- `0.1.16`: Complete Phase 13 by updating install and release documentation,
  replacing inherited release notes with the `1.0.0` rebrand release record,
  enabling published documentation, and running the final stale-reference
  audit.

## Purpose

This ledger records the executable migration from the current `repoindex`
project identity to the new `codira` identity.

It is intentionally checklist-based. During implementation, each completed
step must be checked off in this document so the migration state remains visible
and auditable.

## Fixed Decisions

- [x] Use `codira` as the new project name.
- [x] Treat the earlier `codera` spelling as a typo.
- [x] Use `pre-rebrand-snapshot` as the historical snapshot tag name.
- [x] Start the public `codira` release line at `v1.0.0` intentionally, even
  though the old `repoindex` line reached `v2.0.0`.
- [x] Publish the core distribution as `codira`.
- [x] Publish first-party distributions under the `codira-*` namespace.
- [x] Rename public APIs from `repoindex*` to `codira*`; do not keep the old
  public names as supported compatibility surfaces for the new project.
- [x] Keep the old `repoindex` GitHub repository public and archived after
  issue triage, instead of making it private.
- [x] Create a new public GitHub repository named `codira` with fresh history.

## Target Package Set

The intended published package set is:

- [x] `codira`
- [x] `codira-analyzer-python`
- [x] `codira-analyzer-json`
- [x] `codira-analyzer-c`
- [x] `codira-analyzer-bash`
- [x] `codira-backend-sqlite`
- [x] `codira-bundle-official`

The old package set must not appear in active package metadata after the rename:

- [x] `repoindex`
- [x] `repoindex-analyzer-python`
- [x] `repoindex-analyzer-json`
- [x] `repoindex-analyzer-c`
- [x] `repoindex-analyzer-bash`
- [x] `repoindex-backend-sqlite`
- [x] `repoindex-bundle-official`

## Target Public API Surface

The rebrand is a public API rename, not only a repository rename.

Required public surface changes:

- [x] CLI executable: `repoindex` -> `codira`.
- [x] Python import package: `repoindex` -> `codira`.
- [x] First-party analyzer import packages:
  - [x] `repoindex_analyzer_python` -> `codira_analyzer_python`
  - [x] `repoindex_analyzer_json` -> `codira_analyzer_json`
  - [x] `repoindex_analyzer_c` -> `codira_analyzer_c`
  - [x] `repoindex_analyzer_bash` -> `codira_analyzer_bash`
- [x] First-party backend import package:
  - [x] `repoindex_backend_sqlite` -> `codira_backend_sqlite`
- [x] Example plugin import packages:
  - [x] `repoindex_demo_analyzer` -> `codira_demo_analyzer`
  - [x] `repoindex_demo_backend` -> `codira_demo_backend`
- [x] Plugin entry-point groups:
  - [x] `repoindex.analyzers` -> `codira.analyzers`
  - [x] `repoindex.backends` -> `codira.backends`
- [x] Repository-local state directory: `.repoindex` -> `.codira`.
- [x] Generated version file path: `src/repoindex/_version.py` ->
  `src/codira/_version.py`.
- [x] Package data key: `repoindex = ["py.typed"]` ->
  `codira = ["py.typed"]`.
- [x] Documentation, examples, badges, scripts, release notes, and developer
  prompts use `codira` unless they intentionally describe archived history.

Intentional historical references to `repoindex` are allowed only when they
are clearly marked as historical.

## CLI Subcommand Rename Contract

The rebrand includes shortening subcommands while keeping them mnemonic.

Accepted command names:

- [x] `index` remains `index`.
- [x] `coverage` becomes `cov`.
- [x] `symbol` becomes `sym`.
- [x] `embeddings` becomes `emb`.
- [x] `calls` remains `calls`.
- [x] `refs` remains `refs`.
- [x] `audit-docstrings` becomes `audit`.
- [x] `context-for` becomes `ctx`.
- [x] `plugins` remains `plugins`.
- [x] `help` remains `help`.

Required CLI behavior:

- [x] `codira ctx` is the documented replacement for `repoindex context-for`.
- [x] `codira audit` is the documented replacement for
  `repoindex audit-docstrings`.
- [x] `codira cov` is the documented replacement for `repoindex coverage`.
- [x] `codira sym` is the documented replacement for `repoindex symbol`.
- [x] `codira emb` is the documented replacement for `repoindex embeddings`.
- [x] Help text, examples, tests, and docs use only the new command names.
- [x] No old subcommand aliases are retained unless a later decision explicitly
  adds a temporary compatibility phase.

## Phase 0 - Restore Tool Usability Before Rebranding

Goal:
`repoindex` must be usable as a local developer tool before the rebrand starts.
It must work both on this repository and on another repository.

Current observed blocker:

- [x] `source .venv/bin/activate && repoindex index` previously failed in this
  checkout with `ValueError: No language analyzers are registered for
  repoindex`.

Tasks:

- [x] Confirm the active `.venv` installation state.
- [x] Confirm whether first-party analyzer and backend distributions are
  installed in `.venv`.
- [x] Fix the local developer bootstrap or installation flow so the active
  `.venv` can discover the first-party analyzer and backend entry points.
- [x] Ensure `codira plugins --json` reports the expected first-party
  analyzers and backend from installed distributions.
- [x] Ensure `codira cov --json` works from this repository root.
  It currently reports incomplete coverage for `src/codira/py.typed`.
- [x] Ensure `codira index --full --json` works from this repository root.
- [x] Ensure `codira ctx "rename package metadata" --json` works from this
  repository root after the subcommand-shortening implementation, or
  `codira ctx "rename package metadata" --json` works before that
  implementation.
- [x] Run the same minimum tool-smoke sequence from one external repository:
  - [x] `codira plugins --json`
  - [x] `codira cov --json`
  - [x] `codira index --full --json`
  - [x] one context retrieval query
- [x] Add or update tests that would have caught missing analyzer discovery in
  the repository-local developer workflow.

Exit criteria:

- [x] `codira` can index and query this repository from the active `.venv`.
- [x] `codira` can index and query at least one external repository from the
  active `.venv`.
- [x] The fix is validated by the current repository contract.

Phase 0 implementation note:

- [x] The active `.venv` now points first-party editable installs at
  `../codira-split-repos/`.
- [x] `scripts/install_first_party_packages.py` supports `--package-root` so
  maintainers can intentionally target exported split repositories.
- [x] `tests/test_bootstrap_scripts.py` verifies the split-package-root install
  command plan.
- [ ] Decide whether `py.typed` files should be ignored by coverage or covered
  by a metadata analyzer before requiring full coverage.

## Phase 1 - Freeze And Audit The Starting State

Goal:
Record the last intentional `codira` state before modifying identity.

Tasks:

- [x] Run `git status --short` and account for every untracked or modified
  file.
- [x] Create or verify the `pre-rebrand-snapshot` tag.
- [x] Record the current commit SHA.
- [x] Record the `pre-rebrand-snapshot` tag SHA.
- [x] Record the old PyPI project cleanup state for all seven old package
  names.
- [x] Record the final seven new PyPI package names.
- [x] Confirm target names are available or intentionally reserved where
  package indexes are involved.
- [x] Confirm no pending release artifacts remain in:
  - [x] `dist/`
  - [x] `build/`
  - [x] `src/codira.egg-info/`
  - [x] `packages/*/dist/`
  - [x] `packages/*/build/`
  - [x] `packages/*/src/*.egg-info/`
  - [x] `.artifacts/`
  - [x] `.codira/`
  - [x] `src/codira/_version.py`
- [x] Run repository cleanup only through repository-approved tooling.

Exit criteria:

- [x] The starting state can be reconstructed from local Git and this ledger.
- [x] There are no stale local artifacts that can contaminate the rename.

Phase 1 audit record:

- [x] Current commit SHA after Phase 0: `8a9d4d382e5128022493999c8bb0e65dd5ab6284`.
- [x] `pre-rebrand-snapshot` resolves to
  `eb3d2a17c6c10f68b4379d7a5307883c2b955fcb`.
- [x] `git status --short` was clean before the Phase 1 ledger update.
- [x] `git clean-repo` removed ignored build, cache, and package metadata
  artifacts.
- [x] `source .venv/bin/activate && codira index --full --json` passed
  after cleanup with 93 indexed files and zero failures.
- [x] Protected ignored runtime/generated state remains by repository policy:
  - [x] `.codira/`
  - [x] `src/codira/_version.py`
- [x] These protected paths were intentionally still `repoindex` before the
  rebrand implementation. They became `.codira/` and
  `src/codira/_version.py` when `scripts/clean_repo.py` is updated in
  Phase 4.
- [x] PyPI JSON endpoint status for target names on 2026-04-11:
  - [x] `codira`: 404
  - [x] `codira-analyzer-python`: 404
  - [x] `codira-analyzer-json`: 404
  - [x] `codira-analyzer-c`: 404
  - [x] `codira-analyzer-bash`: 404
  - [x] `codira-backend-sqlite`: 404
  - [x] `codira-bundle-official`: 404
- [x] PyPI JSON endpoint status for old names on 2026-04-11:
  - [x] `repoindex`: 200, occupied by package `repoindex` version `0.15.2`
    with summary `A collection-aware metadata index for git repositories`.
  - [x] `repoindex-analyzer-python`: 404
  - [x] `repoindex-analyzer-json`: 404
  - [x] `repoindex-analyzer-c`: 404
  - [x] `repoindex-analyzer-bash`: 404
  - [x] `repoindex-backend-sqlite`: 404
  - [x] `repoindex-bundle-official`: 404

## Phase 2 - Triage GitHub Issues

Goal:
Preserve only useful active work in the new `codira` issue tracker.

Tasks:

- [x] Keep the old `repoindex` repository public while issue triage is in
  progress.
- [x] Classify each current `repoindex` issue as:
  - [x] still relevant to `codira`
  - [x] historical only
  - [x] obsolete
- [x] Pre-create matching labels and milestones in `codira` where preserving
  them matters.
- [x] Transfer only still-relevant open issues in Phase 9 after the new
  `codira` repository exists.
- [x] Leave closed, obsolete, and historical issues in the archived
  `repoindex` repository.

Exit criteria:

- [x] The new `codira` issue tracker contains only intentional active work.
- [x] The old `repoindex` issue tracker remains available for history.

Phase 2 classification record:

- [x] Open issues to transfer to `codira` after repository creation:
  - [x] `#3` - fallback analyzers for whole-file and fragment parse gaps
  - [x] `#4` - Ruff interface and complexity ignore cleanup
  - [x] `#5` - documentation retrieval channel; update references from
    `context-for` to `ctx` during the rebrand
  - [x] `#6` - documentation-audit plugin conventions; update references from
    `audit-docstrings` to `audit` during the rebrand
  - [x] `#8` - Makefile analyzer plugin
  - [x] `#14` - config-first analyzer-aware coverage roots
  - [x] `#15` - deterministic capability contract and analyzer declarations
- [x] Closed historical issues to leave in archived `codira`:
  - [x] `#1` - real embeddings with deterministic invalidation
  - [x] `#2` - pluggable language analyzers
  - [x] `#7` - JSON language analyzer plugin
  - [x] `#9` - capability-driven signal layer
  - [x] `#10` - native call-graph retrieval producer
  - [x] `#11` - optional plugin extraction and package topology
  - [x] `#12` - replaceable Python analyzer and backend
  - [x] `#13` - monorepo analyzer fallback removal
- [x] Obsolete issues: none identified.
- [x] No labels or milestones were present on the selected open issues, so no
  pre-created `codira` labels or milestones were needed.

## Phase 3 - Create The New Public GitHub Repository

Goal:
Create a clean target remote without disturbing the old repository location.

Tasks:

- [x] Create a new public GitHub repository named `codira`.
- [x] Do not rename the old `repoindex` repository in place.
- [x] Do not transfer the old `repoindex` repository.
- [x] Do not create a new repository at the old `repoindex` location after any
  rename or transfer operation.
- [ ] Configure the new repository with the expected default branch, branch
  protection, Actions settings, and trusted publishing settings if used.

Exit criteria:

- [x] Old repository: `codira`, public, unchanged.
- [x] New repository: `codira`, public, ready to receive fresh history.

Phase 3 repository record:

- [x] Repository URL: `https://github.com/marco0560/codira`.
- [x] Visibility: public.
- [x] Archived: false.
- [x] Default branch is empty until fresh history is pushed.

## Phase 4 - Apply The Local Rebrand

Goal:
Rename the project in a local working copy while keeping the change minimal and
reviewable.

Tasks:

- [x] Work in a copy or branch dedicated to the rebrand.
- [x] Rename `src/repoindex/` to `src/codira/`.
- [x] Rename package directories under `packages/`:
  - [x] `packages/repoindex-analyzer-python/` ->
    `packages/codira-analyzer-python/`
  - [x] `packages/repoindex-analyzer-json/` ->
    `packages/codira-analyzer-json/`
  - [x] `packages/repoindex-analyzer-c/` ->
    `packages/codira-analyzer-c/`
  - [x] `packages/repoindex-analyzer-bash/` ->
    `packages/codira-analyzer-bash/`
  - [x] `packages/repoindex-backend-sqlite/` ->
    `packages/codira-backend-sqlite/`
  - [x] `packages/repoindex-bundle-official/` ->
    `packages/codira-bundle-official/`
- [x] Rename first-party package source roots under each package.
- [x] Rename example plugin directories and source roots.
- [x] Update root `pyproject.toml`.
- [x] Update every package `pyproject.toml`.
- [x] Update package dependencies and pins from `repoindex*` to `codira*`.
- [x] Update all imports from `repoindex` to `codira`.
- [x] Update all imports from `repoindex_*` first-party packages to
  `codira_*`.
- [x] Update plugin discovery entry-point groups to `codira.analyzers` and
  `codira.backends`.
- [x] Update registry/discovery code and error messages.
- [x] Update the local state directory from `.repoindex` to `.codira`.
- [x] Update `scripts/clean_repo.py` protected paths from `.repoindex` and
  `src/repoindex/_version.py` to `.codira` and `src/codira/_version.py`.
- [x] Update scripts that own package inventories, release plans, split
  manifests, bootstrap, cleanup, and Git aliases.
- [x] Update tests to assert the new package names, imports, entry points, CLI
  command names, cache directory, and error messages.
- [x] Update docs, README, MkDocs config, badges, examples, release docs,
  architecture docs, ADR references, and developer prompts.
- [x] Keep one explicit historical note in the new README:
  `This project was initially developed under the working name repoindex and
  was renamed to codira before the codira public release.`

Exit criteria:

- [x] No active code, metadata, test, script, or documentation reference still
  uses `repoindex` except approved historical notes.
- [x] Public APIs use `codira*`.

## Phase 5 - Apply CLI Subcommand Shortening

Goal:
Ship the new project identity with the shorter mnemonic command set.

Tasks:

- [x] Update CLI parser command names.
- [x] Update dispatch logic for the new command names.
- [x] Update CLI usage examples.
- [x] Update README command walkthroughs.
- [x] Update AGENTS-style workflow snippets and developer prompts.
- [x] Update tests for command parsing and CLI behavior.
- [x] Update shell aliases and helper scripts from old commands to new
  commands.
- [x] Confirm `codira --help` lists the new command set.
- [x] Confirm old command names are absent unless explicitly approved later.

Exit criteria:

- [x] `codira ctx`, `codira audit`, `codira cov`, `codira sym`, and
  `codira emb` work.
- [x] The documented CLI surface contains only the accepted new subcommand
  names.

## Phase 6 - Drift Audit

Goal:
Find and classify every stale old-name reference before release.

Tasks:

- [x] Run `rg -n "repoindex|repoindex-|repoindex_|\\.repoindex|REPOINDEX"`.
- [x] Run `rg -n "context-for|audit-docstrings|codira coverage|codira symbol|codira embeddings"`
  and classify remaining old subcommand references.
- [x] Inspect every remaining hit manually.
- [x] Convert active references to `codira`.
- [x] Mark intentional historical references with local context explaining why
  they remain.
- [x] Verify package metadata names are exactly the accepted target names.
- [x] Verify dependency metadata points only to `codira` packages.
- [x] Verify entry-point groups are only `codira.analyzers` and
  `codira.backends`.

Exit criteria:

- [x] Stale-reference search has no unexplained hits.
- [x] Intentional historical references are few, explicit, and non-operational.

## Phase 7 - Local Validation

Goal:
Validate the renamed tree through the current repository contract and release
rehearsals.

Required repository checks:

```bash
source .venv/bin/activate
black --check src scripts tests
ruff check src scripts tests
mypy src scripts tests
pytest -q
```

Additional rename-specific checks:

- [x] Extend the required checks to include `packages` and `examples` where
  rename-sensitive code lives.
- [x] Build every distribution.
- [x] Run artifact validation on every generated distribution.
- [x] Install the core package locally in an isolated install target.
- [x] Install the bundle package locally in an isolated install target.
- [x] Verify `codira --help`.
- [x] Verify `codira -V`.
- [x] Verify `codira plugins --json`.
- [x] Verify `codira index --full --json` in this repository.
- [x] Verify `codira ctx "package metadata rename" --json` in this repository.
- [x] Verify plugin discovery from installed artifacts, not source-tree
  leakage.

Exit criteria:

- [x] Required repository checks pass.
- [x] Build and install rehearsals pass.
- [x] The installed CLI and plugin discovery work outside the source tree.

## Phase 8 - Create Fresh Public History

Goal:
Publish a clean `codira` history without old `repoindex` commit history.

Tasks:

- [x] Remove old `.git` metadata only in the prepared `codira` copy, not in the
  source `repoindex` repository.
- [x] Run `git init` in the prepared `codira` copy.
- [x] Create one initial commit containing the fully renamed, validated tree.
- [x] Add the new `codira` GitHub remote.
- [x] Push `main`.
- [x] Create and push tag `v1.0.0`.

Exit criteria:

- [x] The public `codira` repository starts from the renamed tree.
- [x] The first public tag is `v1.0.0`.

## Phase 9 - Transfer Selected Issues

Goal:
Move only intentionally active issue work to `codira`.

Tasks:

- [x] Transfer selected open issues from `repoindex` to `codira`.
- [x] Verify transferred issues have comments and assignees.
- [x] Verify labels and milestones are preserved where intended.
- [x] Verify old issue URLs redirect to the transferred issues where GitHub
  supports that redirect.

Exit criteria:

- [x] Active issue work lives in `codira`.
- [x] Historical issue work remains in `repoindex`.

Phase 9 issue transfer record:

- [x] `marco0560/repoindex#3` transferred to `marco0560/codira#1`.
- [x] `marco0560/repoindex#4` transferred to `marco0560/codira#2`.
- [x] `marco0560/repoindex#5` transferred to `marco0560/codira#3`.
- [x] `marco0560/repoindex#6` transferred to `marco0560/codira#4`.
- [x] `marco0560/repoindex#8` transferred to `marco0560/codira#5`.
- [x] `marco0560/repoindex#14` transferred to `marco0560/codira#6`.
- [x] `marco0560/repoindex#15` transferred to `marco0560/codira#7`.
- [x] `gh issue list --repo marco0560/repoindex --state open` returned no
  open issues after transfer.
- [x] `gh issue list --repo marco0560/codira --state open` returned the seven
  expected transferred issues.
- [x] No transferred issue had labels, milestones, or assignees to preserve.
- [x] Existing comments were preserved on transferred issues `#3`, `#4`, and
  `#5`.
- [x] GitHub redirect samples:
  - [x] `https://github.com/marco0560/repoindex/issues/3` redirects to
    `https://github.com/marco0560/codira/issues/1`.
  - [x] `https://github.com/marco0560/repoindex/issues/15` redirects to
    `https://github.com/marco0560/codira/issues/7`.

## Phase 10 - Archive The Old Repository

Goal:
Freeze the old identity as historical reference.

Tasks:

- [x] Update the old `repoindex` README with:
  - [x] archived status
  - [x] link to the new `codira` repository
  - [x] note that active development moved to `codira`
  - [x] note that the rename avoided conflict and confusion around the old
    `repoindex` package identity
- [x] Archive the old `repoindex` repository on GitHub.
- [x] Keep the old repository public.

Exit criteria:

- [x] Old history and issues remain visible.
- [x] Users landing on the old repository can find `codira`.

Phase 10 archive record:

- [x] README archive notice added before the old repository was archived.
- [x] Old repository visibility before archive: public.
- [x] Old repository default branch before archive: `main`.
- [x] Old repository archived status after archive: true.

## Phase 11 - TestPyPI Rehearsal

Goal:
Prove the package set resolves from a package index before touching real PyPI.

Publish to TestPyPI in dependency order:

1. [x] `codira-analyzer-python`
2. [x] `codira-analyzer-json`
3. [x] `codira-analyzer-c`
4. [x] `codira-analyzer-bash`
5. [x] `codira-backend-sqlite`
6. [x] `codira`
7. [x] `codira-bundle-official`

Fresh-environment checks:

- [x] `pip install codira-bundle-official` from TestPyPI with PyPI as the
  extra index for third-party dependencies.
- [x] `codira --help`
- [x] `codira -V`
- [x] `codira plugins --json`
- [x] `codira index --full --json`
- [x] `codira ctx "package metadata rename" --json`
- [x] Confirm no installed distribution depends on `repoindex`.

Exit criteria:

- [x] TestPyPI install and runtime smoke tests pass from a fresh environment.

Phase 11 TestPyPI record:

- [x] Built wheel and sdist artifacts for all seven distributions.
- [x] `twine check` passed for all generated artifacts.
- [x] TestPyPI project pages:
  - [x] `https://test.pypi.org/project/codira-analyzer-python/1.0.0/`
  - [x] `https://test.pypi.org/project/codira-analyzer-json/1.0.0/`
  - [x] `https://test.pypi.org/project/codira-analyzer-c/1.0.0/`
  - [x] `https://test.pypi.org/project/codira-analyzer-bash/1.0.0/`
  - [x] `https://test.pypi.org/project/codira-backend-sqlite/1.0.0/`
  - [x] `https://test.pypi.org/project/codira/1.0.0/`
  - [x] `https://test.pypi.org/project/codira-bundle-official/1.0.0/`
- [x] Fresh environment:
  `/tmp/codira-testpypi-venv`.
- [x] Install command:
  `python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ codira-bundle-official`.
- [x] Installed package set included `codira==1.0.0` and all six first-party
  `codira-*==1.0.0` distributions.
- [x] `pip check` reported no broken requirements.
- [x] Metadata search found no installed `repoindex` distribution and no
  `Requires-Dist: repoindex` dependency metadata.
- [x] Runtime smoke tests passed from the fresh environment:
  - [x] `codira --help`
  - [x] `codira -V`
  - [x] `codira plugins --json`
  - [x] `codira index --full --json`
  - [x] `codira ctx "package metadata rename" --json`

## Phase 12 - Real PyPI Release

Goal:
Publish the validated `codira` package set to PyPI.

Publish to PyPI in dependency order:

1. [x] `codira-analyzer-python`
2. [x] `codira-analyzer-json`
3. [x] `codira-analyzer-c`
4. [x] `codira-analyzer-bash`
5. [x] `codira-backend-sqlite`
6. [x] `codira`
7. [x] `codira-bundle-official`

Tasks:

- [x] Do not publish the bundle before its dependencies exist on PyPI.
- [x] Do not reuse any failed version number in a package namespace.
- [x] Verify each PyPI project page after upload.
- [x] Verify `pip install codira-bundle-official` in a fresh environment.
- [x] Verify `codira --help`.
- [x] Verify `codira plugins --json`.
- [x] Verify no dependency metadata points to `repoindex`.

Exit criteria:

- [x] The real PyPI release is installable through `codira-bundle-official`.
- [x] The installed command is `codira`.
- [x] The installed public API is `codira*`.

Phase 12 blocker record:

- [x] Real PyPI project availability was checked before upload; all seven
  target names returned 404.
- [x] The first upload attempted was
  `codira-analyzer-python==1.0.0`.
- [x] PyPI rejected the upload with `403 Forbidden`.
- [x] `https://pypi.org/pypi/codira-analyzer-python/json` still returned 404
  after the failed upload, so no partial project creation was observed.
- [x] Resolved PyPI upload authorization by unsetting `TWINE_USERNAME` and
  `TWINE_PASSWORD` so `twine` used the real PyPI credentials from
  `~/.pypirc`.

Phase 12 PyPI release record:

- [x] Real PyPI project pages:
  - [x] `https://pypi.org/project/codira-analyzer-python/1.0.0/`
  - [x] `https://pypi.org/project/codira-analyzer-json/1.0.0/`
  - [x] `https://pypi.org/project/codira-analyzer-c/1.0.0/`
  - [x] `https://pypi.org/project/codira-analyzer-bash/1.0.0/`
  - [x] `https://pypi.org/project/codira-backend-sqlite/1.0.0/`
  - [x] `https://pypi.org/project/codira/1.0.0/`
  - [x] `https://pypi.org/project/codira-bundle-official/1.0.0/`
- [x] Fresh environment:
  `/tmp/codira-pypi-venv`.
- [x] Install command:
  `python -m pip install codira-bundle-official`.
- [x] Installed package set included `codira==1.0.0` and all six first-party
  `codira-*==1.0.0` distributions.
- [x] `pip check` reported no broken requirements.
- [x] Metadata search found no installed `repoindex` distribution and no
  `Requires-Dist: repoindex` dependency metadata.
- [x] Runtime smoke tests passed from the fresh environment:
  - [x] `codira --help`
  - [x] `codira -V`
  - [x] `codira plugins --json`
  - [x] `codira index --full --json`
  - [x] `codira ctx "package metadata rename" --json`

## Phase 13 - Post-Release Cleanup

Goal:
Remove local migration leftovers and update downstream references.

Tasks:

- [x] Verify GitHub README badges and install instructions.
- [x] Verify published documentation links.
- [x] Verify release notes mention the rebrand and version reset.
- [x] Update local developer aliases and shell snippets.
- [x] Update any external documentation controlled by the maintainer.
- [x] Remove temporary release notebooks or archive them under `docs/process`
  if they are still useful.
- [x] Run one final stale-reference audit.

Exit criteria:

- [x] The migration is complete.
- [x] Remaining `repoindex` references are historical and intentional.

Phase 13 cleanup record:

- [x] README install instructions now include the published
  `pip install codira-bundle-official` path and the core-only
  `pip install codira` path.
- [x] `docs/getting_started.md` now starts with the published package install
  path before source-tree contributor setup.
- [x] `docs/release/checklist.md` and
  `docs/process/python-package-publishing-walkthrough.md` now describe the
  coordinated `codira` package release flow instead of the old `v2.0.0`
  split-first plan as active guidance.
- [x] `CHANGELOG.md` now records `1.0.0` as the first public `codira` release,
  including the rebrand from `repoindex` and the intentional version reset.
- [x] GitHub Pages was enabled for `marco0560/codira` with Actions deployments.
- [x] Fresh Docs workflow run `24292298099` completed successfully.
- [x] `https://marco0560.github.io/codira/` returned HTTP 200 after the docs
  deployment.
- [x] README badge targets were checked:
  - [x] `https://github.com/marco0560/codira/actions/workflows/ci.yml`
    returned HTTP 200.
  - [x] `https://pypi.org/project/codira-bundle-official/1.0.0/` returned
    HTTP 200.
- [x] No temporary release notebooks were present in the checkout.
- [x] Final active stale-reference audit found only intentional historical
  `repoindex` references in `CHANGELOG.md` and release-process context, plus
  historical migration/ADR/process documents.
- [x] Local documentation validation:
  `python -m mkdocs build --strict`.

## Validation Contract

Every implementation slice must end with the repository contract unless the
slice only changes planning documentation.

Repository contract:

```bash
source .venv/bin/activate
black --check src scripts tests
ruff check src scripts tests
mypy src scripts tests
pytest -q
```

Rename-sensitive slices must also validate the relevant package and example
paths.

## Commit Policy

Use small atomic commits while implementing the migration. Each commit should
leave the tree in a coherent state and should update this ledger when it
completes a listed step.

Do not combine unrelated behavior changes with the rebrand unless they are
required to keep `codira` or `codira` usable as a tool during migration.
