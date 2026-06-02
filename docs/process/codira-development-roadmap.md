# Codira Development Roadmap

## Status

This document is a living planning document.

Unlike ADRs, this roadmap does not record immutable architectural decisions. It captures current priorities, sequencing, dependencies, and expected development milestones. The roadmap may be revised as the project evolves, new requirements emerge, ecosystem needs change, or priorities shift.

The roadmap is organized around capabilities rather than issue numbers. Issue references are included for traceability but do not define the structure of the plan.

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

## Phase 1 — Configuration Foundation

**Target Window:** June 2026

### Phase 1 Objectives

Establish configuration as the primary mechanism for analyzer selection and system customization.

### Phase 1 Issues

* #17 Install-time configuration system

### Phase 1 Deliverables

* Configuration file format
* Configuration discovery
* Analyzer selection rules
* Validation and diagnostics
* Configuration documentation

### Phase 1 Exit Criteria

* Analyzer ownership can be configured explicitly.
* Configuration validation is deterministic.
* Core analyzer selection semantics are defined.

---

## Phase 2 — Plugin Contract Stabilization

**Target Window:** July 2026

### Phase 2 Objectives

Stabilize the plugin architecture before ecosystem expansion.

### Phase 2 Issues

* #4 Extend plugin architecture and audit conventions
* #27 Configuration injection core ↔ plugin interface

### Phase 2 Deliverables

* Stable plugin contract
* Capability registration model
* Configuration injection mechanism
* Plugin audit requirements
* Plugin author documentation

### Phase 2 Exit Criteria

* Third-party analyzers can target a stable contract.
* Plugin configuration is fully supported.
* Plugin registration semantics are frozen.

---

## August 2026

### August 2026 Planned Status

No planned roadmap work.

The month is intentionally reserved for:

* maintenance
* issue refinement
* backlog review
* documentation updates
* exploratory research

No major roadmap commitments should be scheduled.

---

## Phase 3 — Documentation & Context Retrieval

**Target Window:** September 2026

### Phase 3 Objectives

Treat repository documentation as a first-class information source.

### Phase 3 Issues

* #3 Documentation retrieval channel
* #32 ADR-006 signal aggregation migration

### Phase 3 Deliverables

* Documentation analyzer
* Documentation indexing
* Signal aggregation improvements
* Context extraction pipeline

### Phase 3 Exit Criteria

* Repository documentation is queryable.
* Context generation incorporates documentation-derived information.
* Documentation retrieval becomes part of the standard retrieval workflow.

---

## Phase 4 — Repository Architecture Reporting

**Target Window:** October 2026

### Phase 4 Objectives

Transform repository intelligence into consumable architectural artifacts suitable for both human developers and AI agents.

### Phase 4 Issues

* #54 Repository Architecture Report Generator

### Phase 4 Deliverables

* Repository architecture domain model
* DOT graph generation
* Graphviz integration
* SVG architecture diagrams
* Markdown architecture reports
* Dependency statistics
* Cycle detection
* Layer-violation framework
* Architectural hotspot analysis

### Phase 4 Exit Criteria

* A single command can generate architecture artifacts.
* DOT output is deterministic.
* SVG generation works when Graphviz is available.
* Reports can be published directly as repository documentation.
* Architecture information is analyzer-independent.

---

## Phase 5 — Agent Efficiency Benchmarking

**Target Window:** November 2026

### Phase 5 Objectives

Measure and demonstrate the impact of Codira on AI-assisted repository analysis and modification workflows.

### Phase 5 Issues

* #53 Create Agent Efficiency Benchmark Suite

### Phase 5 Deliverables

* Benchmark schema
* Repository benchmark corpus
* Task-definition catalog
* Token accounting framework
* Baseline workflow measurements
* Codira-assisted workflow measurements
* Benchmark reporting and visualization

### Phase 5 Benchmark Categories

* Symbol discovery
* Impact analysis
* Architecture investigation
* Bug localization
* Patch preparation
* Documentation generation

