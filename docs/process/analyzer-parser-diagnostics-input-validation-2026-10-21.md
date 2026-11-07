# Reuse content validation during worker input checks

The full 25,762-original remediation remains active. Classification v61 remains
unchanged at 4,496 verified fixes, 680 separated inputs and 20,586 open files.
The current 278-file statement family has 147 fixed and 131 open originals.

## Measured shared cost

Live stacks from actual native-qualified SDK CLI indexing show workers rebuilding
complete include graphs during input verification. Planning and source analysis
already capture these graphs. On two unchanged actual SDK inputs, recomputation
took 4.37 and 4.62 seconds; the existing content validator took 1.08 and 1.21
seconds and established matches to the exact captured identities. These are
limited measurements, not a promised end-to-end speedup.

Worker verification now uses the existing analyzer-owned content validator
through the coordinator. Source hashes are still checked. The before/after
analysis checks remain in place, and the coordinator recomputes the complete
identity if validation is unavailable or does not establish a match. No timestamp
cache, new analyzer schema, compiler invocation or dependency-read bypass is
introduced. Other analyzers retain the existing recomputation fallback.

## Validation and evidence

Real SQLite and DuckDB tests reject same-length, same-timestamp source and header
edits after parsing, and reject a previously missing header appearing during
analysis. Serial and thread indexing verify unchanged inputs without repeating
successful planning captures. Existing process-worker, include invalidation,
reader freshness, source-only and persisted-identity checks remain exercised.
The focused input/storage/concurrency suite passed 40 tests. Final full-gate and
actual-original CLI evidence are retained separately; no new file admissions
follow from this performance change alone.

Evidence under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `cpp32-input-verification-measurement-r1/`
- `cpp32-cli-r2-stacks-r1/`
- `cpp-input-validation-reuse-integration-r1/`

The full gate uses
`.artifacts/validation/repo-gates/cpp-input-validation-reuse-r1.*`.
