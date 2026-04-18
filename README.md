<img src="docs/badges/cartoon_cold-2.png" alt="codira badge" width="160">

# codira

**codira: your code ferret**

[![CI](https://github.com/marco0560/codira/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/marco0560/codira/actions/workflows/ci.yml)
[![Docs](https://github.com/marco0560/codira/actions/workflows/docs.yml/badge.svg?branch=main)](https://marco0560.github.io/codira/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

`codira` is a repository-local indexing and context retrieval tool for
agent-assisted development. It gives coding agents a concise, deterministic
map of the codebase so they can answer focused questions, find the right files,
and start edits with less broad scanning.

The practical effect is simple: when `codira` is used alongside a coding
agent, the same task can often be handled with fewer tokens because the agent
receives a small, relevant context pack instead of rediscovering the repository
from scratch.

`codira` builds a SQLite index inside the target repository and supports exact
symbol lookup, docstring auditing, deterministic local semantic embeddings,
static call and callable-reference inspection, plugin discovery, and
deterministic context generation for natural-language queries.

The current release indexes mixed-language repositories through registered
language analyzers:

- Python via the first-party `codira-analyzer-python` plugin
- JSON via the first-party `codira-analyzer-json` plugin for JSON Schema,
  `package.json`, and `.releaserc.json`
- C-family `*.c` and `*.h` files via the first-party
  `codira-analyzer-c` plugin backed by `tree-sitter-c`
- Bash scripts via the first-party `codira-analyzer-bash` plugin backed by
  `tree-sitter-bash`
- SQLite persistence via the first-party `codira-backend-sqlite` backend
  plugin

Storage and query persistence remain SQLite-backed through the active backend
registry.

## Why It Helps Agent Workflows

Coding agents are strongest when they start with the right local facts. `codira`
turns the repository into a compact map of symbols, docstring issues, semantic
matches, call edges, callable references, and plugin coverage. Instead of asking
an agent to spend a large part of the context window scanning files, you can run
one focused command and hand it the relevant slice.

That usually means:

- fewer tokens spent on broad repository exploration
- fewer repeated file reads for the same task
- more deterministic handoffs between human intent and agent action
- a clearer audit trail for why a file or symbol was considered relevant

## Repository Documentation

The repository-local operational and contributor documentation is organized
under `docs/`.

Start with:

- `docs/getting_started.md`
- `docs/CONTRIBUTING.md`
- `docs/architecture/index.md`
- `docs/plugins/index.md`
- `docs/release/checklist.md`
- `docs/release/process.md`
- `docs/process/branching.md`
- `docs/process/decisions.md`
- `docs/adr/index.md`

The project documentation site uses the same badge on the landing page and
uses the small badge as the MkDocs favicon.

## Install

For the official runtime with the first-party analyzers and SQLite backend:

```bash
pip install codira-bundle-official
```

`codira` and the official bundle are published on PyPI. If you only need to
use the tool and do not need a development branch, prefer the published package
instead of an editable checkout.

The installed command is:

```bash
codira --help
```

For a core-only install:

```bash
pip install codira
```

## Install for Local Development

Install `codira` into the virtual environment of the repository you want to
analyze.

Example: from a target repository such as Fontshow:

```bash
source .venv/bin/activate
pip install -e ../codira
```

The editable install keeps the `codira` CLI available in the target
repository's virtual environment while still using the live source tree from
this repository.

Developer automation is Poetry-based for dependency resolution and lockfile
maintenance, while local validation and CI execute the installed tools directly
from `.venv` and the editable first-party package set.

Install optional analyzer packages only when needed. For repository-local
development inside this repo, the bootstrap flow installs the official
first-party packages automatically through:

```bash
python scripts/install_first_party_packages.py \
  --include-core \
  --core-extra dev \
  --core-extra docs \
  --core-extra semantic
```

For an editable install into another repository with the current source tree:

```bash
source .venv/bin/activate
python ../codira/scripts/install_first_party_packages.py \
  --python "$VIRTUAL_ENV/bin/python" \
  --include-core \
  --core-extra semantic
```

The published end-user bundle is `codira-bundle-official`. Inside the current
checkout, install the extracted first-party analyzers and backend from
`packages/`; the canonical local install set is owned by
`scripts/install_first_party_packages.py`.

Use `codira plugins` to inspect discovery. The report marks each plugin as
`origin=core`, `origin=first_party`, or `origin=third_party`.

## Architecture Status

The current architecture after completed `ADR-004` migration work is:

- one active backend per repository instance, selected through
  `codira.registry`
- SQLite as the default first-party backend distributed through
  `codira-backend-sqlite`
- multiple language analyzers in one indexing run
- deterministic mixed-language indexing for tracked Python, supported JSON,
  Bash, and C-family files
- query-time retrieval planning with deterministic intent families for
  behavior, test, configuration, API-surface, and architecture/navigation
  queries

The first-party JSON analyzer is intentionally family-based rather than generic.
It currently supports:

- JSON Schema documents
- npm-style `package.json` manifests
- semantic-release `.releaserc.json` files

It intentionally does not claim lockfiles, VS Code JSONC settings, or generic
unclassified JSON blobs.

The detailed architecture and migration record live under:

- `docs/architecture/index.md`
- `docs/adr/ADR-004-pluggable-backends-migration-plan.md`

## Commands

Build or refresh the repository-local index:

```bash
codira index
```

Indexing also precomputes local deterministic embeddings for indexed symbols.
Unchanged files are reused by default.

Force a full rebuild:

```bash
codira index --full
```

Show incremental reuse decisions:

```bash
codira index --explain
```

Inspect canonical-directory analyzer coverage without building the index:

```bash
codira cov
codira cov --json
```

Coverage checks tracked files under `src/`, `tests/`, and `scripts/`. A file is
considered covered only when some active analyzer both discovers it and returns
`True` from `supports_path()`.

Require full canonical coverage before indexing:

```bash
codira index --require-full-coverage
```

Audit indexed docstrings:

```bash
codira audit
codira audit --json
codira audit --prefix src/codira/query
```

For Python callables, `audit` applies Python-aware result-section
rules:

- regular functions should document `Returns` and not `Yields`
- generator and async-generator functions should document `Yields`
- generators may also document `Returns` only when they explicitly use
  `return <value>` to produce a terminal `StopIteration.value`

Query exact symbols:

```bash
codira sym build_parser
codira sym build_parser --json
codira sym build_parser --prefix src/codira
```

Inspect embedding-only matches and backend metadata:

```bash
codira emb "schema migration rules"
codira emb "schema migration rules" --json
codira emb "schema migration rules" --prefix src/codira/query
```

Inspect static call edges:

```bash
codira calls context_for
codira calls context_for --json
codira calls context_for --tree
codira calls context_for --tree --dot
codira calls imported_helper --module pkg.b --incoming
codira calls imported_helper --module pkg.b --incoming --prefix src/codira/query
```

Inspect callable-object references such as registry bindings:

```bash
codira refs _retrieve_script_candidates --module codira.query.context --incoming
codira refs _retrieve_script_candidates --incoming --json
codira refs _retrieve_script_candidates --incoming --tree
codira refs _retrieve_script_candidates --incoming --tree --dot
codira refs _retrieve_script_candidates --incoming --prefix src/codira/query
```

Generate deterministic context for a natural-language query:

```bash
codira ctx "missing numpy docstring"
codira ctx "missing numpy docstring" --prefix src/codira
```

Embedding-assisted retrieval works best for natural-language queries such as:

```bash
codira ctx "schema migration rules"
```

Emit structured JSON for agent workflows:

```bash
codira ctx "missing numpy docstring" --json
codira ctx "missing numpy docstring" --json --prefix src/codira/query
```

Emit a prompt-oriented view:

```bash
codira ctx "parse inventory validation flow" --prompt
```

## Command Guide

Use the subcommands in roughly this order during development and maintenance:
refresh the index, inspect exact symbols or relations, then ask for broader
task-oriented context.

### 0. `index`

Use `index` to build or refresh the repository-local snapshot that every other
retrieval command depends on.

Suggested use cases:

- first use in a repository
- after switching branches
- after rebases, pulls, or merges
- after significant code or structure changes
- before trusting results from `sym`, `calls`, `refs`, `ctx`, or
  `audit`

Examples:

```bash
codira index
codira index --require-full-coverage
```

Expected result semantics:

- refreshes `.codira/` for the current working tree
- makes later queries deterministic against the current indexed state
- should be rerun when you suspect the current snapshot is stale

### 1. `sym`

Use `sym` when you already know the exact symbol name and want the indexed
definition sites.

Suggested use cases:

- jump to `build_parser`, `context_for`, or another known symbol
- confirm exact defining files before editing
- narrow down repeated symbol names with `--prefix`

Examples:

```bash
codira sym build_parser
codira sym build_parser --json
codira sym build_parser --prefix src/codira
```

Expected result semantics:

- returns exact symbol-name matches, not semantic approximations
- is best when the symbol name is already known

### 2. `emb`

Use `emb` to inspect the embedding channel by itself.

Suggested use cases:

- debug semantic recall
- inspect backend metadata and raw embedding-ranked matches
- compare embedding-only behavior with `ctx`

Examples:

```bash
codira emb "schema migration rules"
codira emb "schema migration rules" --json
```

Expected result semantics:

- shows embedding-ranked matches only
- does not include the multi-channel merge used by `ctx`

### 3. `calls`

Use `calls` to inspect direct indexed static call edges.

Suggested use cases:

- see what a function directly calls
- see who directly calls a function with `--incoming`
- render a bounded traversal with `--tree`
- export a bounded traversal as Graphviz DOT with `--tree --dot`

Examples:

```bash
codira calls context_for
codira calls context_for --incoming
codira calls context_for --tree
codira calls context_for --tree --dot
```

Expected result semantics:

- covers direct static call edges only
- tree mode remains bounded by `--max-depth` and `--max-nodes`
- DOT export is opt-in and only available for bounded tree mode

### 4. `refs`

Use `refs` to inspect callable-object references rather than direct call sites.

Suggested use cases:

- inspect registry bindings
- see which owners return or store a callable object
- trace incoming owners of one callable target with `--incoming`
- render or export a bounded reference tree

Examples:

```bash
codira refs _retrieve_script_candidates --incoming
codira refs _retrieve_script_candidates --incoming --tree
codira refs _retrieve_script_candidates --incoming --tree --dot
```

Expected result semantics:

- focuses on callable-object references such as registries, assignment values,
  and returned function objects
- is complementary to `calls`, not interchangeable with it

### 5. `ctx`

Use `ctx` when you have a task or question rather than an exact symbol
name.

Suggested use cases:

- understand where behavior lives for a bug fix
- prepare a maintenance or refactor pass
- gather bounded context for an agent or review workflow
- inspect retrieval diagnostics with `--explain`

Examples:

```bash
codira ctx "schema migration rules"
codira ctx "missing numpy docstring" --json
codira ctx "parse inventory validation flow" --prompt
codira ctx "missing numpy docstring" --explain
```

Expected result semantics:

- uses bounded multi-channel retrieval rather than exact lookup only
- can use bounded graph evidence during ranking
- can expand related cross-module symbols after ranking
- is a focused context pack, not a full repository report

### 6. `audit`

Use `audit` to inspect indexed docstring problems directly.

Suggested use cases:

- run a documentation cleanup pass
- focus audits on one subtree with `--prefix`
- emit machine-readable results for automation with `--json`

Examples:

```bash
codira audit
codira audit --prefix src/codira/query
codira audit --json
```

Expected result semantics:

- reports indexed docstring issues, not arbitrary style suggestions
- is most useful after a fresh `codira index`

### 7. `plugins`

Use `plugins` to inspect which capabilities are active and where they come
from.

Suggested use cases:

- confirm whether a capability came from core, an official package, or a
  third-party plugin
- verify packaging and installation state in a repository

Examples:

```bash
codira plugins
codira plugins --json
```

Expected result semantics:

- reports installed or active plugin and capability surfaces
- is useful when debugging environment or packaging issues

### 8. `caps`

Use `caps` when a tool, contributor, or agent needs codira to declare what it
can answer before making retrieval decisions. The longer `capabilities` command
is kept as a compatibility alias.

Suggested use cases:

- inspect the canonical ontology used by active analyzers
- verify analyzer declarations after plugin changes
- inspect command and retrieval-channel guarantees
- feed deterministic capability metadata into agent workflows

Examples:

```bash
codira caps
codira caps --json
codira caps --strict --json
```

Expected result semantics:

- exports command, channel, analyzer, and retrieval-producer declarations
- reports degraded metadata if an active analyzer does not explicitly declare
  ontology coverage
- fails on missing or invalid analyzer declarations only when `--strict` is set
- describes capability surfaces only; it does not index or query repository
  content

### 9. Common Flags and Modes

The most important cross-cutting flags are:

- `--prefix`: scope results to one subtree or file
- `--json`: machine-readable output
- `--prompt`: compact agent handoff for `ctx`
- `--explain`: retrieval diagnostics for `ctx`
- `--tree`: bounded traversal mode for `calls` and `refs`
- `--dot`: Graphviz DOT export for bounded `calls` and `refs` trees

Practical rule:

- use exact commands first when you already know what you are looking for
- use `ctx` when the task is known but the exact symbol is not
- rerun `index` whenever you would not trust the current snapshot
- always read the referenced files before patching

## Using `--prefix`

Use `--prefix <path>` to scope supported read/query subcommands to one
repo-root-relative directory or file.

Examples:

```bash
codira sym build_parser --prefix src/codira
codira emb "schema migration rules" --prefix src/codira/query
codira calls imported_helper --module pkg.b --incoming --prefix src/codira/query
codira refs _retrieve_script_candidates --incoming --prefix src/codira/query
codira audit --prefix src/codira/query
codira ctx "missing numpy docstring" --json --prefix src/codira/query
```

Semantics:

- `sym --prefix P NAME`: only symbols whose defining file is under `P`
- `emb --prefix P QUERY`: only matched symbols whose file is under `P`
- `ctx --prefix P QUERY`: retrieval, expansion, issues, and references
  are restricted to files under `P`
- `calls --prefix P NAME`: only call edges whose caller file is under `P`
- `refs --prefix P NAME`: only callable-object references whose owner file is
  under `P`
- `audit --prefix P`: only issues for symbols defined under `P`

`--prefix` must be relative to the repository root. It may point to either a
directory or a single file.

## Using `--json`

Use `--json` on the exact/query subcommands when another tool or agent needs a
machine-readable result instead of human-oriented text.

Supported subcommands:

- `sym`
- `emb`
- `calls`
- `refs`
- `audit`
- `ctx`
- `caps`

Examples:

```bash
codira sym build_parser --json
codira emb "schema migration rules" --json --prefix src/codira/query
codira calls imported_helper --module pkg.b --incoming --json
codira refs _retrieve_script_candidates --incoming --json --prefix src/codira/query
codira audit --json --prefix src/codira/query
codira ctx "missing numpy docstring" --json
```

For `sym`, `emb`, `calls`, `refs`, and `audit`, the JSON
contract uses a lightweight shared envelope:

```json
{
  "schema_version": "1.0",
  "command": "symbol",
  "status": "ok",
  "query": {
    "name": "build_parser",
    "prefix": "src/codira"
  },
  "results": []
}
```

Status values:

- `ok`: one or more results were found
- `no_matches`: the filtered query returned no results
- `not_indexed`: the command requires indexed embedding data that is not present

`ctx --json` keeps its existing richer retrieval schema. It is not part
of the lightweight query-envelope contract above.

## Using `--prompt`

Use `codira ctx "<query>" --prompt` when you want a compact,
copy-ready prompt for an agent session.

Recommended use cases:

- starting a focused bug-fix task
- preparing a docstring audit pass
- analyzing an external repository before patching
- resuming work on a specific subsystem after context switching

Recommended workflow:

1. Verify likely symbols or files with `rg`.
2. Run `codira index`.
3. Run `codira ctx "<query>" --prompt`.
4. Read the returned files and symbols before editing.

The prompt view is optimized for fast operator handoff. It is not a substitute
for reading the referenced files.

## Choosing an Output Mode

Use the plain text mode when you want a compact human-readable summary across
the symbol, semantic, and embedding channels:

```bash
codira ctx "missing numpy docstring"
```

Use JSON when another tool or agent workflow needs structured output:

```bash
codira ctx "missing numpy docstring" --json
codira sym build_parser --json
```

Use prompt mode when you want a copy-ready task preamble:

```bash
codira ctx "parse inventory validation flow" --prompt
```

Use explain mode when you need retrieval diagnostics:

```bash
codira ctx "missing numpy docstring" --explain
```

Practical rule:

- plain text: human inspection
- `--json`: automation and downstream tooling
- `--prompt`: agent handoff
- `--explain`: debugging retrieval behavior

The `emb` command is a debugging surface for the embedding channel only.
Use it when you want backend metadata and raw embedding-ranked matches without
the normal multi-channel merge used by `ctx`.

## Query Examples

Natural-language queries:

```bash
codira ctx "missing numpy docstring"
codira ctx "parse inventory validation flow"
codira ctx "where is schema validation performed"
codira ctx "how does release tagging work"
codira ctx "semantic merge ordering"
```

Exact symbol lookup:

```bash
codira sym build_parser
codira sym context_for
codira sym validate_docstring
```

Static call-edge inspection:

```bash
codira calls context_for
codira calls imported_helper --module pkg.b --incoming
```

Callable-reference inspection:

```bash
codira refs _retrieve_script_candidates --module codira.query.context --incoming
```

The most useful queries are usually:

- behavior-oriented
- scoped to one subsystem
- phrased in terms of the problem you are solving

Prefer specific queries over broad ones such as `"project structure"` or
`"everything about indexing"`.

## Reindexing and Freshness

Rerun `codira index` when the repository state has changed enough that the
existing `.codira/` snapshot may no longer reflect the current code.

Typical cases:

- after significant code changes
- after switching branches
- after rebases, pulls, or merges
- before a larger audit session
- before querying a repository that has not been indexed yet

The index is repository-local and intentionally conservative. Rebuilding it is
cheap compared with working from stale symbol or docstring data.

Practical rule:

```bash
codira index
```

Run it again whenever you would not trust an earlier search result to describe
the current working tree.

## Limits and Expectations

`codira` is a retrieval and inspection tool. It narrows search and improves
determinism, but it does not replace direct source inspection.

Important limits:

- it includes a deterministic in-repo embedding backend rather than a full
  external-model semantic stack
- stored embeddings carry explicit backend and version metadata so the backend
  can be replaced later without changing the retrieval interface
- it does not prove behavior correctness on its own
- it does not replace reading the referenced files
- it does not authorize blind edits based only on retrieved snippets
- it is only as current as the indexed repository state
- embedding recall is intentionally lightweight and local-first in the current
  implementation
- `codira calls` only covers direct static call sites
- `codira refs` should be used for callable-object references such as
  registry values, assignment values, and returned function objects
- `codira calls --tree` and `codira refs --tree` provide bounded
  traversal views, and `--dot` renders those bounded trees as Graphviz DOT
- `ctx` now uses bounded graph evidence during retrieval and then uses
  stored call and callable-reference data to pull in related cross-module
  symbols around top function and method matches

Recommended use:

- use `codira` to find likely files, symbols, and related issues
- use `rg` to verify concrete symbol existence
- read the actual files before patching
- rerun tests and validation after changes

## Recommended Workflow in an External Repository

Run `codira` from the target repository, not from the `codira` source
tree.

Example workflow:

1. Activate the target repository virtual environment.
2. Run `codira index`.
3. Verify candidate symbols with `rg <query>` before patching.
4. Run `codira ctx "<query>" --json`.
5. Inspect the actual files and symbols returned.
6. Apply changes only after verification.
7. Rebuild the index after material source changes.

This keeps the `.codira/` cache local to the analyzed repository and avoids
cross-repo state drift.

## Suggested Shell Aliases

```bash
alias ri='codira'
alias ri-index='codira index'
alias ri-audit='codira audit'
alias ri-ctx='codira ctx'
alias ri-docs='codira ctx "missing numpy docstring" --json'
```

## Optional Helper Script

A thin wrapper script in the target repository can make the workflow more
repeatable:

```bash
#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
codira "$@"
```

Example target-repo setup:

```bash
mkdir -p scripts
cat > scripts/ri.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
codira "$@"
EOF
chmod +x scripts/ri.sh
```

Then run:

```bash
./scripts/ri.sh index
./scripts/ri.sh audit
./scripts/ri.sh ctx "missing numpy docstring" --json
```

## Integration Guidance

Use `codira` as a developer tool.

Recommended:

- install it editable into the target repository virtual environment
- keep the index local to the target repository
- verify symbol existence with `rg` before editing

Not recommended:

- global installation for day-to-day work
- treating `codira` as a runtime dependency of the target project
- relying on ad-hoc `PYTHONPATH` launch patterns for normal usage

## AGENTS.md Snippet for Target Repositories

If you want a target repository to standardize `codira` usage, this snippet
can be copied into its `AGENTS.md`:

```text
### codira Workflow

Use `codira` as a repository-local developer tool.

Before broad code exploration or patching:

1. Activate the repository virtual environment.
2. Run `codira index`.
3. Verify candidate symbols with `rg <query>` before editing.
4. Run `codira ctx "<query>" --json` or `--prompt` as needed.
5. Inspect the referenced files before applying changes.

Use output modes as follows:

- plain `ctx`: compact human-readable context
- `ctx --json`: structured tool/agent workflows
- `ctx --prompt`: copy-ready agent preamble
- `ctx --explain`: retrieval diagnostics

`codira` narrows search and improves determinism. It does not replace
reading the actual source files before editing.
```
