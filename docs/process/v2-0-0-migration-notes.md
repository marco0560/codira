# v2.0.0 Migration Notes

## Purpose

This note records the intended user-facing breaking changes and migration path
for the clean `v2.0.0` packaging release.

It is a release-planning document, not a promise that `v2.0.0` is ready to
publish from the current monorepo checkout.

## Scope

The `v2.0.0` release finalizes the packaging migration described by:

* `ADR-011`
* `ADR-012`
* `ADR-013`

It assumes:

* the multirepo split has been performed
* `#13` has removed checkout-local fallback behavior
* the first-party package set has been validated through release rehearsals

## Breaking Changes

### 1. Defaults no longer live in core

`codira` remains the core platform package, but the default runtime
implementations are no longer owned by that package:

* Python analyzer
* JSON analyzer
* SQLite backend

Those implementations are provided through first-party plugin distributions and
discovered through entry points.

### 2. Installed-package discovery becomes the only supported path

After `#13`, `codira` no longer relies on sibling checkout loading or
monorepo-local fallback imports for first-party analyzers or backends.

If a required first-party plugin is not installed, `codira` fails with an
explicit install hint instead of silently finding code from the checkout.

### 3. Source-tree local bundle assumptions are not a supported end-user model

Before publication, a source checkout may still require local editable installs
for the extracted first-party packages.

The `v2.0.0` contract is different:

* published package names are the source of truth
* end users should install published distributions, not local `packages/` paths

### 4. The first-party package set is explicit

The intended published first-party package set is:

* `codira`
* `codira-analyzer-python`
* `codira-analyzer-json`
* `codira-analyzer-c`
* `codira-analyzer-bash`
* `codira-backend-sqlite`
* `codira-bundle-official`

## Stable Install Model After v2.0.0

### Recommended end-user install

```bash
pip install codira-bundle-official
```

### Compatible umbrella surface

```bash
pip install "codira[bundle-official]"
```

This compatibility surface is only valid once the published package metadata
actually resolves the first-party plugin distributions through standard package
indexes.

### Source-tree contributor workflow

Source-tree editable installs remain a contributor workflow, not an end-user
install contract. During development from a checkout, use the repository-owned
helper:

```bash
python scripts/install_first_party_packages.py \
  --python "$VIRTUAL_ENV/bin/python" \
  --include-core
```

Add `--core-extra semantic` when the embedding stack is required.

## Migration Guidance

### If you currently install only `codira`

After `v2.0.0`, core-only installation does not imply the default backend or
default analyzers are available.

Install either:

* `codira-bundle-official`
* or the individual first-party packages you need

### If you currently rely on source checkout behavior

Move to explicit installed packages. Do not rely on:

* sibling package directories in a monorepo checkout
* implicit import visibility from a development workspace
* old assumptions that built-in defaults live inside `codira`

### If you integrate with plugin discovery

Expect plugin resolution to depend on installed distributions and entry points
only. Missing-package failures are part of the intended operator contract.

## Operator Checklist

Before treating an environment as migrated, verify:

1. `codira plugins` shows the expected backend and analyzers from installed distributions.
2. `codira index` succeeds without sibling-checkout assumptions.
3. `codira cov` reports the expected active analyzer environment.
4. The install path used matches the published-package model or the documented source-tree helper.

## Maintainer Notes

The final `v2.0.0` publish must happen from the split repositories. The
monorepo is only the staging/export source for the package set.

Before publication, maintainers must verify:

* every split repository owns exactly one distribution
* every first-party distribution publishes `2.0.0`
* `codira-bundle-official` pins the matching `2.0.0` package set
* TestPyPI installation of `codira-bundle-official` works in a fresh
  environment
* `codira -V` reports the core version and installed first-party plugin
  distribution versions
