# ADR-036 — Optional Clang C and C++ frontend pilot

**Date:** 24/10/2026

**Status:** Accepted for a bounded comparison pilot

## Context

The independently distributed C and C++ analyzers currently use Tree-sitter
for source analysis. Their parser and source-recovery behavior differs from a
compiler frontend on preprocessor-selected code, compiler extensions, language
versions, generated declarations, and template handling. Recent parser
diagnostics work has also built custom, bounded preprocessor and declaration
recovery paths. Extending those paths further would duplicate compiler behavior
and still leave semantic gaps.

The operator approved a fixed comparison of about 200 open original files,
including both LLVM and non-LLVM projects, C and C++, files with reproducible
compile context, and files whose context is absent or incomplete. The pilot is
an evidence-gathering step; it does not establish that Clang is equivalent to
the existing analyzer or that it should become the production frontend.

## Decision

Build and evaluate one optional Clang-backed frontend shared by the C and C++
analyzers. Keep Tree-sitter as the default and as the fallback when Clang is
not selected, unavailable, or cannot run with a complete supported profile.
The pilot does not expand the custom preprocessor or declaration-recovery
implementation.

The pilot uses a deterministic, source-hash-bound cohort of 200 files: 100
from LLVM and 100 from non-LLVM projects, with 50 C and 50 C++ files in each
population. Selection is balanced by repository where possible, broad source
feature evidence, source size, and whether an existing compile profile and
dependency evidence are available. Family labels are sampling hints, not
root-cause adjudications. Missing or partial compile context remains in the
cohort denominator and is reported as held; it does not trigger replacement by
an easier file. The generator, seed, canonical classification digest, exact
source digests, pinned repository revisions, and retained context evidence are
recorded with the manifest under the parser-diagnostics pilot artifact root.
The actual cohort and current context census are documented in the
[pilot census report](../process/analyzer-parser-diagnostics-clang-frontend-pilot-census-2026-10-24.md).

The comparison must preserve the original compile command, working directory,
driver identity, and source/dependency evidence separately from the Clang
syntax-only adaptation. Every adaptation records the exact argv, the changes
made, and unsupported or missing context. A GCC or other non-Clang project
command is not relabeled as a Clang command. No build system is run by the
adapter. No target flags, include directories, macro definitions, or language
modes may be guessed or silently synthesized.

Clang output is a frontend result, not its own correctness oracle. Qualification
uses independent source or fixture evidence and reports oracle coverage
separately from frontend completion. Compiler-visible inactive-branch behavior,
implicit declarations, and template instantiations are not assumed to match the
existing source-written Tree-sitter contract. The pilot records written source
entities and compiler-produced entities with distinct provenance and calls out
where the two contracts differ. A clean AST, successful compiler exit, or
Clang/Clang agreement alone does not qualify a file as fixed.

## Scope and compatibility boundary

This ADR narrows the compiler-free constraint stated by
[ADR-034](ADR-034-bounded-cpp-declaration-macro-analysis.md) and
[ADR-035](ADR-035-bounded-c-declaration-macro-analysis.md) only for an explicitly
selected, optional Clang frontend mode. It does not change the existing
Tree-sitter mode, its defaults, its fallback behavior, or existing analyzer
configuration. It does not make a compiler, CMake, Make, or another build
system mandatory for indexing.

The pilot does not change analyzer schemas, public analyzer behavior, default
frontend selection, package versions, runtime requirements, or release pins. It
does not update the canonical parser-diagnostics classification ledger or
admit cohort files as verified fixes. Such changes require a later decision
grounded in the pilot results.

## Measurement and decision criteria

Report results independently for LLVM and non-LLVM files and for C and C++.
Include cohort size, profile-context coverage, held cases and reasons,
independently graded source-written declarations and calls, diagnostics,
unsupported fields, false additions or omissions, per-file runtime, and
resource cost. Keep context-qualified semantic accuracy separate from the
percentage of rows on which the frontend completed.

Compare the cost and coverage of the shared frontend with the existing
Tree-sitter path and the custom recovery work already present. Explain the
tradeoffs and limitations to the operator. This ADR sets no arbitrary
percentage threshold and makes no automatic production go/no-go decision; a
production choice follows from the measured evidence and operator review.

## Future package boundary

If a later production decision favors Clang, keep the shared frontend outside
Codira core and reusable by both independently distributed analyzer plugins.
The likely boundary is a separately versioned first-party Clang frontend
package consumed by the C and C++ analyzer packages. Its compiler discovery,
process boundary, profile contract, normalized metadata, partial-coverage
behavior, and platform support require a separate design before production
integration. The pilot alone does not create or pin that package.

## Consequences

The comparison can test whether a shared compiler frontend improves
context-qualified source understanding across both analyzer plugins without
changing existing users' defaults. It also exposes the cost of compiler
availability and exact build context. Rows lacking that context remain visible
as held results, so measured completion cannot be mistaken for coverage of the
whole selected population.

Clang and Tree-sitter may expose different entities because a compiler
evaluates preprocessor branches and templates. Qualification must preserve
those differences rather than treating all compiler output as source-written
symbols. The measured results may therefore support a limited opt-in mode,
additional profile tooling, or retaining Tree-sitter as the sole supported
frontend; this pilot does not predetermine which outcome follows.
