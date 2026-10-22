# Analyzer backlog and release-readiness workflow

## Objective and separate completion criteria

The full remediation objective remains unchanged: retain all 25,762 immutable
original identities; separate source-proven malformed inputs and unsupported
future syntax by language, source-owned language version and repository; fix
and independently qualify every remaining original. Keep all raw and failed
evidence. A candidate release does not complete that objective.

On 22 October the operator approved a faster execution strategy: maintain an
overlapping blocker census, rank work by whole-file closure potential, reuse
native evidence, automate qualification, and measure representative groups before
large qualification runs. Release readiness is assessed separately from clearing
the stress corpus. No publication, push, merge or main-branch modification is
authorized by this workflow.

## Audited starting point

Classification v68, bound to source commit
`1008e27b6698fd3bacf2d9f9b2cad212063555c3`, contains:

| View | Original problem files | Verified fixed | Separated | Open |
| --- | ---: | ---: | ---: | ---: |
| Full immutable set | 25,762 | 4,633 | 680 | 20,449 |
| LLVM repository | 22,692 | 3,868 | 603 | 18,221 |
| Other repositories | 3,070 | 765 | 77 | 2,228 |

These are originally failing benchmark identities, not a failure rate over all
source files in those repositories. The remaining non-LLVM files are C (1,867)
and C++ (361). Repository labels do not identify file languages: the CPython and
VictoriaMetrics remainder is C/C++ source.

| Non-LLVM repository | Open files |
| --- | ---: |
| PostgreSQL | 957 |
| CPython | 670 |
| Redis | 343 |
| Catch2 | 155 |
| zlib | 59 |
| fmt | 39 |
| VictoriaMetrics | 4 |
| inih | 1 |

The first three repositories account for 1,970 of the 2,228 files. The LLVM view
remains queryable and fully in scope; excluding it from a measurement does not
classify its fixtures, dismiss its findings, or remove release-relevant defects.

Evidence is retained under
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `classification-v68.jsonl` and `classification-summary-v68.json`;
- `parallel-remediation-20261022-r1/groups/cpp-record-declaration-context/admission-audit-v68-r1.json`;
- the same group's `qualification-source-binding-native11-r1.json`, native
  captures, native corruption controls, actual CLI runs, and storage controls.

The latest 11 admissions passed full native metadata comparisons, 76 product
corruption controls, eight native-evidence corruption controls, and 20 isolated
database corruption controls. Actual SQLite and DuckDB runs each indexed all
11 files without failures; complete actual-profile DTOs equal the native-graded
DTOs. The source commit passed the full repository gate: 2,984 tests passed,
three skipped, 88% coverage, 931 fresh indexed files and zero index failures.
The independent admission audit checked all original identities and source
hashes, 25,751 unchanged other rows, and all 680 unchanged separated inputs.

## Evidence vocabulary and accounting

One original may have multiple blockers. Preserve the following distinctions:

- A diagnostic is an observation. Repeated diagnostic text is not proof of a
  shared root cause.
- A syntax-pattern candidate is a selection hint. Its size is not a projected
  fix count.
- A confirmed cause requires independent source/native evidence and a focused
  counterexample demonstrating the faulty layer.
- A native reference limitation is distinct from an analyzer defect.
- Parser readiness, native metadata qualification, persistence qualification
  and ledger admission are separate states.

For example, the record family had 665 syntax candidates, 40 originals with
63 native-confirmed record-range defects, and 11 eventual whole-file admissions.
The paired producers each had 137 parser-ready originals. The other confirmed
field corrections remain useful, but their originals stay open when another
blocker remains. Earlier two-hour throughput is not a reliable completion ETA.

## Reusable inventory and overlapping catalog

`scripts/analyzer_backlog_inventory.py` captures the public C/C++ analyzer DTO,
source hash, exact options, configuration fingerprint and dependency-sensitive
input fingerprint for each original/profile pair. It compares defaults with
explicit repository profiles, retains unique attempt artifacts and failures,
checkpoints each completed case, and resumes only unchanged inputs. Installed
analyzers must come from the inspected checkout. Changed producer, source,
header, profile or driver inputs require a new run identity.

