# Plugin Model

`ADR-004` now lands a real plugin surface for analyzers and backends.

## Accepted Target Model

The accepted migration distinguishes two extension families:

- `IndexBackend`: exactly one active storage/query backend per repository index
- `LanguageAnalyzer`: zero or more analyzers participating in one indexing run

This asymmetry is deliberate:

- storage selection is an instance-level policy
- analyzers represent repository-content capabilities

## Current State

The current codebase now exposes:

- first-party backend and analyzer package registrations
- third-party plugin discovery through Python entry points
- deterministic duplicate rejection and load diagnostics
- a `codira plugins` inspection surface for discovery verification

## Phase-3 Baseline

Phase 3 now introduces the first explicit contract modules:

- `src/codira/contracts.py`
- `src/codira/models.py`
- `src/codira/normalization.py`

Those modules define the accepted vocabulary for:

- `LanguageAnalyzer`
- `IndexBackend`
- normalized `AnalysisResult` artifacts

## Phase-8 Registries and Configuration

Phase 8 introduces explicit registry helpers in `src/codira/registry.py`.

Current defaults and selection rules are:

- `CODIRA_INDEX_BACKEND` selects the active backend
- when unset or blank, the backend defaults to `sqlite`
- unsupported backend names raise `ValueError` before indexing or query work
- analyzers are registered from first-party packages plus entry points and
  instantiated in deterministic order
- file routing still uses first-match analyzer selection

This keeps configuration narrow while making backend selection and analyzer
activation explicit.

The current packaging boundary is also now explicit:

- core `codira` dependencies cover shared CLI, registry, query, indexing, and
  contract infrastructure
- analyzer-specific dependencies live in separate plugin distributions
- the current Python, JSON, C, and Bash analyzers are extracted into
  first-party packages rather than remaining built-ins in the core install
- the default SQLite backend is provided by `codira-backend-sqlite`
- third-party plugins live in separate distributions and are discovered from
  `codira.analyzers` and `codira.backends` entry-point groups

## Phase-9 Analyzer Proof

Phase 9 validated the analyzer side of the plugin model with a second
implementation. The current package set extends that proof:

- `PythonAnalyzer` handles `*.py`
- `JSONAnalyzer` handles supported JSON document families
- `CAnalyzer` handles `*.c` and `*.h`
- `BashAnalyzer` handles Bash scripts
- all active analyzers can participate in the same indexing run

This is the first concrete proof that the `LanguageAnalyzer` contract supports
mixed-language repositories without changing backend semantics.
