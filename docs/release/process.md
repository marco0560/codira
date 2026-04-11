# Release Process

`codira` uses a conservative main-branch release flow backed by
`semantic-release`.

## Local checks

Before pushing release-bearing commits to `main`, verify the repository is in a
publishable state:

```bash
git release-audit
```

That audit checks:

- clean working tree
- upstream alignment when an upstream is configured
- latest reachable semantic tag ancestry
- `CHANGELOG.md` consistency
- semantic-release baseline visibility

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

The current release workflow:

1. runs on pushes to `main`
2. runs `semantic-release`
3. creates the next version tag when commits warrant a release
4. updates `CHANGELOG.md`
5. publishes the GitHub release

## Manual tags

Manual release-tag creation is not part of the normal workflow.

Use manual tag creation only for repair operations or exceptional recovery.
