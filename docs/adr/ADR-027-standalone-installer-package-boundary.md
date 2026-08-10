# ADR-027 — Standalone installer package boundary

**Date:** 09/08/2026
**Status:** Accepted

## Context

Codira has a narrow core and separately distributed first-party plugins. A
guided cross-platform setup experience requires Textual and package-management
orchestration, neither of which belongs in core or its MCP installation.

## Decision

`codira-installer` is a coordinated first-party distribution. It owns the
declarative installer engine, packaged official catalog, and Textual interface.
`codira-bundle-official` depends on the matching installer release. Core
exposes `codira setup` only as a guarded proxy to the installed provider; a
missing provider produces compatible installation guidance and never imports
Textual into core.

The canonical `packages/first_party_packages.json` manifest owns each official
distribution's name, local path, family, and configuration-schema factory. A
deterministic generator creates the installer catalog before packaging. Catalog
loading is data-only and never imports Textual or optional plugins.

## Consequences

Core-only installations remain minimal. Installer catalog drift is detected by
the generator's `--check` mode. The first-party release and split-rehearsal
inventory is derived from the same manifest, making coordinated additions
explicit. Configuration updates are previewed and validated before their
comment-preserving atomic replacement; an existing file receives a
byte-identical `.bak` recovery copy. Codex TOML and Claude/Cursor JSON MCP
entries are merged idempotently without replacing unrelated client settings.
