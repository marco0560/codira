# Release Checklist

## Monorepo Staging

1. Ensure the working tree is clean.
2. Run `source .venv/bin/activate`.
3. Run `black --check src scripts tests packages`.
4. Run `ruff check src scripts tests packages`.
5. Run `mypy src scripts tests packages`.
6. Run `pytest -q`.
7. Run `git release-audit`.
8. Push the releasable staging commits with `git rel`.

## v2.0.0 Split-First Gate

1. Export the accepted split repository set from the monorepo manifest.
2. Create or update the real split repositories from the exports.
3. Verify each split repository builds and tests in isolation.
4. Verify the core repository integration tests install first-party packages as
   artifacts, not sibling source trees.
5. Set every first-party distribution to the coordinated `2.0.0` release.
6. Align `codira-bundle-official` pins to the `2.0.0` package set.
7. Confirm `codira -V` reports the core package and installed plugin
   distribution versions.
8. Build artifacts from the split repositories.
9. Upload to TestPyPI in dependency order.
10. Run a fresh TestPyPI smoke test with `codira-bundle-official`.
11. Upload to PyPI in dependency order.
12. Run a fresh PyPI smoke test with `codira-bundle-official`.
