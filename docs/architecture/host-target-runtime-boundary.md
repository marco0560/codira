# Host-target runtime boundary

This document records the implemented host-target runtime boundary. The staged
direction in [ADR-028](../adr/ADR-028-host-target-runtime-decoupling.md) now
includes workspace routing and Python parsing owned by the analyzer package.

## Separate contracts

- The **host runtime** is the interpreter that runs Codira and its installed
  plugins. ADR-017 currently requires Python 3.13 or newer for that runtime.
- A **target repository** is data read by Codira. Normal indexing reads source,
  configuration, Git metadata, and files; it does not import or execute target
  repository code.
- **Target source compatibility** is declared by the Python analyzer. Its
  Tree-sitter grammar binding is package-owned, so core Codira does not depend
  on the host interpreter's Python grammar.

The first-party Python analyzer makes its compatibility claim only for the
fixture-backed matrix. Grammar ownership alone does not assert complete version
coverage.

## Declared target Python metadata

The Python analyzer records a declared target contract through its
package-owned Tree-sitter extraction path. Codira resolves the explicit
`[plugins.analyzer-python] target_python` PEP 440 specifier before
`[project].requires-python`; the capability contract exposes the source,
specifier, bounded 3.8–3.14 minor normalization, tested-minor list, bundled
grammar identity, grammar maximum, and a provenance key. Missing, invalid,
partial (open or excluded), and unsupported declarations remain distinct
outcomes. The package-owned matrix stores every fixture as source data, so the
Python 3.13 Codira host can validate the Python 3.14 template-string fixture
without importing it through the host parser.

The same output separately records the host interpreter minor and
`plugin_owned_tree_sitter` parser compatibility. Declared target minors are
an explicit, fixture-validated release claim. Any new maximum needs its own
fixture and synchronized tested-minor metadata; the matrix test rejects a
claim that is not represented by the fixtures.

## Current routing contract

Repository-scoped CLI commands support direct path routing and named workspace
routing. `--path` selects a target repository, `--output-dir` selects Codira
state, and `--config-file` selects the repository-level configuration source;
`--workspace` selects their registered equivalent as one unit.

The local MCP server starts with exactly one of `codira-mcp --root PATH` or
`codira-mcp --workspace NAME`; omitting both preserves the current-directory
root default. Workspace startup resolves the repository root, state root, and
optional configuration file exactly once before constructing the server. It
then fingerprints the descriptor and keeps the resolved values for the process
lifetime. Requests accept no repository or workspace selector, so they cannot
retarget a live server after a descriptor change.

Workspace-originated response provenance includes only the workspace name and
descriptor SHA-256 fingerprint. It does not expose descriptor, repository,
state, or configuration paths. Direct-root startup retains its existing
path-only protocol and provenance behavior. Codex, Claude Desktop, and Cursor
presets can render either fixed startup mode.

## Shared model-store contract

Model payloads are host-user data, not workspace or managed-runtime data.
Codira resolves their root in this order: an explicit operation root,
`CODIRA_MODEL_ROOT`, `[embeddings].model_root`, then the platform cache model
root. Every selected root must be absolute.

`SharedModelStore` publishes immutable files as SHA-256-addressed blobs. An
identity manifest binds the embedding engine, upstream model, model version,
and artifact role to one verified blob. Identity-scoped locks and atomic blob
then manifest publication ensure readers never observe a partial or corrupt
artifact. Existing Codira-managed files can be copied into the store without
altering the source copy.

SentenceTransformers receives a cache folder under this shared root, so its
Hugging Face snapshots are reused by all Codira runtimes. ONNX configurations
can name `model_artifact` and `tokenizer_artifact` roles; those resolve only
through verified store manifests. The legacy explicit-path configuration remains
available for a non-destructive migration. New relative paths are rooted under
the shared model store whenever Codira supplies it; the historical
`.codira/...` shape remains an explicit compatibility path until migration.

Installer model plans can pass an explicit shared root to the target runtime.
They never select a model location under the target virtual environment.

## Workspace domain baseline

Slice 2 introduces a versioned `workspace.toml` domain contract without adding
CLI routing or a registry. A descriptor identifies exactly one repository root,
one state root, and an optional configuration file. Descriptor-relative paths
resolve from the descriptor directory; repository and configuration paths must
exist, while a state root may be created later by its owning operation.

`platform_paths` centralizes the per-user configuration, data, state, cache,
and runtime locations through `platformdirs`. It derives managed runtime,
workspace descriptor, workspace state, and shared model roots without creating
directories. Later workspace, installer, service, and model-store slices reuse
these typed values instead of duplicating platform logic.

## Workspace registry baseline

Slice 3 adds `codira workspace add`, `list`, `show`, `validate`, `update`, and
`remove`. The registry publishes descriptors atomically, rejects duplicate
names and canonical repository roots, and emits versioned JSON for automation.
Removal unregisters only the descriptor: repository, configuration, state, and
model data remain untouched.

## Workspace routing baseline

Every repository-scoped CLI command now accepts `--workspace NAME` or
`CODIRA_WORKSPACE`. Workspace routing resolves its repository root, state root,
and optional configuration file as one validated unit before configuration or
storage access. It is mutually exclusive with direct `--path`, `--output-dir`,
and `--config-file` routing, including their environment equivalents. Direct
path behavior remains available and uses the same resolved runtime-path
contract.

## Characterization guardrails

The Python analyzer golden fixture protects normalized artifacts. A
deterministic production host-AST inventory is empty and rejects any future
core or package import or reference to the host `ast` module.
