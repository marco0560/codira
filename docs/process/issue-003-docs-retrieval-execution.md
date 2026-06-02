# Issue 003 Documentation Retrieval Channel Execution

This ledger tracks implementation of issue #3: adding a first-class
documentation retrieval channel to `ctx`.

## Scope

In scope:

- Add documentation artifacts as a backend-neutral analyzer output.
- Index all non-excluded Markdown files as deterministic heading sections.
- Index Python module docstrings as module-level documentation artifacts.
- Persist and query documentation artifacts consistently in SQLite, DuckDB, and
  the in-memory contract backend.
- Retrieve documentation through a distinct `docs` channel in `ctx`.
- Use dedicated documentation embeddings instead of mixing documentation text
  into the symbol embedding pool.
- Expose documentation provenance in JSON and explain output.

Out of scope for V1:

- Function, class, and method docstring retrieval.
- Arbitrary comment-block harvesting.
- Generic C/C++ block comments.
- Rustdoc, Doxygen, reStructuredText, or other non-Markdown documentation
  formats.
- A docs-only CLI command.

## Phase Ledger

| Phase | Status | Evidence | Commit |
|-------|--------|----------|--------|
| 0. Scope and execution ledger | In progress | Ledger created. | Pending |
| 1. Models and analyzer contract | Complete | Added `DocumentationArtifact`, documentation literals, and shared row aliases. `uv run ruff check src/codira/models.py src/codira/types.py`; `uv run ruff format --check src/codira/models.py src/codira/types.py`. | Pending |
| 2. Source extraction | Pending | Add Markdown section analyzer and Python module-doc artifacts. | Pending |
| 3. Backend persistence and embeddings | Pending | SQLite, DuckDB, and in-memory backends persist/query docs and doc embeddings. | Pending |
| 4. `ctx` retrieval and output | Pending | `docs` channel, result union, intent weighting, provenance, and explain output. | Pending |
| 5. Validation and cleanup | Pending | Full validation and ledger closure. | Pending |

## Decisions

- Documentation results participate in unified `top_matches` as typed results.
- Documentation storage is dedicated and distinct from symbol storage.
- Markdown stable IDs use source kind, repo-relative path, normalized heading
  path, and deterministic ordinal.
- Markdown segmentation is heading-based; front matter is ignored, and fenced
  code blocks stay inside their owning section.
- Documentation retrieval is intent-weighted: strong for architecture,
  navigation, process, setup, release, configuration, API contract, and
  rationale queries; conservative for runtime behavior, debugging, bug fixing,
  and tests.
- Backend parity is mandatory for SQLite, DuckDB, and the in-memory backend.

## Phase Notes

### Phase 0

- Created this ledger before behavior changes.
- Worktree was clean before the ledger was added.

### Phase 1

- Added the backend-neutral documentation artifact model.
- Extended `AnalysisResult` with ordered documentation artifacts while keeping
  the default empty for existing analyzer outputs.
- Added shared documentation row aliases for later backend and query work.
