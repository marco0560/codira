# ADR-037 — Optional shared Clang production integration

**Date:** 26/10/2026

**Status:** Accepted for implementation and independent integration qualification

## Context

[ADR-036](ADR-036-optional-clang-c-cpp-frontend-pilot.md) established a bounded
comparison, committed as `078b341`. Its 200-input cohort produced 27 complete
frontend captures, 23 partial captures, and 150 held inputs. Only 50 inputs had
supported compilation-database profiles and invoked the helper. No independent
corpus semantic grades or verified file admissions resulted from that pilot.
The results support further integration, without establishing a replacement
default or a backlog closure rate. Missing build context, particularly generated
C++ headers, remains a separate problem from syntax recognition.

The operator approved an optional shared frontend, explicit compile profiles,
dependencies and cache provenance, no further development of the custom preprocessor,
and a small real indexing/persistence qualification including a non-LLVM original.
The operator requires a report and pause as soon as evidence supports committing
fully to the new engineering direction. That decision is distinct from making
Clang mandatory for all installations or changing the default frontend.

## Decision

Add `codira-clang-frontend` as a separately versioned first-party distribution
outside Codira core. Both C and C++ analyzer plugins consume its shared compiler
interface. Tree-sitter remains the default and the lightweight fallback. Clang
selection is explicit in each plugin's configuration and its Python dependency
is optional. Do not extend the custom preprocessor as part of this work.

Keep the native helper behind a process boundary with a versioned protocol.
Native compilation is an explicit preparation operation, separate from analysis.
Indexing must not execute a project build system or silently compile a helper.
The initial integration may require explicitly supplied helper and build-receipt
paths; it must document that operational requirement rather than implying that
installing a Python wheel supplies a supported native binary on every platform.

Accept actual compilation-database entries and explicitly retained compiler
argument records with their working directories and source bindings. Preserve
original driver identity and arguments separately from the audited Clang
adaptation. Do not guess flags, include directories, language versions or
generated headers. Unsupported or missing context remains visible.

Record source, profile, compiler, helper, resource and dependency identities.
Bind analysis reuse to those inputs and the frontend version, using the existing
analyzer fingerprint contract. Changing a header or compile profile must invalidate
an unchanged source file's cached result. Reusing Tree-sitter output as a successful
Clang result is prohibited. Keep raw success and failure evidence in fresh durable
attempt directories.

The shared frontend returns typed compiler records independent of core DTOs.
The analyzer adapters map supported records into the existing `AnalysisResult`
contract. Preserve source-written versus compiler-generated distinctions,
spelling versus expansion coordinates, callable ownership and diagnostics.
Do not merge two frontend outputs and thereby introduce duplicate or inconsistent
symbols. When Clang cannot supply a supported result, fallback must expose the
limitation through the existing persisted analysis status.

The current call-site DTO cannot carry the compiler's resolved overload target
identity. Overloaded calls remain explicitly unresolved in this initial slice;
the raw compiler evidence retains the target identity. Metadata omissions are
recorded as partial coverage, including macro declarations and body flags.

## Qualification and decision boundary

Exercise the actual indexer and both SQLite and DuckDB persistence using
source-authored expected symbols and calls for C and C++. Cover macro expansion,
conditional activity and relevant C++ ownership/provenance distinctions. Include
an original non-LLVM source with retained compiler context; a synthetic fixture
with a repository label does not satisfy that requirement.

Check false additions and omissions, caller ownership, persisted status and
fingerprints. Exercise unchanged-source reindexing after context changes, and
verify explicit fallback for missing or unsupported context. A successful helper
exit, clean AST or agreement between two Clang captures is insufficient evidence.

Run the repository's focused checks, preflight and full gate before a validated
atomic commit. Record actual qualification coverage and remaining limitations
in a durable report. Do not update the canonical remediation ledger without
its independent original-file admission evidence.

The initial package is experimental. This ADR authorizes implementation and
qualification; it does not authorize publishing, switching defaults or declaring
all C/C++ gaps fixed. The next architecture decision follows the resulting
evidence and operator review.
