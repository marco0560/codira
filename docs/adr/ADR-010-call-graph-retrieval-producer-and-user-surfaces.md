# ADR-010 — Call-graph retrieval producer and bounded user surfaces

**Date:** 03/04/2026
**Status:** Under review

## Context

Issue `#10` proposes promoting call-graph enrichment from shared descriptor
metadata to a native `RetrievalProducer`, following the embedding-channel
migration completed during issue `#9`.

That internal extraction is useful on its own, but call-graph work also has a
potential end-user surface. The risk is scope creep: once call relations become
available as a native producer, it becomes tempting to treat "the call graph"
as a broad feature rather than a bounded retrieval/navigation capability.

The repository needs an explicit scope boundary before implementation proceeds.

In particular:

* full-repository graph visualization is easy to ask for but rarely useful
* unconstrained graph expansion becomes noisy very quickly
* `calls`, `refs`, and `ctx` have different user-facing purposes
* graphical export may be valuable later, but it should not define the first
  implementation

## Decision Direction

Treat this work as **bounded call-relationship retrieval**, not as a generic
repository-wide graph browser.

The intended end-state may include multiple user-facing surfaces, but they must
be delivered in phases and remain explicitly scoped.

### Primary Internal Goal

The first architectural goal remains the issue's original one:

* extract a native call-graph retrieval producer outside `context.py`
* route call-graph signal emission through that producer
* preserve current ranking and explain behavior

### User-Facing Boundary

If user-facing call-graph features are added, they must follow these rules:

* all traversal must be bounded by explicit limits
* truncation must be visible in plain and JSON output
* symbol-scoped questions are in scope
* whole-repository graph dumps are out of scope for the first implementation

Examples of in-scope questions:

* who calls `X`?
* what does `X` call?
* what small bounded neighborhood surrounds `X`?
* why was `X` considered relevant in `ctx`?

Examples of out-of-scope first-version behavior:

* render the entire call graph of a repository
* unbounded recursive graph expansion
* large default terminal visualizations

## Proposed Phase Order

1. placeholder ADR and execution ledger
2. native call-graph retrieval producer extraction outside `context.py`
3. bounded user-facing `calls` enhancements
4. optional bounded `refs` parity
5. `ctx` integration as a retrieval channel
6. optional graph/export surfaces such as `--dot`

## Consequences

### Positive

* keeps issue `#10` from broadening opportunistically
* allows internal producer extraction to proceed independently from later UX
* makes limits and truncation part of the feature contract from the start
* preserves room for later graphical/export work without forcing it into v1

### Negative

* some attractive graph features will be deferred explicitly
* user-facing `calls`/`refs` improvements may need follow-up issues after the
  producer extraction lands

### Neutral / Trade-offs

* the native producer and user-facing surfaces are related, but not identical
* `ctx` should consume call-graph evidence in a much smaller bounded
  form than a dedicated `calls` view
* graphical output, if added later, should be optional export rather than the
  primary interaction mode

## Execution Rules

* Keep this ADR in `Under review` state until at least the producer extraction
  boundary and the initial user-facing phase ordering have been validated.
* Maintain a dedicated execution ledger for issue `#10` under `docs/process/`.
* Treat `issue/10-call-graph-retrieval-producer` as the long-lived design and
  integration branch for this issue.
* Prefer short-lived implementation branches or `main` for concrete slices, and
  periodically rebase the issue branch to limit divergence.

## Phase Ledger

* [x] Phase 1 — Placeholder ADR and execution ledger
* [x] Phase 2 — Native call-graph retrieval producer extraction
* [x] Phase 3 — Bounded `calls` user surface
* [x] Phase 4 — Optional bounded `refs` parity
* [x] Phase 5 — `ctx` call-graph channel integration
* [x] Phase 6 — Optional graph/export surfaces
