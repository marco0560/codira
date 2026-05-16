# AGENTS.md — Codira Repository Contract

## 0. Mission

Operate on the `codira` repository with strict priorities:

1. Correctness
2. Test integrity
3. Reproducibility
4. Traceability
5. Minimal change

Fluency is irrelevant.

## 1. Operating Mode

Mode: HARD-FAIL DETERMINISTIC

Rules:

- Never guess
- Never infer missing code
- Never reconstruct unseen files
- Never approximate behavior

## 2. Global STOP Rule

If any of the following occurs:

- missing information
- ambiguity
- multiple valid approaches without guidance
- inability to match exact code

→ STOP
→ Ask for clarification

## 3. Sources of Truth (SOT)

Priority:

1. Repository files
2. Tests (`tests/`)
3. Documentation (`docs/`)
4. User instructions

Previous assistant output is NOT a source of truth.

## 4. Execution Precedence

Always use the highest available level:

1. Repository-provided structured tools (e.g. `codira`)
2. Local skills (`~/.codex/skills`)
3. Standard tools (`rg`, shell)
4. Manual inspection

Lower levels are fallback only.

## 5. Repository Map (Orientation Layer)

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
| `packages/`   | First-party plugin packages (analyzers, backend) |
| `tests/`      | Authoritative behavior and contract validation   |
| `docs/`       | Documentation, architecture, ADRs                |
| `scripts/`    | Development and process tooling                  |
| `.github/`    | CI workflows                                     |
| `.artifacts/` | Generated artifacts (e.g. benchmarks)            |

### 5.2. Core System (`src/codira/`)

The core implementation resides under `src/codira/`.

#### Entry points

| File         | Role                    |
|--------------|-------------------------|
| `cli.py`     | CLI command entry point |
| `indexer.py` | Index orchestration     |

#### Analyzers (built-in)

| Path                  | Responsibility  |
|-----------------------|-----------------|
| `analyzers/python.py` | Python analysis |
| `analyzers/c.py`      | C analysis      |
| `analyzers/bash.py`   | Bash analysis   |
| `analyzers/json.py`   | JSON analysis   |

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

#### Semantic / embeddings

| Path                     | Responsibility       |
|--------------------------|----------------------|
| `semantic/embeddings.py` | embedding generation |
| `semantic/search.py`     | semantic retrieval   |

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
| `schema.py`     | schema handling    |
| `schema/*.json` | schema definitions |

#### Miscellaneous

| Path                        | Responsibility         |
|-----------------------------|------------------------|
| `capabilities.py`           | capabilities reporting |
| `utils.py`                  | shared utilities       |
| `version.py`, `_version.py` | version metadata       |
| `prompts/`                  | prompt templates       |

### 5.3. Plugins (`packages/`)

First-party plugins are distributed as separate packages.

| Type      | Examples                | Responsibility             |
|-----------|-------------------------|----------------------------|
| Analyzers | `codira-analyzer-*`     | language-specific analysis |
| Backend   | `codira-backend-sqlite` | persistent storage backend |

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

## 6. Core Principles

- Deterministic: reproducible, verifiable outputs
- Minimal: smallest correct change
- Scoped: no unrelated modifications

Forbidden unless explicitly required:

- refactoring unrelated code
- renaming symbols
- API changes
- stylistic churn

## 7. Task Classification

A task is non-trivial if it involves:

- multiple files
- architectural decisions
- ambiguity
- potential behavioral impact

## 8. Execution Workflow (MANDATORY)

For non-trivial tasks use `deterministic-change-workflow`

1. Analyze request
2. Identify gaps → STOP if needed
3. Propose plan
4. WAIT for approval
5. Execute
6. Validate

Do not skip steps.

If planning is ambiguous → use `planning-refinement-gate`.

## 9. Codira Exploration (MANDATORY)

The repository provides `codira`:

→ the `codira-workflow` skill MUST be used

### CLI Invocation

- Prefer the installed CLI executable (`.venv/bin/codira`)
- Do not assume `python -m codira` is supported

### Rules

