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

## Coordinated Package Release

1. Verify every distribution version is the intended coordinated release
   version.
2. Align `codira-bundle-official` pins to the coordinated package set.
3. Confirm `codira -V` reports the core package and installed plugin
   distribution versions.
4. Build wheel and sdist artifacts for every distribution.
5. Run `twine check` for every artifact.
6. Upload to TestPyPI in dependency order.
7. Run a fresh TestPyPI smoke test with `codira-bundle-official`.
8. Upload to PyPI in dependency order.
9. Run a fresh PyPI smoke test with `codira-bundle-official`.
