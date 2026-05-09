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
3. Confirm `codira -V` reports the core package and installed plugin
   distribution versions.
4. Build wheel and sdist artifacts for every distribution.
5. Run `twine check` for every artifact.
6. Upload to TestPyPI in dependency order.
7. Run a fresh TestPyPI smoke test with `codira-bundle-official`.
8. Upload to PyPI in dependency order.
9. Run a fresh PyPI smoke test with `codira-bundle-official`.