- Do not manually reproduce codira behavior
- Do not approximate its workflow
- Do not use `rg` or broad search as a first step

### Fallback

Fallback to `rg` is allowed only if:

- `codira` is unavailable, OR
- indexing fails, OR
- results are demonstrably insufficient

### Enforcement

If `codira` is available and not used:

→ STOP
→ report violation
→ restart using `codira-workflow`

## 10. Skills Usage

If a required skill exists in `~/.codex/skills`:

→ MUST be used

Required skills:

- deterministic-change-workflow
- numpy-docstring-enforcer
- commit-block-generator
- planning-refinement-gate
- codira-workflow
- roadmap-snapshots

If a skill is missing:

- If behavior is fully specified → proceed manually
- Otherwise → STOP and report missing capability

When a skill fully defines a workflow:

→ the skill replaces any equivalent procedural instructions in this document
→ this document defines only constraints and enforcement

## 11. Change Strategy

- Prefer small, atomic changes
- One subsystem at a time
- Separate refactor / feature / fix

## 12. Validation Contract

All checks MUST pass.

Primary:

```bash
pre-commit run --all-files
pytest -q
```

Fallback:

```bash
black --check .
ruff check .
mypy .
pytest -q
```

Rules:

- fix all failures
- do not weaken tests
- do not ignore errors

Notes:

- pre-commit is the authoritative validation entry point
- It enforces ruff, formatting, typing, and other checks
- Do not run individual tools unless diagnosing failures

## 13. Test Contract

Tests define behavior.

Requirements:

- deterministic
- environment-independent

Forbidden:

- weakening assertions
- introducing flakiness
- bypassing failures

If tests contradict assumptions → tests win.

## 14. Strict Patch Discipline

All changes MUST include:

- exact file paths
- exact OLD block (byte-identical)
- exact NEW block

Forbidden:

- summaries
- partial edits
- approximations

If OLD block cannot be matched:

→ STOP

## 15. Architecture Constraints

Respect separation of concerns:

| Layer   | Responsibility       |
|---------|----------------------|
| scanner | filesystem → symbols |
| indexer | symbols → database   |
| query   | database → results   |
| CLI     | interface            |

Rules:

- do not mix layers
- do not bypass abstractions
- do not duplicate logic

## 16. Build & Artifacts

- do not edit generated files
- modify generators instead
- keep build outputs consistent

## 17. Coding Standards

### Python

- type hints required
- avoid `Any`
- prefer `Path`

### Docstrings

NumPy style required:

- Parameters
- Returns
- optional: Raises, Notes, Examples

Use `numpy-docstring-enforcer`

## 18. Error Handling

- fail fast
- catch only expected exceptions
- avoid broad `except Exception`

## 19. Regression Policy

Bugs include:

- platform breakage
- performance regressions
- CLI/output changes
- optional feature regressions

## 20. Debugging Discipline

- reproduce first
- identify root cause
- avoid speculative fixes
- do not repeatedly retry the same failing approach
- if the same error is encountered twice:
  - research 3-5 plausible fixes
  - compare tradeoffs
  - choose the most efficient correct solution
  - implement deterministically

## 21. Commit Contract

Use `commit-block-generator`

- single atomic commit
- format: `type(scope): summary`

Body must include:

- root cause
- fix
- validation

Do NOT include toolchain status lines.

## 22. Roadmap Snapshots

Use `roadmap-snapshots` for:

- issues.json
- milestones.json

Rules:

- treat as local artifacts
- verify schema and completeness
- do not infer missing fields

## 23. Anti-Patterns (Forbidden)

- guessing code
- blind scanning
- duplicating logic
- silent failures
- skipping validation

## 24. Session Stability

Monitor:

- context drift
- assumption creep

If detected:

→ STOP
→ Recommend reset

## 25. Heuristics

- small changes can have wide effects
- complex code encodes edge cases
- correctness > elegance

## 26. Default Interaction Mode

- minimal prose
- command-oriented
- no verbosity unless requested

## 27. Meta Rule

Do not reference this contract in responses.
Do not explain compliance.
Only execute.

## 28. When in Doubt

STOP and ask.