### Phase 5 Exit Criteria

* Benchmarks are reproducible.
* Token savings can be quantified.
* Tool-call reductions can be quantified.
* Benchmark results are publishable.
* Multiple repository sizes and languages are represented.

---

## Phase 6 — Findings Interoperability (SARIF)

**Target Window:** December 2026

### Phase 6 Objectives

Provide standards-based integration with external code-scanning ecosystems.

### Phase 6 Issues

* #52 Add SARIF Output Support for Findings-Based Commands

### Phase 6 Deliverables

* Common finding model
* SARIF serializer
* GitHub Code Scanning compatibility
* Findings renderer abstraction
* SARIF documentation

### Phase 6 Exit Criteria

* SARIF output validates successfully.
* Findings can be uploaded to GitHub Code Scanning.
* Existing JSON and Markdown outputs remain unchanged.
* Findings-based commands support SARIF export.

---

## Phase 7 — Embedding Evaluation & Calibration

**Target Window:** January 2027

### Phase 7 Objectives

Understand the impact of documentation indexing and architecture reporting on retrieval quality and storage requirements before introducing new storage technologies.

### Phase 7 Issues

* #28 Embeddings calibration

### Phase 7 Deliverables

* Embedding evaluation framework
* Retrieval benchmarking methodology
* Embedding calibration tooling
* Performance measurements
* Storage-growth analysis

### Phase 7 Exit Criteria

* Embedding effectiveness is quantified.
* Retrieval trade-offs are documented.
* Storage requirements are understood.

---

## Phase 8 — Optional Vector Backend

**Target Window:** February 2027

### Phase 8 Objectives

Provide optional semantic retrieval infrastructure while preserving deterministic baseline workflows.

### Phase 8 Issues

* #20 Optional vector database backend

### Phase 8 Deliverables

* Vector backend abstraction
* Optional vector storage implementation
* Benchmarking suite
* Retrieval comparison framework

### Phase 8 Exit Criteria

* Semantic retrieval remains optional.
* SQLite-only workflows remain supported.
* Retrieval behavior is measurable and documented.

---

## Phase 9 — Daemon Mode

**Target Window:** March 2027

### Phase 9 Objectives

Support incremental indexing and long-running retrieval workloads.

### Phase 9 Issues

* #22 Daemon mode

### Phase 9 Deliverables

* Background indexing service
* Incremental refresh support
* Repository monitoring
* Operational tooling

### Phase 9 Exit Criteria

* Daemon mode remains optional.
* Batch indexing remains canonical.
* Incremental updates function reliably.

---

## Phase 10 — Shared Repository Index Service

**Target Window:** April 2027

### Phase 10 Objectives

Support centralized indexing and retrieval across multiple repositories.

### Phase 10 Issues

* #51 Shared repository index service

### Phase 10 Deliverables

* Shared repository catalog
* Repository registration mechanism
* Shared retrieval infrastructure
* Shared embedding storage
* Service administration tooling

### Phase 10 Exit Criteria

* Multiple repositories can coexist within one service.
* Provenance remains explicit.
* Service mode and batch mode produce equivalent repository facts.

---

## Phase 11 — Core Language Expansion

**Target Window:** May–June 2027

### Phase 11 Objectives

Expand support for high-value software ecosystems.

### Phase 11 Issues

* #36 JavaScript analyzer
* #37 TypeScript analyzer
* #38 Go analyzer
* #43 PHP analyzer

### Phase 11 Deliverables

* First-wave language analyzers
* Expanded benchmark corpus
* Plugin-author reference implementations

### Phase 11 Exit Criteria

* Representative OSS repositories can be analyzed successfully.
* All analyzers comply with plugin contracts.

---

## August 2027

### August 2027 Planned Status

No planned roadmap work.

Reserved for:

* maintenance
* roadmap review
* issue grooming
* ecosystem feedback

---

## Phase 12 — Embedded Fragment Delegation

