# AGENTS.md

## Purpose

This document defines the rules, workflow, and constraints for AI-assisted
development in the `codira` project.

All agents (including ChatGPT) MUST follow these rules strictly.

---

## Core Principles

### 1. Source of Truth (SOT)

- The repository filesystem is the ONLY source of truth.
- Never assume files, modules, or structures that are not present.
- Never reconstruct code from memory.

If something is not visible → STOP.

If any required information is missing:

→ STOP
→ Ask for clarification

---

### 2. Deterministic Behavior

- No guessing
- No approximations
- No “best effort”

All outputs must be:

- reproducible
- verifiable
- minimal

---

### 3. Strict Patch Discipline

All code changes MUST be provided as:

- explicit file paths
- exact OLD / NEW blocks

No summaries. No partial edits.

---

### 4. Minimalism (LEAN)

- Prefer the smallest correct solution
- Avoid introducing abstractions prematurely
- Avoid “framework thinking”

---

## Development Workflow

### Required Shared Skills

When a shared skill exists and is applicable to the current task, agents MUST
use it and follow its instructions.

This requirement applies generally, not only to the examples below.

Use at least the following shared skills for the corresponding task classes:

- `deterministic-change-workflow` for non-trivial code changes, bug fixes, and
  feature work
- `numpy-docstring-enforcer` whenever modifying modules, classes, public
  functions, or non-trivial private functions
- `codira-workflow` before broad code exploration or patching
- `commit-block-generator` for every commit, including direct local commits and
  proposed commit blocks

If a required shared skill is unavailable, state that explicitly and apply the
same rules manually.

### Monorepo Plugin Packaging

While first-party plugins and bundles live in this monorepo, every change to a
plugin implementation, plugin public contract, entry point, package dependency,
or package data MUST update the corresponding package metadata and tests in the
same change.

This includes the plugin distribution version, its `pyproject.toml`
dependencies, package-data declarations, package-local metadata tests, and every
bundle that pins or exposes that plugin. Bundle pins MUST remain compatible with
the core `codira` version installed from the same monorepo checkout.

This rule is temporary monorepo discipline. It prevents editable installs from
mixing current source code with stale distribution metadata; once the packages
are split into independent repositories, each repository's own release process
will own this consistency requirement.

### Standard Loop

1. Analyze request
2. Propose plan, ask all necessary clarification questions
3. Wait for approval or changes
4. Execute plan
5. Do NOT run `git check` in a terminal for agent validation.
6. Run the underlying checks directly from `.venv`:

   ```bash
   source .venv/bin/activate
   black --check .
   ruff check .
   mypy .
   pytest -q
   ```

7. Verify:

   - `black --check .` passes
   - `ruff check .` passes
   - `mypy .` passes
   - `pytest -q` passes
   - If any would fail → fix BEFORE concluding

8. Manually validate behavior if needed
9. At the end of every complex modification cycle, create a commit before
   concluding.

   Always use `commit-block-generator` before creating the commit.

10. If a commit block is requested or appropriate, propose a **single** commit
    block using the applicable shared skill.

    The commit block must remain atomic and CI-compliant.

### codira Workflow

Use `codira` as a repository-local developer tool.

Before broad code exploration or patching:

1. Verify candidate symbols with `rg <query>` before editing.
2. Run `codira ctx "<query>" --json` or `--prompt` as needed.
3. Inspect the referenced files before applying changes.

Use output modes as follows:

- plain `ctx`: compact human-readable context
- `ctx --json`: structured tool/agent workflows
- `ctx --prompt`: copy-ready agent preamble
- `ctx --explain`: retrieval diagnostics

`codira` narrows search and improves determinism. It does not replace
reading the actual source files before editing.

### Virtual Environment

This repository is operated from the local `.venv` environment.

All Python-facing tools and entry points MUST resolve from `.venv`, not from
the system installation or ambient `PATH`.

Use one of these forms consistently:

- `source .venv/bin/activate` before running project tools
- explicit `.venv/bin/<tool>` paths when activation is not appropriate

Assume all tool paths, Python interpreters, and console scripts are based on
`.venv`.

---

### Cleanup

Before critical operations:

```bash
git clean-repo
codira index
```

---

### Context Exploration

Use:

```bash
codira ctx <query>
```

to inspect symbols and relationships.

---

## Coding Standards

### Python

- Type hints required
- No `Any` unless justified
- Prefer `Path` over string paths

---

### Docstrings

- Use **NumPy style**
- Required for all modules, classes, non trivial functions
- Must include:

  - Parameters
  - Returns

- Includes if appropriate

  - `Raises` when exceptions are possible
  - `Notes`
  - `Examples`

Docstrings must:

- match actual behavior (no drift)
- reflect current signature
- include `Raises` when exceptions are possible
- avoid redundancy
- be concise and precise

---

### Error Handling

- Avoid broad `except Exception`
- Catch only expected exceptions
- Fail fast

---

## Architecture Rules

### Separation of Concerns

| Layer      | Responsibility       |
|------------|----------------------|
| scanner    | filesystem → symbols |
| indexer    | symbols → database   |
| query      | database → results   |
| CLI        | user interface       |

Do not mix layers.

---

### Git is the Source of Truth for Cleanup

- Cleanup logic MUST rely on git
- Never implement custom filesystem heuristics

---

## Anti-Patterns (Forbidden)

- Blind filesystem scanning when git provides truth
- Re-implementing logic already present elsewhere
- Introducing caching without clear invalidation rules
- Silent failures

---

## Agent Roles

Agents may act as:

- Senior Reviewer
- Pair Programmer
- Refactoring Assistant

But MUST always:

- respect SOT
- avoid hallucination
- produce deterministic output

---

## When in Doubt

STOP and ask for clarification.

Never proceed with assumptions.

---

## Future Extensions

This file may evolve to include:

- audit workflows
- release discipline
- semantic indexing policies

---

END
