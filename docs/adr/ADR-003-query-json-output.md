# ADR-003 — JSON Output for Query Subcommands

**Date:** 28/03/2026
**Status:** Accepted

## Context

`codira` already exposed a structured JSON mode for `ctx`, but the
other read/query subcommands remained plain-text only:

* `symbol`
* `embeddings`
* `calls`
* `refs`
* `audit`

That output is easy for humans to scan, but it is awkward for downstream
automation and agent workflows because consumers must parse display-oriented
strings instead of stable fields.

The repository now also supports path scoping through `--prefix`, which makes
these subcommands more useful as deterministic building blocks for AI tooling.

## Decision

Adopt a `--json` flag for the exact/query subcommands:

* `symbol`
* `embeddings`
* `calls`
* `refs`
* `audit`

Use a lightweight shared JSON envelope for those commands:

```json
{
  "schema_version": "1.0",
  "command": "symbol",
  "status": "ok",
  "query": {},
  "results": []
}
```

Rules:

* keep the existing `ctx --json` contract unchanged
* keep query semantics unchanged; `--json` is an output mode only
* allow `--json` to compose with `--prefix`, `--incoming`, `--module`, and
  `--limit` where applicable
* echo the user-supplied repo-root-relative prefix in `query.prefix`
* use command-specific result item shapes under the shared envelope

Status values:

* `ok`
* `no_matches`
* `not_indexed` for embedding queries when stored embedding rows are absent

## Rationale

This design gives AI and tool consumers a stable machine-readable contract
without forcing all commands into the richer retrieval-oriented schema used by
`ctx`.

Keeping the implementation at the CLI layer has two benefits:

* no database schema changes are required
* the underlying exact/query helpers remain focused on data retrieval rather
  than output formatting

Using one shared envelope across the exact/query subcommands makes it easier to
write generic automation, while still allowing each command to expose the
fields that matter for its result type.

## Consequences

### Positive

* deterministic machine-readable output for the main exact/query surfaces
* clean composition with `--prefix`
* lower parsing burden for agent workflows and external tools
* no schema bump or index rebuild requirement

### Negative

* one more output mode to document and test
* long-term responsibility to version and preserve the JSON contracts

### Neutral / Trade-offs

* `ctx --json` remains a separate richer schema family
* exit codes remain aligned with existing command behavior even when JSON is
  emitted

## Notes

* The shared JSON envelope is intended for command-line consumers, not as a
  replacement for the internal query helper APIs.
