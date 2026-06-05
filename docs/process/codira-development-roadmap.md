# Codira Development Roadmap

## Status

This document is a living planning document.

Unlike ADRs, this roadmap does not record immutable architectural decisions. It captures current priorities, sequencing, dependencies, and expected development milestones. The roadmap may be revised as the project evolves, new requirements emerge, ecosystem needs change, or priorities shift.

The roadmap is organized around release-sized capability milestones rather than issue numbers. Issue references are included for traceability but do not define the structure of the plan.

---

## Planning Assumptions

The following assumptions guide roadmap decisions.

1. Determinism takes precedence over convenience.
2. Configuration takes precedence over automatic analyzer selection.
3. All analyzers are peers; there is no nested plugin hierarchy.
4. First-party analyzers cover common, stable, high-value cases.
5. Specialized dialects and frameworks are ecosystem extensions.
6. The configuration file decides which analyzer owns each file set.
7. Ambiguous analyzer ownership is a configuration error, not a heuristic decision.
8. Repository understanding is a first-class goal alongside source-code analysis.
9. New analyzers must conform to the existing plugin contract rather than introducing special cases.
10. Architectural simplicity is preferred over exhaustive automatic detection.
11. Local deterministic batch indexing remains the canonical execution model.
12. Daemons, vector databases, and shared services are optional deployment modes.
13. Provenance must remain explicit and auditable throughout the pipeline.
14. Public PyPI releases should land at meaningful capability boundaries.
15. Active phases should remain close to four weeks unless a milestone is explicitly split or deferred.

---

## Long-Term Objectives

The long-term goals of Codira are:

* Deterministic repository indexing.
* Deterministic symbol extraction.
* Deterministic call graph generation.
* Deterministic reference graph generation.
* Repository-context extraction.
* Documentation-aware retrieval.
* Extensible plugin ecosystem.
* Multi-language repository support.
* Multi-repository analysis.
* Optional semantic retrieval.
* Optional service-based deployments.
* Reproducible and auditable outputs.

---

## Completed Foundations — Configuration, Documentation, and Calibration

**Target Window:** completed by 04/06/2026
**Release Boundary:** pre-1.50.0 foundation
**Status:** Completed

### Completed Foundation Objectives

Establish configuration, plugin configuration injection, documentation retrieval, signal aggregation migration, and hardware-aware embedding calibration as stable foundations for the next public release series.

### Completed Foundation Issues

* [x] #3 Documentation retrieval channel
* [x] #17 Install-time configuration system
* [x] #27 Configuration injection core ↔ plugin interface
* [x] #28 Embeddings calibration
* [x] #32 ADR-006 signal aggregation migration

### Completed Foundation Deliverables

* Configuration file format
* Configuration discovery
* Analyzer selection rules
* Plugin configuration injection
* Documentation indexing and retrieval
* Signal aggregation migration
* Hardware-aware embedding calibration
* Configuration and retrieval documentation

### Completed Foundation Exit Criteria

* Analyzer ownership can be configured explicitly.
* Plugin configuration is injected deterministically.
* Repository documentation is queryable.
* Embedding calibration can be generated and validated.

---

## Phase 1 — Contract and Analyzer Concurrency Foundation

**Target Window:** 05/06/2026–03/07/2026
**Release Milestone:** v1.50.0 - Contract and analyzer concurrency foundation

### Phase 1 Objectives

Stabilize the plugin and analyzer-facing contracts needed before ecosystem expansion and parallel indexing.

### Phase 1 Issues

* #4 Extend plugin architecture and audit conventions
* #6 Config-first, analyzer-aware coverage roots
* #55 Parallelize full indexing with explicit analyzer concurrency contracts

### Phase 1 Deliverables

* Stable plugin contract
* Analyzer audit requirements
* Plugin author documentation
* Config-first coverage root policy
* Analyzer concurrency declaration contract
* Index analysis concurrency configuration
* Serial-vs-parallel analyzer verification strategy

### Phase 1 Exit Criteria

* Third-party analyzers can target a stable contract.
* Analyzer ownership and coverage roots are configuration-driven.
* Analyzer concurrency support is explicit and fail-closed.
* Serial and concurrent analysis results can be compared deterministically.

---

## Phase 2 — Backend Concurrency and Staged Index Runs

