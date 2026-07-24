# Issue 4 Documentation Audit Plugins Execution Ledger

## Control Plane

- Issue: #4, extend plugin architecture and audit conventions.
- Branch: `feat/documentation-audit-plugins`.
- Validation gate before every commit: `uv run python scripts/validate_repo.py`.
- Commit policy: use `commit-block-generator`; each commit has a Conventional Commit subject, body, and validation statement.
- Closure footer: reserve `Closes #4` for the final implementation commit.

## Decisions

- Documentation audits are a separate plugin family, not analyzer hooks.
- Documentation audit plugins are associated with a language and convention.
- More than one documentation audit plugin may be active for a language.
- Routing is explicit and ordered by language plus path rules; unmatched or ambiguous routing fails with a configuration diagnostic.
- First release scope covers NumPy and Google-style Python plus Doxygen for C and C++ files.
- Compatibility mode requires explicit configuration for documentation audit execution.

## Non-Goals

- Do not replace language analyzers with documentation audit plugins.
- Do not make convention selection implicit when more than one plugin can match.
- Do not silently retain legacy docstring audit rows after configuration changes.
- Do not close the v1.50.0 milestone until the issue is implemented and synced externally.

## Phase Checklist

| Phase | Scope | Status | Commit |
| --- | --- | --- | --- |
| 0 | Branch and execution ledger | Complete | `aeb0708` |
| 1 | Architecture contract | Complete | `f29ca7c` |
| 2 | Configuration and routing | Complete | `6cd76db` |
| 3 | Registry, audit execution, and persistence | Complete | `6cd76db` |
| 4 | First-party documentation audit packages | Complete | `8ed353e` |
| 5 | Test matrix and migration verification | Complete | `223f91e` |
| 6 | Documentation upgrade | Complete | `1519ccd` |
| 7 | Final validation and closure | Complete | `b954264` |
| 8 | Correct package boundary and persisted provenance | Complete | `e8571f3` |

## Per-Commit Evidence

| Commit | Phase | Validation | Notes |
| --- | --- | --- | --- |
| `aeb0708` | 0 | `uv run python scripts/validate_repo.py` passed with 578 tests. | Ledger created before feature edits. |
| `f29ca7c` | 1 | `uv run python scripts/validate_repo.py` passed with 580 tests. | Added documentation audit contract, route config, and ADR. |
| `6cd76db` | 2-3 | `uv run python scripts/validate_repo.py` passed with 583 tests. | Added documentation-audit registry family, explicit route execution, built-in NumPy/Google/Doxygen plugins, backend routing, and test updates. |
| `8ed353e` | 4 | `uv run python scripts/validate_repo.py` passed with 589 tests. | Added NumPy, Google Python, and Doxygen documentation-audit distributions plus bundle/root dependency wiring. |
| `223f91e` | 5 | `uv run python scripts/validate_repo.py` passed with 589 tests. | Added audit JSON route metadata derived from the active explicit documentation audit route and covered it in CLI JSON tests. |
| `1519ccd` | 6 | `uv run python scripts/validate_repo.py` passed with 589 tests. | Documented the documentation-audit plugin family, route syntax, first-party packages, JSON metadata, and MkDocs navigation. |
| `b954264` | 7 | `uv run python scripts/validate_repo.py` passed with 589 tests. | Final branch-close validation after all implementation and documentation phases. |
| `e8571f3` | 8 | `uv run python scripts/validate_repo.py` passed with 589 tests. | Removed core documentation-audit registrations so package entry points load as first-party plugins; added persisted audit language, plugin, convention, rule, and severity provenance to SQLite, DuckDB, and memory-backed query rows. |

## Migration and Compatibility Notes

- Existing Python NumPy audit behavior moves behind explicit documentation audit configuration.
- Existing persisted audit rows must remain queryable only when they are still valid for the active audit route.
- Plugin and bundle version changes are required when first-party package boundaries or emitted audit artifacts change.
- Current analyzer scope does not require audit plugins for JSON, Markdown,
  text, or Bash. Future language analyzers with a real documentation convention
  should add their documentation audit plugin in the same rollout.

## Final Closure Checklist

- All selected documentation audit plugins discover through registry/capability surfaces.
- Explicit routing is covered by tests for multi-plugin same-language behavior.
- Audit JSON includes plugin provenance and routing information.
- SQLite, DuckDB, and memory-backed storage paths persist audit provenance and execute explicit route-filtered audit validation consistently.
- Documentation explains plugin authoring, configuration, routing, migration, and examples.
- `uv run python scripts/validate_repo.py` passes after the final change.
