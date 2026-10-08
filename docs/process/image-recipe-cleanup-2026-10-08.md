# Recipe-only image cleanup — 2026-10-08

## Approved policy and result

The operator selected policy B: retain reconstruction inputs and accept that a
rebuilt image may differ from the historical image. This replaces whole-image
cache retention for the audited Codira images. Historical campaign identities,
profiles and original image-digest bindings remain unchanged; a rebuild is not an
exact image backup and must not be substituted into an old campaign.

The completed cleanup removed 455 distinct Codira image IDs, including their
intermediate build snapshots, and retained the upstream Python base image. There
are 54 distinct image recipe records for 59 selected named/leaf inventory entries,
with no identified source-recovery gaps. Five entries are aliases of repeated IDs.
Historical rebuilds were not executed or qualified. Recipe completeness here
means that the supported history translation found no unresolved source bindings;
it does not prove that upstream packages will remain available or that every
recipe will build successfully in the future.

`/home` filesystem usage decreased by 217,366,450,176 bytes (about 202.4 GiB)
between the removal operation's before/after measurements. Usage is now 83%, with
327,514,034,176 bytes available (about 305 GiB; `df -h` displays 306G).
These are observed filesystem-accounting differences, including metadata and any
concurrent activity, rather than a sum of nominal image sizes.

## Durable evidence

The ignored receipt root is
`.artifacts/analysis/image-recipe-retention-20261007-r2/`. Its identity dates the
start of preservation; final repair and removal completed on 2026-10-08.

- `images.json` retains the original image metadata, names, digest references,
  labels and parent bindings. The inventory contains 461 rows; aliases can
  repeat image IDs, so this is not a count of distinct images.
- `summary.json` links all 59 named/leaf entries to their 54 distinct current
  original or replacement recipe directories. Replacement records remain under
  `repairs/`; initial diagnostics remain under `recipes/`.
- Each recipe retains its context archive, generated Containerfile, original
  build history, installed dependency/tool inventory and generated npm locks.
  Retained payloads are checked against their recorded SHA-256 digests.
- `copy-inputs/` retains shared source/binary payloads and their checksums.
  Known dependency caches, fixture environments, node modules and bytecode were
  excluded. Native inputs preserve the two Codex binaries and, where supplied
  historically, bwrap; inherited npm links are not treated as native inputs.
- `removal-plan.json` records the 455 exact selected IDs, upstream image to keep,
  recipe-record fingerprints and source-record verification.
- `removal-before.json`, `removals.jsonl` and `removal-verification.json` retain
  the initial filesystem measurement, removal events and final verification.
- `remove-preserved-images.py` retains the audit-local guarded operation. It
  verifies records, rejects containers/new image identities or tags, follows
  the approved ancestry order and never uses force or a broad prune.

Podman refused one batch because an image had multiple names, including a digest
alias. The failure receipt was retained. The operation resumed after removing
only the recorded names of selected images with `podman untag`; deletion then
used exact IDs with `--no-prune`. Final verification found none of the selected
IDs remaining and exactly one upstream image left.

The completed audit, source records and repair diagnostics occupy about 3.4 GiB
on the repository NVMe filesystem. The initial interrupted diagnostic pass is
also retained under `.artifacts/analysis/image-recipe-retention-20261007-r1/`
(about 406 MiB). Keep these ignored reconstruction records backed up; Git tracks
the tooling and this summary, not the raw evidence.

## New default and validation

The benchmark fixture-image builder now retains a source context and recipe
before network-enabled building, then captures dependency inventories and
generated npm locks after a successful build. The default destination is
`.artifacts/agent-efficiency/image-rebuilds/<build-identity>/`. See
[recipe-only image retention](image-rebuild-retention.md) for reconstruction,
parent-image requirements and historical recovery limitations. Direct manual
Podman builds do not gain automatic capture by calling Podman alone.

Focused tests passed 11 cases covering successful and failed build retention,
record overwrite/tampering rejection, safe extraction, generated lock replay,
fresh image identities, historical COPY recovery and two/three-binary native
contexts. The final repository gate completed with 1,405 tests passed, three
skipped, 86% coverage and all required checks successful. Completed gate sessions
and their transient log/exit files are removed after examination and reporting,
as required by `AGENTS.md`; raw image-retention receipts remain durable.
