# ADR-015 — Codira Development Roadmap

**Date:** 14/04/2026
**Status:** Accepted

## Context

This roadmap is derived from the current issue set (notably :contentReference[oaicite:0]{index=0}) and reflects:

- strong emphasis on deterministic behavior
- ongoing architectural stabilization (#7, #8, #9, #10)
- transition toward a plugin ecosystem
- expansion into multi-language and multi-repo contexts

The roadmap prioritizes:

1. **architectural correctness first**
2. **capability expansion second**
3. **ecosystem and tooling third**

---

## Decision

Adopt a **phased roadmap** with explicit release gates tied to architectural maturity.

---

## Phase 0 — Stabilization (pre-1.2.x → 1.30.0)

## Scope Ph 0

- #2 — Remove temporary Ruff fixes
- #7 — Capability contract
- #8 — Backend decoupling
- #9 — In-memory backend (contract validation)

## Rationale Ph 0

- These issues define **core invariants**
- Without them, all future extensions risk:
  - hidden coupling
  - non-determinism
  - unstable plugin surface

## Outcome Ph 0

- codira becomes:
  - **explicitly defined**
  - **backend-agnostic**
  - **testable across implementations**

## Release policy Ph 0

- No major public positioning yet
- Patch/minor releases acceptable

---

## Phase 1 — Production-readiness (→ 1.40.0)

## Scope Ph 1

- #10 — Multi-backend support
- #13 — Semgrep architectural guardrails
- #6 — Coverage model refactor

## Rationale Ph 1

- Transition from:
  - “works locally”
  - to “production-grade system”

- Introduce:
  - backend diversity
  - architectural enforcement
  - correct coverage semantics

## Outcome Ph 1

- codira becomes:
  - **robust**
  - **extensible**
  - **guarded against regressions**

## Release policy Ph 1

- First **stable minor release suitable for external users**
- Recommended tag: **1.40.0**

---

## Phase 2 — Core capability expansion (→ 1.50.0)

## Scope Ph 2

- #1 — Optional fallback analyzers
- #3 — Documentation channel
- #5 — Makefile analyzer
- #11 — C++ analyzer
- #12 — Lua analyzer

## Rationale Ph 2

- Expand **real-world repository coverage**
- Target high-impact ecosystems:
  - C/C++
  - build systems
  - Lua-based systems

## Key principle Ph 2

> prioritize analyzers that unlock large classes of repositories

## Outcome Ph 2

- codira becomes:
  - **multi-language**
  - **context-rich**
  - **useful beyond Python**

## Release policy Ph 2

- First release suitable for **broad adoption**
- Recommended tag: **1.50.0**

---

## Phase 3 — Ecosystem structuring (→ 1.60.0)

## Scope Ph 3

- #17 — Install-time configuration
- #18 — Plugin extraction readiness checklist
- #4 — Documentation audit plugin system

## Rationale Ph 3

- Transition from:
  - internal architecture
  - to **external ecosystem**

- Enable:
  - third-party plugins
  - configurable environments
  - consistent plugin quality

## Outcome Ph 3

- codira becomes:
  - **platform-ready**
  - **plugin-friendly**
  - **configurable**

## Release policy Ph 3

- First release suitable for **plugin ecosystem growth**
- Recommended tag: **1.60.0**

---

## Phase 4 — System-level capabilities (→ 1.70.0+)

## Scope Ph 4

- #15 — Multi-repo aggregation (“Codira family”)
- #14 — TeX/LaTeX analyzer (optional, domain-specific)

## Rationale Ph 4

- Move from:
  - repository-level understanding
  - to **system-level understanding**

- Address:
  - multi-repo architectures
  - domain-specific ecosystems

## Outcome Ph 4

- codira becomes:
  - **system analysis tool**
  - not just repository tool

## Release policy Ph 4

- Major feature release
- Recommended tag: **1.70.0+**

---

## Cross-cutting track — Tooling and workflow

## Scope

- #16 — Hyperfine integration

## Position

- Can be introduced **early (Phase 0–1)**
- Matured progressively

## Role

- Performance regression detection
- Release validation support

---

## Release Strategy Summary

| Phase   | Version | Purpose                     |
|---------|---------|-----------------------------|
| Phase 0 | ≤1.30.x | Architectural stabilization |
| Phase 1 | 1.40.0  | Production-ready core       |
| Phase 2 | 1.50.0  | Broad usability             |
| Phase 3 | 1.60.0  | Ecosystem readiness         |
| Phase 4 | 1.70.0+ | System-level capabilities   |

---

## Key Architectural Principles

1. Determinism over convenience
2. Explicit contracts over implicit behavior
3. Plugins over core bloat
4. Structure first, semantics later
5. Ecosystem after stability

## Final Statement

This roadmap enforces a strict progression:

```txt
architecture → capability → ecosystem → scale
```

Deviating from this order risks:

- instability
- plugin breakage
- architectural drift
