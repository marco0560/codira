# Distribution repository export manifest

The canonical monorepo remains the development source of truth under
[ADR-014](../adr/ADR-014-canonical-monorepo-generated-distribution-repositories.md).
Exports are generated distribution/rehearsal trees; routine source development
stays here. These tools remain maintained compatibility contracts, not a plan
to move development into autonomous repositories.

## Source of truth

`scripts/future_repo_split_manifest.py` declares ownership;
`scripts/future_repo_export.py` materializes it, with coverage in
`tests/test_future_repo_split_manifest.py` and `tests/test_future_repo_export.py`.
The inventory below reflects the current executable manifest, not every
first-party distribution in `packages/`. Do not assume an unlisted package can
be exported by this helper. Expanding that contract requires a separate change.

## Declared exports

| Repository | Exported package paths | Operational paths retained in core |
| --- | --- | --- |
| `codira-analyzer-python` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-analyzer-json` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-analyzer-c` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-analyzer-cpp` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-analyzer-rust` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-analyzer-javascript` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-analyzer-typescript` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-analyzer-go` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-analyzer-bash` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-analyzer-markdown` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-analyzer-text` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-documentation-audit-rustdoc` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-documentation-audit-jsdoc` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-documentation-audit-tsdoc` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-documentation-audit-go-doc-comments` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-backend-sqlite` | `README.md`, `pyproject.toml`, `src/`, `tests/` | `src/codira/indexer.py`, `tests/test_plugins.py` |
| `codira-backend-duckdb` | `README.md`, `pyproject.toml`, `src/`, `tests/` | `tests/test_plugins.py` |
| `codira-installer` | `README.md`, `pyproject.toml`, `src/`, `tests/` | None declared |
| `codira-bundle-official` | `README.md`, `pyproject.toml`, `tests/` | `tests/test_plugins.py` |

The `codira` export declares these monorepo paths:

- `.gitignore`
- `.github/workflows/ci.yml`
- `.github/workflows/commit-message-check.yml`
- `.github/workflows/docs.yml`
- `.github/workflows/release.yml`
- `.pre-commit-config.yaml`
- `.releaserc.json`
- `CHANGELOG.md`
- `LICENSE`
- `README.md`
- `docs/`
- `examples/`
- `mkdocs.yml`
- `package-lock.json`
- `package.json`
- `pyproject.toml`
- `scripts/`
- `src/codira/`
- `tests/`

## Rehearsal

Inspect the declared export before materializing it into a fresh disposable
workspace beneath the designated scratch root:

```bash
uv run python scripts/future_repo_export.py codira-analyzer-python
uv run python scripts/future_repo_export.py codira-analyzer-python \
  --destination-root '/home/marco/Personalia/Progetti/.Temp/codira-split-<fresh-identity>'
```

The helper refuses an occupied destination and excludes generated Python
artifacts. This scratch export is disposable; durable release artifacts must
use a durable release location. See [the CI contract](multirepo-ci-decomposition.md)
for declared validation commands and the local-core rehearsal boundary.
