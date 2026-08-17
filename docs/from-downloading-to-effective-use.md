# From downloading Codira to effectively using it

You do not need to learn a new programming language to get value from Codira.
Point it at a repository and it turns a question such as “where does this
request become validated?” into a small, local map of the symbols, files,
tests, and relationships worth reading first.

That is the promise: less wandering through an unfamiliar tree, more time on
the part of the code that matters. Codira is especially useful when you are
joining a project, returning after a long break, reviewing a change, or giving
a coding agent a reliable starting point.

## What Codira installs—and what it does not touch

Codira has a **host runtime** and a **target repository**:

- The host runtime is the Python environment that runs Codira and its plugins.
  It requires Python 3.13 or newer.
- The target repository is the project you want to understand. Codira reads
  its files, configuration, and Git metadata; it does not import or execute
  that project's code.
- Each indexed repository receives local state under `.codira/` by default.
  This is an index and cache, not a source-code rewrite. It is normally kept
  out of version control.

Keeping those roles separate is deliberate: one stable Codira installation can
inspect many repositories without becoming a dependency of each one.

## Choose an installation path

| I want to… | Choose |
| --- | --- |
| Start using the current stable release | Install `codira-bundle-official` from PyPI |
| Walk through setup choices, MCP integration, and optional services | Use `codira-installer` |
| Try unreleased changes or contribute to Codira | Clone the GitHub repository |

### Fast path: install the official PyPI bundle

Create a dedicated environment for Codira, separate from the project you will
analyze:

```bash
python3 -m venv ~/.venvs/codira
source ~/.venvs/codira/bin/activate
python -m pip install --upgrade pip
python -m pip install codira-bundle-official
```

The official bundle gives you the `codira` command, first-party language
analyzers, local storage backends, semantic-retrieval support, and the guided
installer. Check that the runtime can see what it needs:

```bash
codira -V
codira plugins
codira caps --json
```

`caps --json` is the machine-readable capability contract. It is useful when
you want a script or agent workflow to discover exactly which commands and
plugins are available rather than relying on assumptions.

### Guided path: let the installer explain the choices

If creating environments, choosing a package profile, configuring MCP, or
enabling a background service sounds like too much ceremony, start the guided
installer:

```bash
codira-installer
```

It previews the selected source, environment, package profile, configuration,
model provisioning, MCP integration, and optional services before it applies
anything. Its default destination is a per-user standalone runtime, so your
application repositories remain independent. The installer never uses `sudo`,
does not remove packages just because they were deselected, and keeps a
resumable journal for an interrupted plan.

For automation, it can export a reviewable JSON plan before applying it. See
the [Installer guide](installer.md) when you need a new environment, an
existing environment, a local checkout, or a named workspace.

### Development path: clone Codira from GitHub

Clone the source when you are evaluating a branch or contributing:

```bash
git clone https://github.com/marco0560/codira.git
cd codira
python3 scripts/bootstrap_dev_environment.py
```

The bootstrap script creates the repository's uv-managed development
environment, installs the extracted first-party packages, and provisions the
default local embedding model. This is intentionally more involved than the
PyPI route: it gives you a live development checkout rather than a stable
standalone tool.

## Your first ten minutes

Activate the environment containing Codira, move to a repository, and build
the local index:

```bash
cd /path/to/your/repository
codira index
```

The first run discovers supported files, stores symbols and static
relationships, and prepares local semantic retrieval. If the configured model
artifact is missing, Codira provisions it locally on this first indexing run.
Subsequent indexes reuse unchanged work, so refreshing is normally quick:

```bash
codira index --explain
```

`--explain` makes the reuse decisions visible. Use `--full` only when you
intentionally need to discard incremental reuse. For a target that must remain
read-only, direct all Codira state elsewhere:

```bash
codira index --path /path/to/your/repository --output-dir /tmp/codira-state
```

Now ask the repository three different kinds of questions.

### 1. See the shape of the project

List the indexed symbols, ordered with their static call and callable-reference
connectivity counts:

```bash
codira symlist --limit 25
codira symlist --prefix src --include-tests
```

This is a fast way to find the project’s landmarks: entry points, heavily
connected services, and the matching test-facing surface. When another tool
needs the inventory, use a stable structured form rather than scrape text:

```bash
codira symlist --json
```

### 2. Follow a behavior from one symbol

Once you know a likely name, resolve it exactly and walk its indexed calls:

```bash
codira sym authenticate_user
codira calls authenticate_user --tree
codira calls authenticate_user --incoming --tree
```

Want an actual graph? Codira can render a bounded traversal as Graphviz DOT.
Save it and turn it into SVG when Graphviz is installed:

```bash
codira calls authenticate_user --tree --dot > authentication-calls.dot
dot -Tsvg authentication-calls.dot -o authentication-calls.svg
```

`refs` complements `calls` by following callable objects through bindings,
assignments, and returned values:

```bash
codira refs authenticate_user --incoming --tree --dot > authentication-refs.dot
```

### 3. Start from a human question

Use `ctx` when you know the job but not the implementation names:

```bash
codira ctx "where are failed login attempts recorded and tested?"
codira ctx "where are failed login attempts recorded and tested?" --json
```

The normal view is made for a human reader. `--json` is for an agent,
automation, or an integration that needs fields it can consume directly.
Other discovery commands—including `index`, `sym`, `calls`, `refs`, `plugins`,
`cov`, and `audit`—also offer `--json`; run `codira <command> --help` to see
the options that apply to one command. `--json` changes the output format, not
the question being asked.

## Keep the map current

An index is a snapshot. During a small investigation, run `codira index` after
a meaningful edit batch and before asking the next retrieval question. This
keeps the result grounded in the files the agent or you just changed.

For an active project, Codira can instead watch the repository and schedule
the normal index operation after relevant changes. First create a repository
configuration if one does not already exist:

```bash
codira config init --level repo
```

Set the following in `.codira/config.toml`:

```toml
[daemon]
enabled = true
debounce_ms = 250
```

Then choose the lifecycle that fits your machine:

```bash
codira daemon run       # foreground watcher; useful while developing
codira daemon install   # install the repository-scoped user service
codira daemon start
codira daemon status
```

The automatic-indexing daemon watches relevant, non-ignored files, respects
Git ignore rules, debounces bursts of changes, and reconciles branch changes.
It is optional: an explicit `codira index` remains the simplest and most
predictable choice. The separate query daemon keeps read queries warm; it does
not watch files or replace indexing. See [Configuration](configuration.md) for
watch scope, service support, and both daemon contracts.

## Make it a habit

The satisfying workflow is a short loop:

1. Name the task in plain language.
2. Refresh the index—or let the indexing daemon do it.
3. Use `ctx` to identify the likely files, then `sym`, `symlist`, `calls`, or
   `refs` to answer the next precise question.
4. Read the source and tests Codira identifies.
5. Change the smallest thing that solves the problem, then validate it.

Codira does not replace judgment or source review. It gives you a better first
page of the story. To hand that page to a coding agent, continue with [How to
use Codira with my coding agent](coding-agents.md).
