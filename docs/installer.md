# Installer

`codira-installer` is the optional, first-party setup interface for Codira. It
keeps Textual and package-management orchestration out of the core `codira`
distribution. Install it directly for guided setup, or install
`codira-bundle-official` to include it with the official plugin set.

```bash
python -m pip install codira-installer
# or
python -m pip install codira-bundle-official
```

From a Codira checkout, `uv run codira setup` delegates to the same provider.
It gives a clear remediation when the installer distribution is not installed.

## Guided setup

Run `codira-installer` with no action flag to open the Textual flow. The
workflow records choices before it enables **Apply**:

1. package source;
2. current, existing, or new environment;
3. repository scope and official profile/features;
4. configuration, model, MCP, and service review stages;
5. a validated plan review, worker progress, and resumable result.

The installer never elevates privileges, installs Python or `uv`, removes
deselected packages, or accepts arbitrary third-party plugins. Cancellation is
cooperative between commands, so an atomic journal or configuration
replacement is never interrupted midway.

## Targets and sources

The source and target choices cover the four normal situations:

| Situation | Source and target |
| --- | --- |
| Install in this checkout's environment | `--source local-checkout --target current` |
| Create a new environment | `--target new --environment /path/to/.venv` |
| Install into another repository's environment | `--target existing --environment /path/to/other/.venv` |
| Reconfigure an existing Codira environment | `--target existing --environment /path/to/.venv` |

`uv` is required for new environments and local-checkout installation. `pip`
is accepted only for coordinated PyPI installation into an existing or current
environment; it cannot create environments or install from a checkout.

For local checkout plans, the checkout defaults to the working directory:

```bash
codira-installer --source local-checkout --target existing \
  --environment /work/other-repository/.venv --plan local-plan.json
```

This embeds only the explicit checkout and target paths in the plan. A PyPI
plan does not inherit a local path.

## Automation and recovery

The TUI and automation use the same typed request and plan resolver. Export a
reviewable JSON plan, then apply or resume it explicitly:

```bash
codira-installer --target new --environment /work/codira/.venv \
  --profile recommended --plan codira-plan.json
codira-installer --apply codira-plan.json --journal .codira-installer-journal.json
codira-installer --resume codira-plan.json --journal .codira-installer-journal.json
```

Plans contain command argument vectors rather than shell strings and a stable
fingerprint. The journal contains only completed identifiers and safe result
text; it contains no credentials or environment dump. A fingerprint mismatch
is rejected rather than resumed.

## Profiles and optional operations

Profiles select only the generated official catalog:

- `core-only` installs only `codira`.
- `recommended` selects the Python analyzer and SQLite backend.
- `full-official` selects every official extension.
- `--package` supplies a granular, catalog-validated override.

The review flow keeps configuration, model provisioning, MCP integration, and
daemon actions visible. Configuration preview/replacement is comment
preserving, validated, backed up, and atomic. Codex TOML and Claude/Cursor JSON
MCP merges are idempotent and preserve unrelated entries; see [Local
MCP](mcp.md). Model provisioning is target-environment scoped. Hardware
recommendations and calibration changes are reviewable, and calibration needs a
second confirmation. Indexing and query-daemon operations are repository
scoped, never use `sudo`, and report remediation rather than failing unrelated
installation work.

## Release and contributor checks

The repository runs the installer artifact rehearsal on Linux, macOS, and
Windows CI. It creates a temporary environment, installs local installer and
official-bundle wheels with no package index, and exports all four plan forms.
Run the same gate locally before coordinated publishing:

```bash
uv run python scripts/rehearse_installer_installs.py \
  --wheel-dir /tmp/codira-installer-wheels \
  --venv-dir /tmp/codira-installer-venv \
  --plan-dir /tmp/codira-installer-plans
```

For the complete coordinated package build and metadata check, follow the
[release checklist](release/checklist.md). Contributors changing the catalog
must also run:

```bash
uv run python scripts/generate_installer_catalog.py --check
uv run pytest -q packages/codira-installer/tests
```
