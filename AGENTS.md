# AGENTS.md - Codira Repository Contract

## Mission

Work in this repository to advance the user's objectives with these priorities:

1. Correctness
2. Test integrity
3. Reproducibility
4. Traceability
5. Minimal change

Be direct. The assistant is not here to flatter the user or preserve a bad
premise. If the user's request, plan, or assumption is technically wrong,
push back clearly and explain the practical consequence.

## Operating Rules

- Treat repository files as the source of truth.
- Read before editing.
- Do not invent unseen code, missing files, or behavior.
- Keep changes small, scoped, and reversible.
- Preserve user changes in the worktree.
- Do not refactor, rename, or change APIs unless the task requires it.
- If a requested change has multiple valid implementations and the repository does not make the choice clear, ask before editing.
- If the task is impossible to complete deterministically, stop and state the blocker.

## Source Priority

Use sources in this order:

1. Repository files
2. Tests in `tests/`
3. Documentation in `docs/`
4. User instructions

Previous assistant output is not a source of truth.

## Required Tools And Skills

- If the repo provides `codira`, use `codira-workflow` before broad exploration or patching.
- Prefer repository-native commands through `uv run`.
- At the start of each task, inspect the skills available in the current session and select the minimal set that applies.
- Read the selected skill instructions before acting on them.
- Use applicable skills as active workflow rules, not as optional references.
- Use local skills when they match the task:
  - `deterministic-change-workflow` for non-trivial changes
  - `planning-refinement-gate` for ambiguous planning or architecture work
  - `numpy-docstring-enforcer` when modifying Python symbols
  - `commit-block-generator` when preparing commits
  - `roadmap-snapshots` for `issues.json` or `milestones.json`
- Use `rg` only after structured repository tools are unavailable,
  insufficient, or irrelevant to the task.

## Repository Map (Orientation Layer)

This section provides a **structural map of the Codira repository grounded in actual filesystem layout**.

It is **not a substitute for `codira-workflow`**.
Use it only to:

- identify relevant modules quickly
- select appropriate `--prefix` scope
- understand subsystem boundaries before detailed inspection

### 5.1. Top-Level Layout

| Path          | Purpose                                          |
|---------------|--------------------------------------------------|
| `src/codira/` | Core library and CLI implementation              |
| `packages/`   | First-party plugin packages and bundle metadata  |
| `tests/`      | Authoritative behavior and contract validation   |
| `docs/`       | Documentation, architecture, ADRs                |
| `scripts/`    | Development and process tooling                  |
| `.github/`    | CI workflows                                     |
| `.artifacts/` | Generated artifacts (e.g. measuring campaigns)   |
| `benchmarks/` | Manifests for measuring campaigns                |

### 5.2. Core System (`src/codira/`)

The core implementation resides under `src/codira/`.

#### Entry points

| File         | Role                    |
|--------------|-------------------------|
| `cli.py`     | CLI command entry point |
| `indexer.py` | Index orchestration     |

#### First-Party Plugin Packages (`packages/`)

| Path                                      | Responsibility                        |
|-------------------------------------------|---------------------------------------|
| `codira-analyzer-bash/`                   | Bash analyzer distribution            |
| `codira-analyzer-c/`                      | C analyzer distribution               |
| `codira-analyzer-cpp/`                    | C++ analyzer distribution             |
| `codira-analyzer-json/`                   | JSON analyzer distribution            |
| `codira-analyzer-markdown/`               | Markdown analyzer distribution        |
| `codira-analyzer-python/`                 | Python analyzer distribution          |
| `codira-analyzer-text/`                   | Plain-text analyzer distribution      |
| `codira-backend-duckdb/`                  | DuckDB structural backend and DuckDB-owned physical schema |
| `codira-backend-sqlite/`                  | SQLite structural backend and SQLite-owned physical schema |
| `codira-vector-store-duckdb/`             | DuckDB vector-store backend           |
| `codira-vector-store-sqlite/`             | SQLite vector-store backend           |
| `codira-embedding-onnx/`                  | ONNX embedding backend                |
| `codira-embedding-sentence-transformers/` | Torch / Sentence Transformers backend |
| `codira-bundle-official/`                 | Curated first-party dependency bundle |

Package internals usually follow `src/<import_package>/` plus package-local
`tests/`.

#### Query subsystem

| Path                        | Responsibility       |
|-----------------------------|----------------------|
| `query/exact.py`            | exact symbol lookup  |
| `query/context.py`          | context retrieval    |
| `query/structural.py`       | structural queries   |
| `query/graph_enrichment.py` | graph augmentation   |
| `query/producers.py`        | result assembly      |
| `query/classifier.py`       | query classification |
| `query/signals.py`          | query signals        |

#### Semantic / embeddings  (`src/codira/semantic/`)

| Path            | Responsibility       |
|-----------------|----------------------|
| `embeddings.py` | embedding generation |
| `search.py`     | semantic retrieval   |

#### Core infrastructure

| Path                        | Responsibility                 |
|-----------------------------|--------------------------------|
| `scanner.py`                | filesystem scanning            |
| `registry.py`               | plugin discovery and selection |
| `contracts.py`              | backend/analyzer interfaces    |
| `models.py`                 | core data models               |
| `types.py`                  | shared type definitions        |
| `storage.py`                | storage abstraction layer      |
| `sqlite_backend_support.py` | SQLite-specific support        |
| `prefix.py`                 | prefix filtering logic         |
| `path_resolution.py`        | path normalization             |
| `normalization.py`          | symbol normalization           |
| `parser_ast.py`             | AST parsing utilities          |
| `docstring.py`              | docstring validation           |