**Target Window:** 06/07/2026–31/07/2026
**Release Milestone:** v1.60.0 - Backend concurrency contract

### Phase 2 Objectives

Define backend write-concurrency semantics that work for current in-process backends and future server-backed storage.

### Phase 2 Issues

* #56 Define backend write-concurrency contracts and staged index runs

### Phase 2 Deliverables

* Backend write-concurrency declaration contract
* Fail-closed backend concurrency configuration
* Staged index-run contract
* Serial backend compatibility strategy
* Fake staged backend contract tests
* Documentation for SQLite, DuckDB, memory, and future server DB caveats

### Phase 2 Exit Criteria

* Current backends explicitly declare serial-only write support.
* Unsupported backend concurrency modes fail before mutation.
* Staged run semantics are documented and testable.
* Future PostgreSQL, MySQL, and MariaDB plugins have a clear contract target.

---

## Phase 3 — Architecture and Findings Reporting

**Target Window:** 01/09/2026–25/09/2026
**Release Milestone:** v1.70.0 - Architecture and findings reporting

### Phase 3 Objectives

Transform repository intelligence into consumable artifacts and standardized findings suitable for developers, AI agents, and external code-scanning workflows.

### Phase 3 Issues

* #52 Add SARIF output support for findings-based commands
* #54 Repository Architecture Report Generator

### Phase 3 Deliverables

* Repository architecture domain model
* DOT graph generation
* Graphviz integration
* SVG architecture diagrams
* Markdown architecture reports
* Dependency statistics
* Cycle detection
* Layer-violation framework
* Common finding model
* SARIF serializer
* GitHub Code Scanning compatibility

### Phase 3 Exit Criteria

* A single command can generate architecture artifacts.
* DOT output is deterministic.
* Reports can be published directly as repository documentation.
* Findings can be exported as SARIF without changing existing JSON or Markdown outputs.

---

## Phase 4 — Agent Efficiency Benchmarking

**Target Window:** 28/09/2026–23/10/2026
**Release Milestone:** v1.80.0 - Agent efficiency benchmarks

### Phase 4 Objectives

Measure and demonstrate the impact of Codira on AI-assisted repository analysis and modification workflows.

### Phase 4 Issues

* #53 Create Agent Efficiency Benchmark Suite

### Phase 4 Deliverables

* Benchmark schema
* Repository benchmark corpus
* Task-definition catalog
* Token accounting framework
* Baseline workflow measurements
* Codira-assisted workflow measurements
* Benchmark reporting and visualization

### Phase 4 Benchmark Categories

* Symbol discovery
* Impact analysis
* Architecture investigation
* Bug localization
* Patch preparation
* Documentation generation

### Phase 4 Exit Criteria

* Benchmarks are reproducible.
* Token savings can be quantified.
* Tool-call reductions can be quantified.
* Benchmark results are publishable.
* Multiple repository sizes and languages are represented.

---

## Phase 5 — Semantic Storage and Long-Running Indexing

**Target Window:** 26/10/2026–20/11/2026
**Release Milestone:** v1.90.0 - Semantic storage and daemon preparation

### Phase 5 Objectives

Prepare optional semantic storage and long-running indexing modes while preserving deterministic batch indexing.

### Phase 5 Issues

* #20 Optional vector database backend
* #22 Daemon mode

### Phase 5 Deliverables

* Vector backend abstraction
* Optional vector storage implementation
* Retrieval comparison framework
* Background indexing service design
* Incremental refresh support
* Repository monitoring strategy

### Phase 5 Exit Criteria

* Semantic retrieval remains optional.
* Batch indexing remains canonical.
* Long-running indexing has explicit operational boundaries.
* Retrieval behavior remains measurable and documented.

---

## Phase 6 — Shared Service and Multi-Repository Analysis

**Target Window:** 23/11/2026–18/12/2026
**Release Milestone:** v2.0.0 - Shared repository service

### Phase 6 Objectives

Support centralized indexing and retrieval across multiple repositories.

### Phase 6 Issues

* #15 Multi-repo aggregation
* #51 Shared repository index service

### Phase 6 Deliverables

* Shared repository catalog
* Repository registration mechanism
* Shared retrieval infrastructure
* Shared embedding storage
* Cross-repository indexing
* Cross-repository references
* Service administration tooling

