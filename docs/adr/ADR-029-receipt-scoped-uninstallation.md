# ADR-029 — Receipt-scoped uninstallation

**Date:** 15/08/2026
**Status:** Accepted

## Context

Codira's standalone host-runtime model separates the executable runtime from
the repositories it analyzes. An installation can create a managed runtime,
deterministic launchers, service registrations, and workspace descriptors. It
can also reuse pre-existing environments, target repositories, configuration,
index state, and shared model artifacts.

Those resources do not have one common owner. Treating uninstall as the
automatic inverse of install would make it possible to delete user-owned or
shared data merely because it was selected during setup. This would contradict
the non-destructive migration and workspace contracts in ADR-028.

The current command surface already has deliberately narrow cleanup actions:

- `codira daemon uninstall` removes a Codira-managed service registration.
- `codira workspace remove NAME` unregisters a workspace descriptor and
  retains the repository, configuration, state, and models.
- `codira emb purge` removes selected vector-store data only after an explicit
  destructive confirmation.

The installer writes a receipt for its managed standalone runtime, but it does
not yet expose a general installer uninstall operation.

## Decision

Codira will not add a blanket `codira uninstall` command as an unconditional
inverse of `install`.

If managed runtime removal becomes a supported user need, it must be provided
by `codira-installer` as a receipt-scoped operation with the following
contract:

- It may remove only a managed runtime whose receipt proves it was created by
  the installer.
- It may remove deterministic launchers and service registrations that the
  same installation owns.
- It must present a dry-run/preview of every deletion and require explicit
  confirmation before execution.
- It must reject missing, malformed, or mismatched receipts rather than infer
  ownership from a path or environment name.
- It must not remove target repositories, user configuration, workspace state,
  shared models, or pre-existing environments by default.
- Any optional removal of installer-owned data beyond the runtime must be
  separately selected, previewed, and confirmed.

Existing narrow commands retain their current ownership boundaries. Workspace
removal remains unregister-only, and model/vector cleanup remains a separate,
explicit maintenance action.

## Consequences

### Positive

- Users can eventually remove an installer-created host runtime without risking
  an analyzed repository or shared data.
- The receipt becomes an auditable ownership proof instead of merely update and
  repair metadata.
- Destructive operations have deterministic scope, preview, and recovery
  expectations.

### Negative

- A runtime without a valid receipt cannot be automatically removed by Codira;
  the user must remove it with the environment manager that owns it.
- A future uninstall implementation needs explicit ownership and service
  inventory handling rather than reusing the install plan in reverse.

### Neutral / trade-offs

- This ADR does not require implementation of an uninstall command now.
- Repository-local installation remains an Advanced compatibility mode and is
  not presumed to be installer-owned.
- This ADR complements ADR-027's installer package boundary and ADR-028's
  host-target runtime separation.
