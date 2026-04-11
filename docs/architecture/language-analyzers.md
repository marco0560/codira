# Language Analyzers

The current repository now has one built-in analyzer plus first-party plugin
analyzers:

- Python through the extracted `codira-analyzer-python` first-party package
- JSON through the extracted `codira-analyzer-json` first-party package for
  deterministic structured document families such as JSON Schema,
  `package.json`, and `.releaserc.json`
- C for the first non-Python proof required by `ADR-004`, installed through
  the extracted `codira-analyzer-c` first-party package

## Current Analyzer Responsibilities

The Python analysis path currently performs:

- module, class, and function extraction
- import collection
- static call-record extraction
- callable-reference extraction
- docstring validation integration

Today these responsibilities are concentrated in:

- `src/codira/parser_ast.py`
- `src/codira/analyzers/python.py`
- `src/codira/analyzers/json.py`
- `src/codira/analyzers/c.py`
- `src/codira/indexer.py` for analyzer routing only

## Current Scope Boundary

`scanner.iter_project_files()` now derives discovery globs from the active
analyzer set instead of relying on a hard-coded core tuple.

Each analyzer declares deterministic `discovery_globs`, and scanner discovery
uses those globs for candidate discovery before confirming ownership through
`supports_path()` for both:

- Git-backed tracked-file discovery
- filesystem fallback outside Git repositories

Phase 19 adds a second scanner path for canonical coverage auditing:

- `src/`
- `tests/`
- `scripts/`

Tracked files under those directories are inspected for coverage even if no
active analyzer claims them yet.

The retrieval-capability migration does not currently widen analyzer
responsibilities.

Analyzer packages still own:

- language-specific parsing
- normalized artifact extraction
- durable symbol identity for indexed artifacts

They do not yet need to implement `RetrievalProducer`. Retrieval-facing
capability metadata currently lives in shared query producer descriptors
instead.

## Accepted Migration Direction

`ADR-004` expands this boundary by accepting:

- multiple analyzers in one indexing run
- mixed-language repositories as a first-class target
- a future proof analyzer beyond Python, with C named as the preferred first
  validation target

## Phase-6 Baseline

Phase 6 now extracts the current Python analysis path into
`src/codira/analyzers/python.py`.

That module owns:

- Python parsing through `parser_ast.parse_file()`
- normalization into `AnalysisResult`
- Python file acceptance through the `LanguageAnalyzer` contract

## Phase-8 Registration Rules

Phase 8 moves analyzer registration into `src/codira/registry.py`.

- analyzers are instantiated from built-ins plus entry-point plugin discovery
- registry order defines deterministic first-match routing order after
  scanner-side ownership filtering
- an empty analyzer registry raises `ValueError`
- extracted analyzers may be omitted when their plugin packages are not
  installed

## Current JSON Family Boundary

The first-party JSON analyzer is intentionally family-based rather than generic.

Supported families:

- JSON Schema documents
- npm-style `package.json` manifests
- semantic-release `.releaserc.json` configuration

Supported JSON symbols currently include:

- schema definition names
- schema property paths
- package names
- package script keys
- package dependency names
- semantic-release branch names
- semantic-release plugin identifiers

Explicitly unsupported JSON inputs include:

- lockfiles such as `package-lock.json`
- VS Code workspace JSONC files under `.vscode/`
- generic unclassified JSON blobs

This keeps JSON indexing deterministic and query-oriented without broadening
support to arbitrary machine-generated artifacts.

## Phase-9 Second Analyzer Proof

Phase 9 adds `src/codira/analyzers/c.py` and registers it after Python.

- Python keeps the full AST-driven extraction path
- C currently extracts module identity, include dependencies, and top-level
  function definitions
- mixed-language repositories are now indexed in one deterministic run

The C analyzer is intentionally narrow. It exists to prove the abstraction and
file-routing model before any deeper C-specific call analysis work.

## Current C Parser Boundary

The current C analyzer is now backed by `tree-sitter-c`.

That gives the branch:

- parse-tree-based function extraction
- parse-tree-based include extraction
- AST-based call extraction for direct and attribute calls
- a safer foundation for future include-graph and symbol-parity work

The normalized artifact model and backend contracts remain unchanged. Only the
language-specific C parsing strategy has been upgraded.

## Dependency Boundary

The packaging surface now distinguishes core `codira` dependencies from
analyzer-specific dependencies.

- core install keeps Python analysis available
- the C analyzer loads when `codira-analyzer-c` is installed
- the Bash analyzer loads when `codira-analyzer-bash` is installed
- the supported package form for C-family indexing is `codira-analyzer-c`
- third-party analyzers must declare their own discovery globs so indexing can
  see their files without core changes

When those plugin packages are absent, registry activation skips the matching
analyzer deterministically and indexing a matching path fails with an explicit
installation hint instead of an import-time crash.
