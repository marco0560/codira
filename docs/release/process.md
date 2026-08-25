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
`.artifacts/benchmarks/release-hyperfine.json`.

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

That guarded path runs the release audit and then pushes with the expected
temporary bypass variables.

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
