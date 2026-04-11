# ADR-007 — First-party package boundary for extracted official plugins

**Date:** 02/04/2026
**Status:** Accepted

## Context

`ADR-004` established the plugin architecture for analyzers and backends, and
issue `#9` completed the capability-driven query groundwork that makes a wider
ecosystem credible.

The repository is now at an awkward intermediate state:

* third-party plugins are already modeled as separate distributions discovered
  through Python entry points
* official optional capabilities still live inside the core source tree
* optional extras such as `codira[c]` and `codira[bash]` install
  dependency stacks, but they do not exercise the same distribution boundary
  that external plugin authors must use
* the current repository layout does not yet make package ownership explicit

That mismatch weakens the architecture in practice:

* the core package still acts as both platform and optional capability bundle
* first-party optional analyzers are not validated through the same entry-point
  path used by third-party plugins
* documentation and install guidance continue to describe optional analyzers as
  extras rather than as real plugin distributions

The next step should validate the distribution boundary without prematurely
forcing the Python analyzer or the default SQLite backend out of the core
install.

## Decision

Adopt an explicit first-party package topology inside the current repository.

### Core stays narrow

The `codira` core distribution remains responsible for:

* contracts
* registry and discovery
* CLI orchestration
* index and query orchestration
* the default Python analyzer
* the default SQLite backend

### Official optional analyzers move into package-owned distributions

Phase 1 extracts the current optional analyzers into dedicated first-party
packages under `packages/`:

* `packages/codira-analyzer-c/`
* `packages/codira-analyzer-bash/`

Those packages own their implementation modules and expose analyzers through the
existing `codira.analyzers` entry-point group.

### Repository topology becomes package-aware

The accepted repository structure is:

* `src/codira/` for the core platform package
* `packages/<distribution>/` for first-party plugin distributions
* `examples/plugins/` for tutorial or third-party-style example packages

This makes package ownership visible in the filesystem instead of encoding it
only in packaging metadata.

### `bundle-official` is the accepted umbrella name

The accepted umbrella install name for the curated first-party plugin set is
`codira[bundle-official]`.

In Phase 1 the repository may still keep a monorepo scaffold such as
`packages/codira-bundle-official/`, but the user-facing bundle contract is
the `bundle-official` install target on `codira`. Repository-local
development may still need explicit editable installs for the component
packages until the distributions are published in a normal package index.

### Compatibility remains explicit during the transition

Phase 1 may keep narrow compatibility shims inside the core source tree when
that reduces churn for existing imports or tests.

Those shims are transitional and must not continue to own the extracted
implementation logic.

### Phase 2 widens the same rule to Python and the default backend

Phase 2 will apply the same package-boundary model to:

* the Python analyzer
* the default SQLite backend

That later phase will make even the default implementations conceptually
replaceable through external distributions.

## Consequences

### Positive

* the first-party plugin story now uses the same entry-point distribution model
  as third-party plugins
* the repository layout reflects package ownership directly
* optional analyzer support is validated through real package installs rather
  than only through extras
* future extraction of Python and backend implementations has a clear precedent
* `codira[bundle-official]` becomes the stable umbrella install contract for
  curated first-party capabilities

### Negative

* repository bootstrap and CI must install multiple editable packages instead of
  one extra-heavy core package
* some transitional compatibility surfaces will coexist temporarily with the
  new package layout
* release automation will later need to reason about multiple distributions

### Neutral / Trade-offs

* the semantic embedding stack may remain behind a core extra during this phase
  even though the umbrella bundle name is established now
* the repository remains a single VCS repository during Phase 1; package split
  does not imply repository split
* example packages remain useful even after first-party packages move under
  `packages/`

## Phase 1 Ledger

* [x] Accept `packages/` as the first-party plugin area
* [x] Accept `codira[bundle-official]` as the umbrella install name
* [x] Select `CAnalyzer` and `BashAnalyzer` as the first extraction targets
* [x] Reconcile repository-local bootstrap, CI, and user docs with the new
  package boundary
* [ ] Finish the Phase 1 extraction branch and merge it through issue `#11`

At the current branch state, the remaining unchecked Phase 1 item is the
integration close-out for issue `#11` itself. Bootstrap, CI, docs, package
metadata, and entry-point discovery have been reconciled on the long-lived
migration branch.
