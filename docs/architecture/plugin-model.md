# Plugin Model

`ADR-004` landed the analyzer/backend plugin surface. `ADR-022` extends that
model with embedding engine and vector-store plugin families.

## Accepted Target Model

The accepted migration now distinguishes four extension families:

- `IndexBackend`: exactly one active storage/query backend per repository index
- `LanguageAnalyzer`: zero or more analyzers participating in one indexing run
- `EmbeddingEngine`: exactly one active text-to-vector runtime
- `VectorStore`: exactly one active vector persistence/similarity store

This asymmetry is deliberate:

- storage selection is an instance-level policy
- analyzers represent repository-content capabilities
- embedding engines and vector stores are singleton runtime/storage choices
  because vector identity and query ranking depend on the active pair

## Current State

The current codebase now exposes:

- first-party backend and analyzer package registrations
- third-party plugin discovery through Python entry points
- deterministic duplicate rejection and load diagnostics
- a `codira plugins` inspection surface for discovery verification
- optional explicit configuration injection through `configure(config)`
- optional plugin-owned JSON Schema publication through
  `configuration_json_schema()`
- machine-readable capability reporting for all four plugin families through
  `codira caps --json`

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

Phase 8 introduced explicit registry helpers in `src/codira/registry.py`.

- Current defaults and selection rules are:

- effective configuration selects the active backend through `[backend].name`
- `CODIRA_INDEX_BACKEND` remains a process override for `backend.name`
- when unset or blank across all config levels, the backend defaults to `sqlite`
- unsupported backend names raise `ValueError` before indexing or query work
- analyzers are registered from first-party packages plus entry points and
  instantiated in deterministic order
- `[plugins].disabled_analyzers` removes configured analyzers from the active
  analyzer set
- `[plugins].disable_third_party` disables third-party plugin loading
- file routing still uses first-match analyzer selection

This keeps configuration narrow while making backend selection and analyzer
activation explicit.

## Configuration Injection Contract

Plugins never read global config directly. The registry extracts the
namespaced table for each loaded plugin and injects it into fresh plugin
instances:

```toml
[plugins.analyzer-python]
emit_imports = false
exclude_paths = ["tests/fixtures"]
```

The table name is `plugins.<family>-<plugin-name>`, where `<family>` is
`analyzer`, `backend`, `embedding`, or `vector-store`.

Plugins may expose:

```python
def configuration_json_schema(self) -> Mapping[str, object]: ...
def configure(self, config: Mapping[str, object]) -> None: ...
```

Both hooks are optional for third-party plugins. A plugin without a schema is
not schema-validated beyond the core table shape. A plugin without
`configure()` keeps default behavior; if its table contains settings other than
`enabled`, `codira config validate` reports a non-fatal warning.

First-party plugins expose strict schemas with `additionalProperties = false`.
All plugin tables accept `enabled: bool = true`. Analyzer tables also accept
repo-relative `include_paths` and `exclude_paths`, evaluated after suffix or
family eligibility; excludes take precedence over includes.

Configured analyzer state contributes to persisted analyzer inventory through
a deterministic configuration fingerprint. Changing analyzer configuration
therefore invalidates stale index reuse without hidden global state.

The current packaging boundary is also now explicit:

- core `codira` dependencies cover shared CLI, registry, query, indexing, and
  contract infrastructure
- analyzer-specific dependencies live in separate plugin distributions
- the current Python, JSON, C, C++, and Bash analyzers are extracted into
  first-party packages rather than remaining built-ins in the core install
- the default SQLite backend is provided by `codira-backend-sqlite`
- the optional DuckDB backend is provided by `codira-backend-duckdb`
- the default SentenceTransformers engine is provided by
  `codira-embedding-sentence-transformers`
- the optional ONNX Runtime engine is provided by `codira-embedding-onnx`
- local vector-store plugins are provided by `codira-vector-store-sqlite` and
  `codira-vector-store-duckdb`
- third-party plugins live in separate distributions and are discovered from
  `codira.analyzers`, `codira.backends`, `codira.embedding_engines`, and
  `codira.vector_stores` entry-point groups

## Phase-9 Analyzer Proof

Phase 9 validated the analyzer side of the plugin model with a second
implementation. The current package set extends that proof:

- `PythonAnalyzer` handles `*.py`
- `JSONAnalyzer` handles supported JSON document families
- `CAnalyzer` handles `*.c` and `*.h`
- `CppAnalyzer` handles standard C++ source and header suffixes
- `BashAnalyzer` handles Bash scripts
- all active analyzers can participate in the same indexing run

This is the first concrete proof that the `LanguageAnalyzer` contract supports
mixed-language repositories without changing backend semantics.
