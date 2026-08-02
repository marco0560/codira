# Codira Development Roadmap

## Status

This is the versioned execution plan approved on 2026-08-02. It orders work by
adoption value and dependency: agent access, evidence, mainstream coverage and
freshness, productization, then differentiated and long-tail capabilities.

Local deterministic batch indexing remains canonical. Daemons, vector
databases, shared services, and semantic retrieval are optional deployment
modes; provenance and deterministic facts remain authoritative.

## Completed Foundations

Completed before this roadmap: configuration and plugin configuration (#17,
#27); documentation retrieval (#3); embedding calibration (#28); signal
aggregation (#32); plugin/analyzer contracts and concurrency (#4, #6, #55).

## Deferred Design: Backend Write Concurrency

**Tracked by:** #56
**Status:** deferred; not scheduled and not a release gate.

Reopen only after either an approved genuinely multi-writer server backend, or
a reproducible persistence bottleneck plus a staged prototype that improves
end-to-end time by at least 20% while preserving determinism and reader
isolation. A future design must preserve the `codira.storage` / backend-plugin
boundary for lifecycle paths, metadata, run identity, and activation state.

## Execution Sequence

1. Agent-ready local MCP and automatic freshness.
2. Reproducible comparative evidence.
3. JavaScript, TypeScript/TSX, Go, and federation readiness.
4. Productization and a gated shared-service decision.
5. Rust, Java, PHP, architecture intelligence, and SARIF.
6. Universal structural/text baseline, fragments, and build/infrastructure.
7. Second-wave and long-tail language coverage.

Blocked work is scheduled after its blockers: #33 after #18; #1 after #67 and
#35; #51 after #15, #20, #22, and #68.

## v1.70.0 — Agent-ready local MCP

**Window:** 2026-08-03 to 2026-10-02

Deliver a usable local stdio MCP server, not only a design specification.

* #58 MCP epic
* #22 daemon mode for local watching, incremental refresh, and freshness
* #61 roadmap/milestone reconciliation
* #62 versioned MCP contract
* #63 local stdio server and direct-core adapter
* #64 trusted roots and output budgets
* #65 client presets and integration suite
* #66 compact agent-oriented repository map

Exit criteria: local read-only MCP has deterministic direct-core tools,
authorized repository roots, bounded results, explicit freshness, and tested
client setup. Multi-repository and shared service are explicitly out of scope.

## v1.80.0 — Evidence and Comparative Benchmarks

**Window:** 2026-10-05 to 2026-11-20

* #53 agent-efficiency benchmark suite
* #59 embedding retrieval quality benchmark
* #68 evidence gates for optional vector and shared-service deployment

Exit criteria: public and private reproducible fixtures, deterministic task
oracles, task-success-first reporting, native and Codira baselines, and a
documented gate for #20 and #51.

## v1.90.0 — Mainstream Coverage and Federation Readiness

**Window:** 2026-11-23 to 2027-01-29

* #36 JavaScript analyzer
* #37 TypeScript and TSX analyzer
* #38 Go analyzer
* #15 multi-repository aggregation
* #20 vector-backend gate decision

The #20 gate follows #59 and #68. Implement a new vector backend only when the
benchmark demonstrates a material recall, latency, or memory limit in an
important repository class; otherwise convert #20 to deferred with that gate.

## v2.0.0 — Product Platform and Shared-Service Decision

**Window:** 2027-02-01 to 2027-04-30

* #18 plugin extraction readiness
* #33 final package split and publish rehearsal, after #18
* #34 trusted publishing verification, after #33
* #51 shared repository index service gate/implementation
* #69 productization baseline and support-tier contract

The #51 gate follows #15, #20, #22, and #68. It requires stable MCP, verified
clients, benchmark coverage, and demonstrated multi-repository/local-index
adoption; otherwise convert #51 to deferred with those reopening criteria.

## v2.10.0 — Mainstream Expansion and Repository Intelligence

**Window:** 2027-05-03 to 2027-07-30

* #40 Rust analyzer
* #39 Java analyzer
* #43 PHP analyzer
* #54 complete repository architecture report
* #52 SARIF output

#66 is the early agent-facing slice of #54. This release completes dependency
graphs and cycles, hotspots, layer rules, DOT/SVG rendering, and the human
report. SARIF follows rather than precedes agent adoption and benchmark proof.

## v2.20.0 — Universal Baseline

**Window:** 2027-08-02 to 2027-10-29

* #5 Makefile analyzer
* #12 Lua analyzer
* #42 YAML/TOML/HCL analyzer
* #67 structural and text fallback baseline
* #35 fragment delegation
* #14 TeX/LaTeX analyzer
* #1 optional fallback analyzers, after #67 and #35

Support tiers are explicit: Tier A is language semantic; Tier B is structural;
Tier C is text retrieval. Fragment recovery never replaces authoritative
primary-parser facts.

## v2.30.0 — Second-Wave Language Coverage

**Window:** 2027-11-01 to 2028-01-28

* #44 Kotlin analyzer
* #49 Ruby analyzer
* #41 C# analyzer

## v2.40.0 — Long-Tail Language Coverage

**Window:** 2028-01-31 to 2028-05-26

* #45 Assembly analyzer
* #46 Fortran analyzer
* #48 Ada analyzer
* #50 VHDL analyzer
* #47 COBOL analyzer

## Planning Rules

* Releases use a roughly four-week cadence only when their scope permits it;
  the larger integration releases above deliberately have longer windows.
* Every open issue is assigned to a release or a scheduled gate decision.
* Only #56 is excluded from operational scheduling because it already has
  explicit deferred reopening gates.
* New analyzer work must remain a separate plugin conforming to the existing
  contract, with deterministic fixtures and explicit supported capabilities.