#### Schema

| Path            | Responsibility     |
|-----------------|--------------------|
| `schema.py`     | logical schema metadata, not backend DDL |
| `schema/*.json` | JSON output schemas |

#### Miscellaneous

| Path                        | Responsibility         |
|-----------------------------|------------------------|
| `capabilities.py`           | capabilities reporting |
| `utils.py`                  | shared utilities       |
| `version.py`, `_version.py` | version metadata       |
| `prompts/`                  | prompt templates       |

### 5.3. Plugins (`packages/`)

First-party plugins are distributed as separate packages.

| Type      | Examples                      | Responsibility                         |
|-----------|-------------------------------|----------------------------------------|
| Analyzers | `codira-analyzer-*`           | language-specific analysis             |
| Backends  | `codira-backend-*`            | persistent structural storage backend  |
| Embedding | `codira-embedding-*`          | embedding engine backend               |
| Vectors   | `codira-vector-store-*`       | vector persistence backend             |
| Bundle    | `codira-bundle-official`      | curated first-party dependency bundle  |

Notes:

- Plugins are discovered via the registry (`registry.py`)
- They may be installed independently from the core

### 5.4. Test Layer

| Path     | Role                                   |
|----------|----------------------------------------|
| `tests/` | authoritative behavioral specification |

Important:

- Tests may contain **full implementations not used in production**
- Example: in-memory backend used for contract validation

Tests override assumptions.

### 5.5. CLI → Module Mapping

| Command   | Primary modules                                |
|-----------|------------------------------------------------|
| `index`   | `indexer.py`, `scanner.py`, analyzers          |
| `sym`     | `query/exact.py`                               |
| `calls`   | `query/graph_enrichment.py`                    |
| `refs`    | `query/graph_enrichment.py`                    |
| `emb`     | `semantic/embeddings.py`, `semantic/search.py` |
| `ctx`     | `query/context.py`                             |
| `audit`   | `docstring.py`                                 |
| `cov`     | analyzer + indexer                             |
| `plugins` | `registry.py`                                  |
| `caps`    | `capabilities.py`                              |

### 5.6. High-Value Entry Points

For any investigation:

1. CLI command (`cli.py`)
2. Indexer (`indexer.py`)
3. Query subsystem (`query/`)
4. Analyzer (if language-specific)
5. Tests

Typical flow:

```text
cli → indexer → query → analyzer → tests
```

### 5.7. Orientation Constraints

- `src/codira/` is the authoritative implementation root
- `packages/` contains pluggable extensions, not core logic
- `tests/` may contain non-production implementations
- Always verify behavior against tests
- Use this map only to narrow scope before using `codira`

### Execution Environment

- The repository uses `uv` as the authoritative environment manager
- Prefer `uv run <tool>` for repository commands
- Use `uv sync` for environment synchronization
- Commands are typically executed from the repository-local virtual environment (`.venv`)
- Prefer explicit paths (e.g. `.venv/bin/codira`) over relying on PATH
- Do not assume global tool availability
- Plugins are discovered via entry points and may live outside the repository.
- First-party plugins are located under `packages/`.

Use this map to scope Codira queries. It does not replace indexed inspection.

## Tests And Documentation

- Tests define behavior.
- Prefer tests over implementation comments when behavior is unclear.
- Documentation describes intent and contracts, but tests and code win when they disagree.
- Do not weaken assertions, skip failures, or add environment-dependent tests.
- When changing public behavior, update matching tests and docs in the same change.

## Python Standards

- Use type hints.
- Prefer `Path` for filesystem paths.
- Avoid `Any` unless the boundary genuinely requires it.
- Catch only expected exceptions.
- Use NumPy-style docstrings for modified Python modules, classes, and functions.

## Architecture Constraints

Keep boundaries intact:

| Layer   | Responsibility        |
|---------|-----------------------|
| scanner | filesystem -> symbols |
| indexer | symbols -> database   |
| query   | database -> results   |
| CLI     | interface             |

Do not duplicate logic across layers or bypass existing abstractions.

## Generated Files And Artifacts

- Do not hand-edit generated files when a generator owns them.
- Modify the generator and regenerate the artifact.
- Keep generated outputs consistent with the checked-in source of truth.

## Validation

Run the narrowest meaningful validation during development, then the declared
repository validation before closing substantial work:

```bash
uv run pyhton scripts/validate_repo-py
```

If the primary validation cannot run, use the closest local fallback and report the reason:

```bash
ruff check .
ruff format --check .
mypy .
pytest -q
```

Do not claim checks passed unless they were run.

## Commits

When asked to commit:

- Keep the commit atomic.
- Use `commit-block-generator`.
- Use Conventional Commit format: `type(scope): summary`.
- Include root cause, fix, and validation in the body.

## TUI Interaction

- Keep status updates concise and operational.
- Ask only when a real decision or missing fact blocks deterministic progress.
- Push back on incorrect assumptions immediately.
- Prefer doing the work over narrating the workflow.
- Report changed files and validation results at the end.
