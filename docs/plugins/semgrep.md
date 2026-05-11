# Semgrep Guidance

This page documents how plugin authors can reuse the Codira Semgrep guardrail
approach in their own repositories.

## What Codira Enforces Internally

The repository-owned rules live under:

- `semgrep/rules/architecture.yml`
- `semgrep/rules/plugins.yml`
- `semgrep/rules/determinism.yml`

These rules are written for the Codira monorepo layout and currently assume
paths such as:

- `packages/codira-analyzer-*/src/`
- `packages/codira-backend-*/src/`
- `src/codira/`

Do not copy the rules unchanged unless your repository uses the same package
layout and architectural boundaries.

## Reusable Plugin Ideas

Third-party plugin repositories can reuse the same guardrail style for rules
such as:

- forbid direct `sqlite3` imports in analyzer packages
- forbid analyzer imports of backend packages
- forbid analyzer imports of `codira.storage`
- require analyzer classes to expose `analyzer_capability_declaration`
- forbid broad `except Exception` in plugin implementation code

When you copy these ideas into a plugin repository, update:

- `paths.include`
- `paths.exclude`
- allowlist entries
- rule messages that reference Codira-specific docs

## Codira-Specific Allowlists

Two current Codira rules intentionally carry internal allowlists:

- `codira.arch.no-sqlite3-outside-allowed-layers`
- `codira.arch.no-backend-package-import-outside-allowed-layers`

Those allowlists reflect current Codira implementation debt recorded in:

- `docs/process/semgrep-architecture-guardrails.md`

Third-party plugin repositories should define their own exception inventory
instead of inheriting the Codira allowlist unchanged.

## Local Invocation

Run the Codira-owned rules from the repository root with:

```bash
uv run python scripts/run_repo_tool.py semgrep scan --config semgrep/rules --metrics=off --disable-version-check .
```

## Recommendation for Plugin Authors

If you adopt Semgrep in a plugin repository:

1. start with one or two low-noise rules
2. document every exception explicitly
3. fail CI only after current violations are either fixed or allowlisted
4. keep rule IDs stable so future violations are easy to track
