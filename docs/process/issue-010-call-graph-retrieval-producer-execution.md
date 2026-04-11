# Issue 010 Execution

## Purpose

This document records the planned execution order for issue `#10` while
`ADR-010` remains under review.

It exists to keep the call-graph work bounded and to prevent unrelated graph
features from being folded into the issue without an explicit phase decision.

## Branch

The long-lived design and integration branch for this issue is:

```text
issue/10-call-graph-retrieval-producer
```

Concrete implementation slices should still land through short-lived branches
or directly on `main`, then be rebased back into the issue branch as needed.

## Phase 1 Outcome

Phase 1 is complete when both of the following exist and agree with each
other:

1. `docs/adr/ADR-010-call-graph-retrieval-producer-and-user-surfaces.md`
2. this execution document

Phase 1 does **not** change runtime behavior.

## Phase 2 Outcome

Phase 2 is complete when:

* call-graph enrichment orchestration lives outside `context.py`
* `context.py` delegates graph expansion to a dedicated query module
* native graph enrichment producers remain visible in explain diagnostics
* ranking and explain behavior stay covered by deterministic regression tests

## Detailed Implementation Plan

### Phase 2 — Native call-graph retrieval producer extraction

Goal:
Move call-graph signal production into a native retrieval producer outside
`context.py` without changing ranking or explain semantics.

Primary files:

* `src/codira/query/context.py`
* `src/codira/query/`
* `src/codira/query/signals.py`
* `tests/test_retrieval_merge.py`
* `tests/test_characterization_phase2.py`

Tasks:

1. Identify the current call-graph signal entry points in `context.py`.
2. Define the producer boundary and capability contract.
3. Extract the producer into its own module.
4. Preserve current mixed producer collection behavior.
5. Add regression tests covering descriptor and native-producer coexistence.

Exit criteria:

* call-graph signal collection no longer lives inline in `context.py`
* ranking and explain output remain behaviorally stable
* tests cover mixed producer collection deterministically

### Phase 3 Outcome

Phase 3 is complete when:

* `calls` keeps its existing flat output by default
* bounded traversal is opt-in and explicit through CLI flags
* traversal order is deterministic
* truncation is visible in plain text and JSON output
* no unbounded repository-wide expansion exists by default

### Phase 3 — Bounded `calls` user surface

Goal:
Add bounded user-facing traversal for `calls` without turning it into a
repository-wide graph browser.

Possible surface:

* `--tree`
* `--max-depth`
* `--max-nodes`
* `--json` graph/tree metadata with explicit truncation

Tasks:

1. Define the default traversal semantics.
2. Define deterministic ordering for neighbors.
3. Define truncation reporting in plain and JSON output.
4. Keep the default output useful for small neighborhoods only.

Exit criteria:

* traversal is bounded and deterministic
* truncation is explicit
* no unbounded whole-repository expansion exists by default

### Phase 4 — Optional bounded `refs` parity

Goal:
Decide whether `refs` should expose the same bounded traversal surface as
`calls`.

Tasks:

1. Evaluate whether the user value is high enough to justify parity.
2. Reuse the same limit/truncation rules if parity is added.
3. Keep callable-reference semantics distinct from actual invocation edges.

Exit criteria:

* either bounded parity exists, or the ledger records why it is deferred

### Phase 5 — `ctx` call-graph channel integration

Goal:
Use the extracted producer as a bounded retrieval channel inside
`ctx`.

Tasks:

1. Define when call-graph evidence should contribute to ranking.
2. Keep graph evidence bounded and query-relevant.
3. Surface producer provenance in explain output.
4. Prevent graph relations from overwhelming higher-signal channels.

Exit criteria:

* call-graph evidence appears as a bounded retrieval-time contribution
* explain output makes that contribution visible
* ranking remains stable and test-covered
* status: complete

### Phase 6 — Optional graph/export surfaces

Goal:
Consider optional export formats after bounded textual and JSON retrieval are
stable.

Candidates:

* `--dot`
* Mermaid-compatible export
* richer JSON graph payloads for external tooling

Constraints:

* export remains opt-in
* graph size limits still apply
* this phase must not redefine the primary user interaction model

Exit criteria:

* optional export exists only if its value is clear and its limits are explicit
* status: complete via bounded `calls --tree --dot` and `refs --tree --dot`

## Non-Goals

The following are out of scope unless the ADR and ledger are explicitly
updated:

* full-repository default graph visualization
* unbounded recursive traversal
* mixing `calls` and `refs` into one ambiguous graph surface
* silently inferred graph semantics without provenance or limits