### Phase 6 Exit Criteria

* Multiple repositories can coexist within one service.
* Provenance remains explicit.
* Service mode and batch mode produce equivalent repository facts.
* Related repositories can be indexed and queried together.

---

## Phase 7 — First-Wave Web and Systems Analyzers

**Target Window:** 04/01/2027–29/01/2027
**Release Milestone:** v2.1.0 - First-wave analyzer expansion

### Phase 7 Objectives

Expand support for high-value web, service, and systems repositories.

### Phase 7 Issues

* #36 JavaScript analyzer
* #37 TypeScript analyzer
* #38 Go analyzer
* #43 PHP analyzer

### Phase 7 Deliverables

* JavaScript analyzer
* TypeScript analyzer
* Go analyzer
* PHP analyzer
* Expanded benchmark corpus
* Plugin-author reference implementations

### Phase 7 Exit Criteria

* Representative OSS repositories in the first-wave language set can be analyzed successfully.
* All analyzers comply with plugin contracts.
* Analyzer fixtures cover symbols, relations, declarations, and failure modes.

---

## August 2026 Stabilization Window

### August 2026 Planned Status

August 2026 is intentionally reserved for:

* stabilization
* maintenance
* issue refinement
* backlog review
* documentation cleanup
* release feedback

No roadmap issues should be scheduled in August.

---

## January 2027 Maintenance Window

### January 2027 Planned Status

The first week of January is reserved for:

* maintenance
* roadmap review
* release feedback
* issue grooming
* dependency updates

No major roadmap commitments should be scheduled before 04/01/2027.

---

## Phase 8 — Fragment Delegation and Documentation Fragments

**Target Window:** 01/02/2027–26/02/2027
**Release Milestone:** v2.2.0 - Fragment-aware analysis

### Phase 8 Objectives

Support mixed-language files and documentation examples without introducing nested plugin architectures.

### Phase 8 Issues

* #14 TeX/LaTeX analyzer
* #35 Fragment delegation mechanism

### Phase 8 Deliverables

* Fragment descriptor model
* Embedded-fragment pipeline
* Fragment provenance tracking
* Fragment analyzer selection
* TeX/LaTeX analyzer

### Phase 8 Examples

* Markdown fenced code blocks
* Documentation examples
* Template fragments
* TeX/LaTeX embedded examples

### Phase 8 Exit Criteria

* Primary analyzers can emit fragments.
* Fragment analyzers are selected through configuration.
* Provenance remains deterministic and auditable.
* TeX/LaTeX repositories can be indexed at a useful baseline level.
* Fragment delegation can be tested without relying on analyzers scheduled for later phases.

---

## Phase 9 — Ecosystem and Publishing Readiness

**Target Window:** 01/03/2027–26/03/2027
**Release Milestone:** v2.3.0 - Ecosystem publishing readiness

### Phase 9 Objectives

Prepare Codira for a mature plugin ecosystem and trusted public releases.

### Phase 9 Issues

* #18 Plugin extraction readiness checklist
* #33 Package split and publish rehearsal
* #34 Branch protection and trusted publishing verification

### Phase 9 Deliverables

* Plugin extraction readiness checklist
* Plugin publication guidance
* Packaging validation
* Release automation validation
* Branch protection verification
* Trusted publishing verification
* Governance documentation

### Phase 9 Exit Criteria

* Third-party analyzers can be published independently.
* Publishing workflows are validated.
* Repository protection and release automation are verified.

---

## Phase 10 — Build and Infrastructure Analyzers

**Target Window:** 29/03/2027–23/04/2027
**Release Milestone:** v2.4.0 - Build and infrastructure analyzers

### Phase 10 Objectives

Expand support for build systems, scripts, and infrastructure configuration files.

### Phase 10 Issues

* #5 Makefile analyzer
* #12 Lua analyzer
* #42 YAML/TOML/HCL analyzer

### Phase 10 Deliverables

* Makefile analyzer
* Lua analyzer
* Infrastructure configuration analyzer
* Expanded integration testing

### Phase 10 Exit Criteria

* Build and infrastructure repositories are covered by first-party analyzers.
* Configuration-driven analyzer selection remains manageable.

---

## Phase 11 — JVM, Systems, and Scripting Analyzers

