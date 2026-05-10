# Codira Semgrep Guardrails

This directory contains Codira-owned Semgrep configuration for architecture,
plugin contract, and deterministic design guardrails.

Semgrep rules are introduced incrementally to avoid noisy CI failures
and to keep architectural exceptions explicit.

Current rule categories:

- architecture
- plugins
- determinism

The initial rule set intentionally targets only low-noise,
high-confidence architectural violations.

## Local invocation

```sh
uv run python scripts/run_repo_tool.py semgrep scan --config semgrep/rules --metrics=off --disable-version-check .
```

## Validation

The standard repository validation entry point runs Semgrep through the
repository tool wrapper:

```sh
uv run python scripts/validate_repo.py
```
