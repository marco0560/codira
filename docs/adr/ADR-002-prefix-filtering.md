# ADR-002 — Prefix-Scoped Query Filtering

**Date:** 27/03/2026
**Status:** Accepted

## Context

`codira` query subcommands originally operated on the whole indexed
repository. That worked for smaller repositories, but it made targeted work on
one subsystem noisy:

* exact symbol lookup returned duplicates from unrelated domains
* embedding and context retrieval mixed matches across unrelated areas
* call and callable-reference inspection could not be constrained to one owner
  domain
* docstring audits could not be limited to a single subtree

At the storage level, several tables duplicated full file paths instead of
reusing the central `files` table:

* `symbol_index`
* `docstring_issues`
* `call_records`
* `callable_ref_records`

The derived relation tables also lacked path ownership metadata:

* `call_edges`
* `callable_refs`

That made uniform prefix filtering awkward and inconsistent.

## Decision

Adopt a permanent `--prefix <repo-root-relative-path>` option for supported
read/query subcommands and make prefix filtering schema-backed.

Supported subcommands and semantics:

* `symbol --prefix P NAME`:
  restrict to symbols whose defining file is under `P`
* `embeddings --prefix P QUERY`:
  restrict to matched symbols whose file is under `P`
* `ctx --prefix P QUERY`:
  restrict retrieval, expansion, docstring issues, and references to files
  under `P`
* `calls --prefix P NAME`:
  restrict to call edges whose caller file is under `P`
* `refs --prefix P NAME`:
  restrict to callable-object references whose owner file is under `P`
* `audit --prefix P`:
  restrict to issues for symbols defined under `P`

Implementation details:

* normalize `--prefix` once relative to the repository root
* reject user-supplied absolute prefixes at the CLI boundary
* use the central `files.id` as the owner key across path-sensitive tables
* join through `files.path` when evaluating prefix filters

Schema changes:

* replace repeated `file_path` columns with `file_id` in:
  * `symbol_index`
  * `call_records`
  * `callable_ref_records`
* add `file_id` to `docstring_issues`
* add owner-side file identifiers to derived relation tables:
  * `caller_file_id` on `call_edges`
  * `owner_file_id` on `callable_refs`

## Rationale

This design keeps the filtering rule uniform while minimizing duplicated path
storage.

Using a centralized file table has two advantages:

* smaller tables and indexes, especially for raw call/reference record tables
* one consistent join path for owner-file filtering

Filtering semantics for relation queries are intentionally owner-side:

* `calls` is about caller-owned edges
* `refs` is about owner-owned callable references

This avoids ambiguous "either side" semantics and keeps the feature teachable.

For `ctx`, prefix filtering is applied throughout the pipeline rather
than only at the end, which reduces noise and wasted work.

## Consequences

### Positive

* uniform scoping model across supported query subcommands
* better signal when working in one subtree or file
* smaller path-sensitive tables due to `file_id` reuse
* exact, schema-backed filtering for `audit`
* owner-side relation filtering that is deterministic and easy to reason about

### Negative

* schema version bump and rebuild cost for existing indexes
* additional joins through `files` in some query paths
* more explicit query-surface complexity in CLI and helper signatures

### Neutral / Trade-offs

* `--prefix` is relative by contract, but internal helper flows may pass the
  normalized absolute path after validation
* relation filtering is not symmetric; it is intentionally tied to owner/caller
  semantics

## Notes

* Existing indexes are rebuilt through the normal schema-version refresh path.
* Directory and single-file prefixes are both supported.
