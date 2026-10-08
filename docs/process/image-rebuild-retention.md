# Recipe-only benchmark image retention

The operator selected recipe-only preservation on 2026-10-07. Rebuilding may
change package resolution, binary contents and image digests. Reconstruction
records are aids for preparing a fresh environment, not exact historical image
backups. Original campaign profiles and digest bindings remain immutable.
The [completed existing-image cleanup](image-recipe-cleanup-2026-10-08.md)
records the preservation audit, exact removal scope and observed disk recovery.

## Default for new builds

`scripts/build_agent_efficiency_environment_image.py` preserves a generated
context before starting its controlled network-enabled build. The default root
is `.artifacts/agent-efficiency/image-rebuilds/`; each fresh tag selects a distinct
directory. `--rebuild-record` can select another fresh durable directory. Records
must not be stored in disposable scratch or committed to Git.

Each record contains:

- `context.tar.gz`: the exact generated pre-build source context, including
  fixture snapshots, product/plugin sources, helper scripts and supplied native
  binaries. It excludes container layers and generated dependency caches.
- `Containerfile`: the generated recipe, also present in the context archive.
- `record.json`: build options, runtime version, original parent/image identities,
  payload checksums, completion state, and explicit reconstruction limitations.
- `inventory.json`, after a successful build: installed Python/Debian package
  versions, tool versions, and npm lockfiles generated inside the image. It does
  not inspect host credentials, shell environments, or managed-login files.

Inventory collection runs with no network, a read-only filesystem, dropped
capabilities and no credential mounts. A failed build retains its context and
records failure. The usual build profile and stdout/stderr remain at their
original output locations. Failure to collect reconstruction metadata prevents
the builder from reporting a fully successful preparation.

## Reconstruction

From the repository root:

```bash
uv run python scripts/rebuild_agent_efficiency_environment_image.py \
--record .artifacts/agent-efficiency/image-rebuilds/<original-record> \
--tag localhost/codira-phase6-fixtures:<fresh-rebuild-tag>
```

The command verifies retained payload checksums and rejects reuse of the original
tag or an existing image tag. It restores inputs into disposable project scratch,
adds retained generated npm locks where the original context identifies their
fixture, and preserves a new recipe record before building. Successful output has
a new image identity and dependency inventory. Requalify that environment before
using it in a new campaign; never substitute its digest into an old campaign.

The parent must already be available locally because builds use `--pull=never`.
If a local parent was removed, reconstruct its recipe first and provide the new
digest through `--base-image <repository>@sha256:<digest>`. This explicitly changes
the new build's parent; the old record remains unchanged. Upstream downloads and
package repositories still need to be available. Recorded versions alone do not
preserve all package binaries or guarantee future installation.

Reconstructed images can retain archived environment-profile metadata inside
their filesystem. The new rebuild record documents reconstruction and parent
substitution; archived profiles are historical inputs, not fresh runtime
qualification. Prepare and qualify fresh campaign controls before measuring a
reconstructed environment.

## Existing images

```bash
uv run python scripts/preserve_agent_efficiency_image_recipes.py \
--output .artifacts/analysis/<fresh-image-retention-audit>
```

This audits all local image identities, then recovers recipes for named Codira
images and Codira leaves. It restricts source extraction to benchmark source and
binary paths in retained COPY snapshots. It excludes known dependency caches,
installed fixture environments, node modules and bytecode. It collects versions
and generated locks from the final image and preserves the original build history.
Completed per-image records are checksum-verified when resuming the same audit.
Shared COPY payloads are extracted once and retained with checksums. After
improving recovery tooling, `--repair-incomplete` writes separate replacement
records and retains the initial diagnostics.

Historical recipes are marked `historical-unverified` or `historical-incomplete`.
They are reconstructed from build history rather than an original context;
directory snapshots may include inherited non-cache files. Missing COPY snapshots
or unsupported instructions are recorded as gaps, never treated as proof of
rebuildability. The rebuild command refuses incomplete historical recipes. Some
complete historical recipes use recovered COPY inputs rather than the modern
fixture layout; recorded fixture bindings restore their final generated locks.
Do not claim a historical recipe is tested until its reconstruction and
runtime qualification have actually passed.

Neither preservation command deletes images. Before removal, review incomplete
recipes, active containers/external build containers, campaign references and
retention requirements. A deletion decision must explicitly accept any remaining
reconstruction gaps. Image-store usage includes shared layers, so individual image
sizes cannot be added to predict recovered disk space.

Keep generated records ignored and backed up. They live on the repository's
filesystem, which can differ from the Podman store's filesystem. Recipe-only
preservation reduces retained content; it does not move entire images to another
disk or preserve every intermediate build layer.
