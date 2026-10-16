# Release Process

`codira` uses a conservative main-branch release flow backed by
`semantic-release`.

## Local checks

Before pushing release-bearing commits to `main`, verify the repository is in a
publishable state:

```bash
python scripts/benchmark_release.py
```

```bash
git release-audit
```

The benchmark command runs the release Hyperfine plan for indexing, context
retrieval, and docstring audit operations. It writes JSON results to
`.artifacts/benchmarks/release/release-hyperfine.json`.

That audit checks:

- clean working tree
- upstream alignment when an upstream is configured
- latest reachable semantic tag ancestry
- `CHANGELOG.md` consistency
- semantic-release baseline visibility

Before a coordinated package publication, also run the installed-wheel
host-target rehearsal documented in the
[release checklist](checklist.md#standalone-host-target-rehearsal). It is the
release evidence that the standalone host model still supports workspace MCP
routing, old declared target Python syntax, and shared model reuse without
monorepo imports.

Direct `git push` to `main` is blocked by the pre-push hook once the repo-local
hooks are installed.

Use:

```bash
git rel
```

That guarded path first builds the published documentation in strict mode,
before any fetch, pull or push. It repeats that check after pulling so incoming
changes cannot bypass it, then runs the release audit and previews semantic-release with the
scoped GitHub environment, and then pushes with the expected temporary bypass
variables.

## Publishing model

Releases are created by GitHub Actions after commits land on `main`.

For a release that changes similarity-index configuration or artifact formats,
the release notes must lead with the breaking reset path: regenerate a v1
configuration with `codira config init --force`, select an installed similarity
index, run `codira emb reset` for incompatible derived state, and index again.
Profile-only changes are not persisted-artifact migrations and do not require a
rebuild.

The current release workflow:

1. runs on pushes to `main`
2. runs `semantic-release`
3. creates the next version tag when commits warrant a release
4. updates `CHANGELOG.md`
5. publishes the GitHub release

## Manual tags

Manual release-tag creation is not part of the normal workflow.

Use manual tag creation only for repair operations or exceptional recovery.

## Documentation gate

Run `uv run python scripts/check_docs.py` from the checkout root to reproduce the
Docs workflow's strict build locally. The quality preflight and full repository
gate include this check. Generated HTML is removed automatically; build failures
and warnings remain visible and stop `git rel` before publication.

Documentation-relative links must stay inside `docs/`, not merely inside the
Git checkout. Cite source files using immutable GitHub commit URLs. Describe
ignored `.artifacts/` measurements as plain code-formatted local paths: they are
operator evidence, not files published by the documentation site. Missing files,
unrecognized local links and absolute filesystem links remain fatal warnings.

The installed `git rel` alias requests the `docs` dependency extra automatically.
After updating a checkout, refresh its aliases with
`uv run python scripts/install_repo_git_config.py`. Existing aliases still call
the guarded release entry point, but may require a prior `uv sync --extra docs`.
