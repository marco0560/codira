# Codira Development Roadmap

## Status

This document is a living planning document.

Unlike ADRs, this roadmap does not record immutable architectural decisions. It captures current priorities, sequencing, dependencies, and expected development milestones. The roadmap may be revised as the project evolves, new requirements emerge, ecosystem needs change, or priorities shift.

The roadmap is organized around capabilities rather than issue numbers. Issue references are included for traceability but do not define the structure of the plan.

---

# Planning Assumptions

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

# Long-Term Objectives

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

# Phase 1 — Configuration Foundation

**Target Window:** June 2026

## Objectives

Establish configuration as the primary mechanism for analyzer selection and system customization.

## Issues

* #17 Install-time configuration system

## Deliverables

* Configuration file format
* Configuration discovery
* Analyzer selection rules
* Validation and diagnostics
* Configuration documentation

## Exit Criteria

* Analyzer ownership can be configured explicitly.
* Configuration validation is deterministic.
* Core analyzer selection semantics are defined.

---

# Phase 2 — Plugin Contract Stabilization

**Target Window:** July 2026

## Objectives

Stabilize the plugin architecture before ecosystem expansion.

## Issues

* #4 Extend plugin architecture and audit conventions
* #27 Configuration injection core ↔ plugin interface

## Deliverables

* Stable plugin contract
* Capability registration model
* Configuration injection mechanism
* Plugin audit requirements
* Plugin author documentation

## Exit Criteria

* Third-party analyzers can target a stable contract.
* Plugin configuration is fully supported.
* Plugin registration semantics are frozen.

---

# August 2026

## Planned Status

No planned roadmap work.

The month is intentionally reserved for:

* maintenance
* issue refinement
* backlog review
* documentation updates
* exploratory research

No major roadmap commitments should be scheduled.

---

# Phase 3 — Documentation & Context Retrieval

**Target Window:** September 2026

## Objectives

Treat repository documentation as a first-class information source.

## Issues

* #3 Documentation retrieval channel
* #32 ADR-006 signal aggregation migration

## Deliverables

* Documentation analyzer
* Documentation indexing
* Signal aggregation improvements
* Context extraction pipeline

## Exit Criteria

* Repository documentation is queryable.
* Context generation incorporates documentation-derived information.
* Documentation retrieval becomes part of the standard retrieval workflow.

---

# Phase 4 — Embedding Evaluation & Calibration

**Target Window:** October 2026

## Objectives

Understand the impact of documentation indexing on retrieval quality and storage requirements before introducing new storage technologies.

## Issues

* #28 Embeddings calibration

## Deliverables

* Embedding evaluation framework
* Retrieval benchmarking methodology
* Embedding calibration tooling
* Performance measurements
* Storage-growth analysis

## Exit Criteria

* Embedding effectiveness is quantified.
* Retrieval trade-offs are documented.
* Storage requirements are understood.

---

# Phase 5 — Optional Vector Backend

**Target Window:** November 2026

## Objectives

Provide optional semantic retrieval infrastructure while preserving deterministic baseline workflows.

## Issues

* #20 Optional vector database backend

## Deliverables

* Vector backend abstraction
* Optional vector storage implementation
* Benchmarking suite
* Retrieval comparison framework

## Exit Criteria

* Semantic retrieval remains optional.
* SQLite-only workflows remain supported.
* Retrieval behavior is measurable and documented.

---

# Phase 6 — Daemon Mode

**Target Window:** December 2026

## Objectives

Support incremental indexing and long-running retrieval workloads.

## Issues

* #22 Daemon mode

## Deliverables

* Background indexing service
* Incremental refresh support
* Repository monitoring
* Operational tooling

## Exit Criteria

* Daemon mode remains optional.
* Batch indexing remains canonical.
* Incremental updates function reliably.

---

# Phase 7 — Shared Repository Index Service

**Target Window:** January 2027

## Objectives

Support centralized indexing and retrieval across multiple repositories.

## Issues

* #51 Shared repository index service

## Deliverables

* Shared repository catalog
* Repository registration mechanism
* Shared retrieval infrastructure
* Shared embedding storage
* Service administration tooling

## Exit Criteria

* Multiple repositories can coexist within one service.
* Provenance remains explicit.
* Service mode and batch mode produce equivalent repository facts.

---

# Phase 8 — Core Language Expansion

**Target Window:** February–March 2027