**Target Window:** 26/04/2027–21/05/2027
**Release Milestone:** v2.5.0 - JVM, systems, and scripting analyzers

### Phase 11 Objectives

Expand mainstream application and systems-language coverage.

### Phase 11 Issues

* #39 Java analyzer
* #40 Rust analyzer
* #44 Kotlin analyzer
* #49 Ruby analyzer

### Phase 11 Deliverables

* Java analyzer
* Kotlin analyzer
* Ruby analyzer
* Rust analyzer
* Expanded repository corpus

### Phase 11 Exit Criteria

* Representative JVM, Ruby, and Rust repositories can be analyzed successfully.
* Analyzer behavior remains deterministic across the expanded language set.

---

## Phase 12 — Engineering Language Analyzers

**Target Window:** 24/05/2027–18/06/2027
**Release Milestone:** v2.6.0 - Engineering language analyzers

### Phase 12 Objectives

Support engineering-oriented, scientific, and hardware software ecosystems.

### Phase 12 Issues

* #45 Assembly analyzer
* #46 Fortran analyzer
* #48 Ada analyzer
* #50 VHDL analyzer

### Phase 12 Deliverables

* Assembly analyzer
* Fortran analyzer
* Ada analyzer
* VHDL analyzer
* Hardware-design fixtures
* Scientific-computing fixtures

### Phase 12 Exit Criteria

* Codira can analyze representative engineering repositories.
* Hardware and scientific repositories are first-class citizens.

---

## Phase 13 — Enterprise and Legacy Language Analyzers

**Target Window:** 21/06/2027–16/07/2027
**Release Milestone:** v2.7.0 - Enterprise and legacy analyzers

### Phase 13 Objectives

Round out enterprise and long-lived software ecosystem support.

### Phase 13 Issues

* #41 C# analyzer
* #47 COBOL analyzer

### Phase 13 Deliverables

* C# analyzer
* COBOL analyzer
* Enterprise repository fixtures
* Legacy-system repository fixtures

### Phase 13 Exit Criteria

* Representative enterprise and legacy repositories can be indexed.
* Analyzer contracts remain stable across the mature first-party language set.

---

## August 2027 Stabilization Window

### August 2027 Planned Status

August 2027 is intentionally reserved for:

* stabilization
* maintenance
* roadmap review
* issue grooming
* ecosystem feedback
* release follow-up

No roadmap issues should be scheduled in August.

---

## Phase 14 — Optional Fallback and Parse-Gap Handling

**Target Window:** 06/09/2027–01/10/2027
**Release Milestone:** v2.8.0 - Optional fallback analyzers

### Phase 14 Objectives

Revisit optional fallback analyzers after the primary analyzer ecosystem has matured.

### Phase 14 Issues

* #1 Optional fallback analyzers

### Phase 14 Deliverables

* Optional fallback analyzer policy
* Whole-file parse-gap handling
* Fragment-level parse-gap handling
* Deterministic fallback diagnostics

### Phase 14 Exit Criteria

* Fallback behavior remains optional.
* Fallback behavior does not weaken explicit analyzer ownership.
* Parse gaps are reported deterministically.

---

## Deferred Work

The following items remain intentionally deferred until sufficient maintenance demand exists.

### Deferred Work — Issue #29 GitHub GraphQL Snapshot Pagination Tooling

Reason:

Maintenance-oriented work with limited architectural impact.

---

## Analyzer Priority

Current first-party analyzer priority:

1. JavaScript
2. TypeScript
3. Go
4. PHP
5. TeX/LaTeX
6. Makefile
7. YAML/TOML/HCL
8. Lua
9. Java
10. Kotlin
11. Ruby
12. Rust
13. Fortran
14. VHDL
15. Ada
16. Assembly
17. C#
18. COBOL

This ordering reflects the release milestones above and may change as ecosystem needs evolve.

---

## Success Criteria

The roadmap will be considered successful if Codira achieves:

* Stable plugin architecture.
* Deterministic configuration-driven analyzer selection.
* Strong repository-context extraction.
* Repository architecture reporting.
* Agent-oriented repository workflows.
* Broad language coverage.
* Healthy third-party analyzer ecosystem.
* Multi-repository analysis.
* Optional semantic retrieval.
* Optional service-based deployments.
* Reproducible and auditable outputs.
