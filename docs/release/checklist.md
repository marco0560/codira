# Release Checklist

## Monorepo Staging

1. Ensure the working tree is clean.
2. Run `uv run python scripts/run_repo_tool.py ruff check src scripts tests packages`.
3. Run `uv run python scripts/run_repo_tool.py ruff format --check src scripts tests packages`.
4. Run `uv run python scripts/run_repo_tool.py mypy src scripts tests packages`.
5. Run `uv run python scripts/run_repo_tool.py pytest -q`.
6. Run `uv run python scripts/benchmark_release.py`.
7. Review `.artifacts/benchmarks/release-hyperfine.json` for unexpected
   regressions.
8. Run `git release-audit`.
9. Push the releasable staging commits with `git rel`.

## Coordinated Package Release

1. Verify every distribution version is the intended coordinated release
   version.
2. Align `codira-bundle-official` pins to the coordinated package set.
3. Verify `README.md` uses absolute HTTPS image URLs for PyPI-rendered images;
   relative repository paths such as `docs/badges/*.png` break on PyPI project
   pages.
4. Confirm `codira -V` reports the core package and installed plugin
   distribution versions.
5. Build wheel and sdist artifacts for every distribution.
6. Run `twine check` for every artifact.
7. Upload to TestPyPI in dependency order.
8. Run a fresh TestPyPI smoke test with `codira-bundle-official`.
9. Verify TestPyPI metadata for `codira` includes the absolute badge URL in
   the long description before uploading the same artifacts to PyPI.
10. Upload to PyPI in dependency order.
11. Run a fresh PyPI smoke test with `codira-bundle-official`.

## Installer release rehearsal

Before a coordinated release, validate the two user-facing artifacts without
allowing the rehearsal to contact a package index:

```bash
uv run python scripts/rehearse_installer_installs.py \
  --wheel-dir /tmp/codira-installer-wheels \
  --venv-dir /tmp/codira-installer-venv \
  --plan-dir /tmp/codira-installer-plans
```

The rehearsal builds `codira-installer` and `codira-bundle-official`, installs
their wheels with `uv pip install --no-index --no-deps`, verifies bundle
metadata, and exports standalone, selected-feature, core-only, and
local-checkout plans. It is deliberately not a PyPI upload rehearsal; TestPyPI
and PyPI uploads remain explicit operator actions above.

Build and check both installer-facing wheel and source artifacts as part of the
same release evidence. In an offline or locked development environment, use
the repository's synchronized build backend rather than requesting a build
isolation download:

```bash
uv run python -m build --no-isolation --wheel --sdist --outdir /tmp/codira-installer-artifacts packages/codira-installer
uv run python -m build --no-isolation --wheel --sdist --outdir /tmp/codira-installer-artifacts packages/codira-bundle-official
uv run python -m twine check /tmp/codira-installer-artifacts/*
```

## Standalone host-target rehearsal

Before publishing the core and first-party wheels, rehearse their installation
outside the checkout:

```bash
uv run python scripts/rehearse_release_installs.py \
  --wheel-dir /tmp/codira-release-wheels \
  --install-dir /tmp/codira-release-site-packages
```

The probe runs only from the installed wheel directory. It verifies first-party
discovery, analyzes a Python 3.8-declared target fixture from the host runtime,
resolves a workspace-scoped MCP startup binding, and proves two isolated
runtimes reuse one verified shared-model blob.
