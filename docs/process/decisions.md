# Decision Workflow

## Purpose

Architecture and governance decisions that should survive beyond individual
commits must be recorded as ADRs under `docs/adr/`.

## When to add an ADR

Create or update an ADR when a change introduces or formalizes:

- an architectural boundary
- a repository governance rule
- a release-process rule
- a durable contributor workflow
- a compatibility or contract decision that future work will rely on

## Current ADR set

The active ADR index is maintained in:

- `docs/adr/index.md`

## Helper script

Use the repository helper to create a new ADR stub:

```bash
python scripts/new_decision.py
```

That script creates the next numbered ADR file and updates the ADR index.

## Scope discipline

ADRs should document accepted decisions and durable rationale.

They should not be used as temporary scratch notes, implementation checklists,
or substitutes for issue tracking.