**Target Window:** September 2027

### Phase 12 Objectives

Support mixed-language files without introducing nested plugin architectures.

### Phase 12 Issues

* #35 Fragment delegation mechanism

### Phase 12 Deliverables

* Fragment descriptor model
* Embedded-fragment pipeline
* Fragment provenance tracking
* Fragment analyzer selection

### Phase 12 Examples

* C inline assembly
* Markdown fenced code blocks
* Documentation examples
* Template fragments

### Phase 12 Exit Criteria

* Primary analyzers can emit fragments.
* Fragment analyzers are selected through configuration.
* Provenance remains deterministic and auditable.

---

## Phase 13 — Multi-Repository Analysis

**Target Window:** October 2027

### Phase 13 Objectives

Move beyond isolated repository analysis.

### Phase 13 Issues

* #15 Multi-repo aggregation

### Phase 13 Deliverables

* Repository aggregation model
* Cross-repository indexing
* Cross-repository references
* Cross-repository retrieval

### Phase 13 Exit Criteria

* Related repositories can be indexed and queried together.
* Cross-repository relationships are discoverable.

---

## Phase 14 — Ecosystem & Publishing

**Target Window:** November–December 2027

### Phase 14 Objectives

Prepare Codira for a mature plugin ecosystem.

### Phase 14 Issues

* #18 Plugin extraction readiness checklist
* #33 Package split and publish rehearsal
* #34 Branch protection and trusted publishing verification

### Phase 14 Deliverables

* Plugin publication guidance
* Packaging validation
* Release automation
* Governance documentation

### Phase 14 Exit Criteria

* Third-party analyzers can be published independently.
* Publishing workflows are validated.

---

## Phase 15 — Secondary Language Expansion

**Target Window:** January–February 2028

### Phase 15 Objectives

Expand support for build systems, infrastructure, and additional mainstream ecosystems.

### Phase 15 Issues

* #5 Makefile analyzer
* #42 YAML/TOML/HCL analyzer
* #12 Lua analyzer
* #39 Java analyzer
* #44 Kotlin analyzer
* #49 Ruby analyzer
* #40 Rust analyzer

### Phase 15 Deliverables

* Additional first-party analyzers
* Expanded integration testing
* Broader repository coverage

### Phase 15 Exit Criteria

* Analyzer ecosystem covers major OSS repository types.
* Configuration-driven analyzer selection remains manageable.

---

## Phase 16 — Engineering & Legacy Language Expansion

**Target Window:** March–April 2028

### Phase 16 Objectives

Support engineering-oriented, scientific, hardware, and long-lived software ecosystems.

### Phase 16 Issues

* #46 Fortran analyzer
* #50 VHDL analyzer
* #48 Ada analyzer
* #45 Assembly analyzer
* #41 C# analyzer
* #14 TeX/LaTeX analyzer
* #47 COBOL analyzer

### Phase 16 Deliverables

* Scientific-computing support
* Hardware-design support
* Legacy-system support

### Phase 16 Exit Criteria

* Codira can analyze representative engineering repositories.
* Hardware and scientific repositories are first-class citizens.

---

## Deferred Work

The following items remain intentionally deferred until sufficient ecosystem demand exists.

### Deferred Work — Issue #1 Optional Fallback Analyzers

Reason:

Fallback behavior introduces significant complexity and should only be considered once the analyzer ecosystem matures.

### Deferred Work — Issue #6 Config-First Analyzer-Aware Coverage Roots

Reason:

Depends on real-world usage patterns and ecosystem growth.

### Deferred Work — Issue #29 GitHub GraphQL Snapshot Pagination Tooling

Reason:

Maintenance-oriented work with limited architectural impact.

---

## Analyzer Priority

Current first-party analyzer priority:

1. Docs
2. JavaScript
3. TypeScript
4. Go
5. PHP
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
18. TeX/LaTeX
19. COBOL

This ordering reflects current expectations and may change as ecosystem needs evolve.

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
