# Plugin Model

`ADR-004` landed the analyzer/backend plugin surface. `ADR-022` extends that
model with embedding engine and vector-store plugin families.

## Accepted Target Model

The accepted migration now distinguishes five extension families:

- `IndexBackend`: exactly one active storage/query backend per repository index
- `LanguageAnalyzer`: zero or more analyzers participating in one indexing run
- `EmbeddingEngine`: exactly one active text-to-vector runtime
- `VectorStore`: exactly one active vector persistence/similarity store
- `DocumentationAuditPlugin`: zero or more convention-specific documentation
  validators selected by explicit routes

This asymmetry is deliberate:

- storage selection is an instance-level policy
- analyzers represent repository-content capabilities
- embedding engines and vector stores are singleton runtime/storage choices
  because vector identity and query ranking depend on the active pair
- documentation audit plugins may overlap by language, so activation is an
  explicit language/convention/path routing decision instead of an implicit
  analyzer side effect

## Current State

The current codebase now exposes:

- first-party backend and analyzer package registrations
- third-party plugin discovery through Python entry points
- deterministic duplicate rejection and load diagnostics
- a `codira plugins` inspection surface for discovery verification
- optional explicit configuration injection through `configure(config)`
- optional plugin-owned JSON Schema publication through
  `configuration_json_schema()`
- machine-readable capability reporting for all five plugin families through
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
`analyzer`, `backend`, `embedding`, `vector-store`, or
`documentation-audit`.

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
- first-party documentation audit plugins are provided by
  `codira-documentation-audit-numpy`,
  `codira-documentation-audit-google`, and
  `codira-documentation-audit-doxygen`
- documentation audit plugin implementations are loaded from package entry
  points; core only owns the shared contract and route execution boundary
- third-party plugins live in separate distributions and are discovered from
  `codira.analyzers`, `codira.backends`, `codira.embedding_engines`,
  `codira.vector_stores`, and `codira.documentation_audits` entry-point groups

## Documentation Audit Routing

Documentation audit plugins are intentionally separate from language analyzers.
Analyzers decide which source files and artifacts are indexed; documentation
audit plugins decide whether an indexed documentation block satisfies one
documentation convention.

Routes live in `plugins.documentation_audit_routes`. Each route declares:

- `language`: analyzer language such as `python`, `c`, or `cpp`
- `convention`: convention label passed to the plugin, such as `numpy`,
  `google`, or `doxygen`
- `plugin`: plugin name selected from the documentation-audit registry
- optional `include_paths` and `exclude_paths` repo-relative glob patterns

More than one documentation audit plugin can be installed for the same
language. Codira therefore does not auto-select a convention. During indexing,
a public artifact is audited only when exactly one route matches its language
and path. No route means no documentation audit row is emitted; more than one
matching route emits an `ambiguous_route` diagnostic so operators can tighten
the route table.

The first release scope supports:

- NumPy-style Python docstrings through plugin `numpy`
- Google-style Python docstrings through plugin `google`
- Doxygen-style C and C++ comments through plugin `doxygen`

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