## Objectives

Expand support for high-value software ecosystems.

## Issues

* #36 JavaScript analyzer
* #37 TypeScript analyzer
* #38 Go analyzer
* #43 PHP analyzer

## Deliverables

* First-wave language analyzers
* Expanded benchmark corpus
* Plugin-author reference implementations

## Exit Criteria

* Representative OSS repositories can be analyzed successfully.
* All analyzers comply with plugin contracts.

---

# Phase 9 — Secondary Language Expansion

**Target Window:** April–May 2027

## Objectives

Expand support for build systems, infrastructure, and additional mainstream ecosystems.

## Issues

* #5 Makefile analyzer
* #42 YAML/TOML/HCL analyzer
* #12 Lua analyzer
* #39 Java analyzer
* #44 Kotlin analyzer
* #49 Ruby analyzer
* #40 Rust analyzer

## Deliverables

* Additional first-party analyzers
* Expanded integration testing
* Broader repository coverage

## Exit Criteria

* Analyzer ecosystem covers major OSS repository types.
* Configuration-driven analyzer selection remains manageable.

---

# Phase 10 — Engineering & Legacy Language Expansion

**Target Window:** June–July 2027

## Objectives

Support engineering-oriented, scientific, hardware, and long-lived software ecosystems.

## Issues

* #46 Fortran analyzer
* #50 VHDL analyzer
* #48 Ada analyzer
* #45 Assembly analyzer
* #41 C# analyzer
* #14 TeX/LaTeX analyzer
* #47 COBOL analyzer

## Deliverables

* Scientific-computing support
* Hardware-design support
* Legacy-system support

## Exit Criteria

* Codira can analyze representative engineering repositories.
* Hardware and scientific repositories are first-class citizens.

---

# August 2027

## Planned Status

No planned roadmap work.

Reserved for:

* maintenance
* roadmap review
* issue grooming
* ecosystem feedback

---

# Phase 11 — Embedded Fragment Delegation

**Target Window:** September 2027

## Objectives

Support mixed-language files without introducing nested plugin architectures.

## Issues

* #35 Fragment delegation mechanism

## Deliverables

* Fragment descriptor model
* Embedded-fragment pipeline
* Fragment provenance tracking
* Fragment analyzer selection

## Examples

* C inline assembly
* Markdown fenced code blocks
* Documentation examples
* Template fragments

## Exit Criteria

* Primary analyzers can emit fragments.
* Fragment analyzers are selected through configuration.
* Provenance remains deterministic and auditable.

---

# Phase 12 — Multi-Repository Analysis

**Target Window:** October 2027

## Objectives

Move beyond isolated repository analysis.

## Issues

* #15 Multi-repo aggregation

## Deliverables

* Repository aggregation model
* Cross-repository indexing
* Cross-repository references
* Cross-repository retrieval

## Exit Criteria

* Related repositories can be indexed and queried together.
* Cross-repository relationships are discoverable.

---

# Phase 13 — Ecosystem & Publishing

**Target Window:** November–December 2027

## Objectives

Prepare Codira for a mature plugin ecosystem.

## Issues

* #18 Plugin extraction readiness checklist
* #33 Package split and publish rehearsal
* #34 Branch protection and trusted publishing verification

## Deliverables

* Plugin publication guidance
* Packaging validation
* Release automation
* Governance documentation

## Exit Criteria

* Third-party analyzers can be published independently.
* Publishing workflows are validated.

---

# Deferred Work

The following items remain intentionally deferred until sufficient ecosystem demand exists.

## Issue #1 — Optional Fallback Analyzers

Reason:

Fallback behavior introduces significant complexity and should only be considered once the analyzer ecosystem matures.

## Issue #6 — Config-First Analyzer-Aware Coverage Roots

Reason:

Depends on real-world usage patterns and ecosystem growth.

## Issue #29 — GitHub GraphQL Snapshot Pagination Tooling

Reason:

Maintenance-oriented work with limited architectural impact.

---

# Analyzer Priority

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

# Success Criteria

The roadmap will be considered successful if Codira achieves:

* Stable plugin architecture.
* Deterministic configuration-driven analyzer selection.
* Strong repository-context extraction.
* Broad language coverage.
* Healthy third-party analyzer ecosystem.
* Multi-repository analysis.
* Optional semantic retrieval.
* Optional service-based deployments.
* Reproducible and auditable outputs.