`scripts/analyzer_backlog_catalog.py` joins those results with reusable native
and storage observations. It preserves overlapping blockers, exact profile
boundaries, historical producer evidence, incomplete stages, and language-mode
and repository labels. A sole *known* blocker is not a closure prediction.
Current parser, native and storage coverage must be explicit before a confirmed
product blocker becomes a fully observed closure candidate. Even that is a
candidate until the fix and all qualification stages pass.

Working directory: the dedicated repository worktree. Prerequisites: its
synchronized `uv` environment and immutable ledger/profile files. Replace the
uppercase path arguments below with absolute paths; each output is a fresh,
durable directory under `.artifacts/analysis/`.

```bash
uv run python -m scripts.analyzer_backlog_inventory \
  --ledger LEDGER_JSONL \
  --profiles PROFILE_MAP_JSON \
  --exclude-repository cpp-llvm-project \
  --output NEW_INVENTORY_DIR \
  --workers 4

uv run python -m scripts.analyzer_backlog_catalog \
  --ledger LEDGER_JSONL \
  --inventory INVENTORY_DIR \
  --observations NATIVE_OBSERVATIONS_JSON \
  --output NEW_CATALOG_DIR \
  --samples 5
```

Expected inventory outputs are `inputs.json`, append-only `results.jsonl`,
per-attempt DTOs/failures, `checkpoint.json` and a terminal `summary.json`.
Every summary reports zero qualification admissions. Retain stdout, stderr and
process exit beside the run. Resume an interrupted inventory with the identical
command and output identity; completed source/header fingerprints and DTO hashes
are reverified before skipping cases. After any input drift, preserve the old
run and use a new identity. Do not edit results or reuse failed-attempt paths.

Expected catalog outputs are input digests, normalized `facts.jsonl` and
`report.json`. Reports are fresh derived snapshots; never overwrite one as the
underlying inventory advances. Groups contain deterministic representatives
across repository/language-mode strata and explicit unknown stages. Conflicting
current snapshots require reconciliation rather than silently choosing a winner.

Native/storage observation envelopes use format
`analyzer-blocker-observations-v1`. They contain input artifact digests,
`producer_source_hashes`, and `observations`. Each observation supplies an
original `path`/`source_sha256`, exact `configuration`, `stage`, boolean
`complete`, and `blockers` with an `id`, `kind` and `confidence`. Stages are
`parser`, `native`, `storage` or `root_proof`; kinds are `product`, `reference`,
`environment` or `diagnostic`; confidence is `confirmed`, `observed` or
`candidate`. Native adapters must retain compiler/profile/dependency identities
and raw captures. They must not treat missing evidence as a passing stage or
infer profile equivalence without a separately verified binding.

The first inventory targets all 2,228 non-LLVM open identities under defaults
and explicit source-contained profiles: 4,446 producer cases. Its immutable
identity is
`parallel-remediation-20261022-r1/strategy-remediation-20261022-r1/non-llvm-inventory-r1`.
This is a current baseline capture, not a native-qualification run. It already
retains an opt-in C token-budget exception for focused diagnosis; no open file
is admitted from that observation.

## Release-readiness assessment

Use the existing [release checklist](../release/checklist.md) and
[release process](../release/process.md). Those controls require repository
validation, coordinated package metadata, wheel/sdist checks and installed
artifact rehearsals. They do not require every LLVM compiler fixture to parse.

The next assessment must add a reproducible analyzer sentinel manifest drawn
from ordinary supported repositories and the existing qualified corpus. For
each sentinel retain its language mode, repository/profile, source identity,
full native metadata and actual two-backend proof. Include adverse controls
showing that unsupported or incomplete analysis is exposed accurately.

Prioritize defects by their impact on the documented user contract: exceptions,
silent omissions or misattribution, incorrect complete-status claims, persistence
loss and regressions in qualified ordinary inputs. Keep explicit partial-analysis
limitations and unsupported stress syntax visible in the release record. Known
native-oracle limitations block benchmark admission; they are not automatically
product defects or an assertion that publication is safe.

The release decision needs the completed sentinel results, current full gate,
installed-artifact rehearsal and a reviewable residual-risk matrix. The current
backlog counts alone establish neither readiness nor a publication deadline.
Once those artifacts exist, the operator can approve the concrete candidate;
full remediation and its immutable ledger continue afterwards.
