# Artifact retention cleanup — 2026-10-07

## Authorized scope

The operator approved package inventories, inspection for unique output or local
modifications, and deletion of the archived `.venv` trees under `.artifacts/`
and `benchmarks/`. The working repository environment is outside this scope.
Responses, patches, logs, results and frozen source evidence must be preserved.
This approval revises the earlier decision to retain entire installed environments.

## Inventory and preservation method

The audit receipts are under
`.artifacts/analysis/environment-retention-20261007-r1/` and remain ignored.
They contain exact local paths and installed metadata, so only this sanitized
summary and authored reports belong in Git.

- `environments.json` identifies the 171 selected environments.
- Each numbered `environments/<number>/inventory.json` records installed names,
  versions, installation locations, direct URL/editable metadata where present,
  and the Python environment configuration. Additional real `lib64` installations
  are inventoried separately in the same inventory.
- `file-audit.jsonl.gz` records the classification and file identity used for
  each environment. Installed files are checked against their distribution
  `RECORD` hashes. This checks installed-record consistency, not independent
  upstream wheel authenticity.
- Installation metadata, bootstrap files and any modified, unowned or otherwise
  unverifiable files are retained in `retained-files.tar.gz`. Each retained
  regular file is verified against its original SHA-256 after archiving.
  Recognized bytecode beside retained source is regenerable and excluded.
- Host process checks must be clear after the audit, and every environment's
  complete file listing must still match the audited listing before deletion.
- `protected-before.jsonl.gz` and `protected-after.jsonl.gz` compare all files
  outside `.venv` in both audited trees, excluding this new receipt directory.
  Regular-file hashes, symlink targets and special-file types are checked.
- `deletions.jsonl`, `verification.json` and the before/after disk-usage records
  establish the actual cleanup result. Inventories are reconstruction aids;
  they do not preserve every binary or guarantee an identical future install.

## Authored report preservation

[The report archive](benchmark-history/index.md) contains 29 authored reports:
28 historical backend, embedding, retrieval and vector-store analyses, plus the
Campaign 016 failure analysis. Original ignored reports remain unchanged; each
tracked copy records its original digest. Fifty-two report-level substitutions
repair 21 distinct known directory moves. Machine-local source hyperlinks are
replaced with historical source identifiers rather than misleading live links.

Twenty-one reports still refer to unavailable original evidence. Across the
archive there are 44 distinct unavailable literal paths and 13 unavailable
patterns. These are explicitly marked as historical and unverified, not silently
mapped to a different run. Restore the exact run identities from an external
backup before revalidating those measurements. Historical recommendations are
not current operating instructions.

## Remaining benchmark-input gap

All 16 inspected repository manifests contain at least one missing local source
path. The tracked retrieval-quality manifest has 13 missing paths out of 16.
These inputs were left intact because substituting a different repository or
revision would change experiment controls. Repair requires a verified mapping
to the intended source/revision; absent repositories need restoration.

| Manifest | Missing repository paths | Total repository paths |
| --- | ---: | ---: |
| `benchmarks/embedding/uv-backed-repos.local.json` | 1 | 4 |
| `benchmarks/performance/benchmarks.local.json` | 12 | 14 |
| `benchmarks/performance/bk-cpp.local.json` | 16 | 19 |
| `benchmarks/performance/bk-llvm.local.json` | 1 | 1 |
| `benchmarks/performance/bk-new.local.json` | 12 | 14 |
| `benchmarks/performance/generated-complete.local.json` | 18 | 21 |
| `benchmarks/performance/generated-huge.local.json` | 5 | 5 |
| `benchmarks/performance/generated-large.local.json` | 3 | 3 |
| `benchmarks/performance/generated-medium.local.json` | 5 | 8 |
| `benchmarks/performance/generated-small-medium-large.local.json` | 13 | 16 |
| `benchmarks/performance/generated-small-medium.local.json` | 10 | 13 |
| `benchmarks/performance/generated-small.local.json` | 5 | 5 |
| `benchmarks/performance/short_benchmark.local.json` | 2 | 3 |
| `benchmarks/performance/short_bk-new.local.json` | 2 | 3 |
| `benchmarks/retrieval-quality/repos.local.json` | 13 | 16 |
| `benchmarks/semantic-pipeline/frozen-repos.local.json` | 6 | 6 |

Historical generated campaign receipts retain their original path values.
Blinded packets, provider bodies, measurement traces and generated reports remain
ignored; tracked authored findings do not replace their raw evidence. Small
unreferenced graphs and completed gate files remain a separate cleanup review.

## Completion evidence

The audit completed and all 171 selected environments were removed. An exhaustive
post-cleanup search found zero `.venv` trees in either requested directory.
The package inventories reduce to three distinct sets: 67 environments with
73 packages, 79 with 206 packages, and 25 initialized environments with none.

All 2,999,443 checked package files matched their installed `RECORD` hashes,
including the additional real `lib64` installation; no recorded files were
missing. Bootstrap, installation metadata and unrecognized files were preserved
in verified archives. No modified installed package files were found.

The before/after comparison matched all 839,102 protected entries outside the
removed environments. This comparison completed before the intentional update
to `.artifacts/MANIFEST.md` recording this retention decision; frozen campaign
and source evidence was not rewritten.

Filesystem usage fell from approximately 654.9 GiB to 25.1 GiB under
`.artifacts/`, a reduction of about 629.8 GiB by `du`. These are filesystem
accounting measurements rather than a promise about unique physical extents.
About 22 GiB remains in agent-efficiency records and 3 GiB in benchmark evidence;
those retained identities require their own review before any further removal.

The inventories, integrity receipts, retained-file archives and preservation
comparison are retained under the ignored receipt identity above. The
`receipt-manifest.json` binds those files by SHA-256
(`bd72fefb5076623449b320267887fe0f56db58867fae74cc41acce608983dfe9`). The authored report archive
and this sanitized cleanup summary are Git-tracked; raw metadata remains ignored.
