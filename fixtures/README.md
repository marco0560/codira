# Semgrep Rule Fixtures

This directory contains intentionally violating fixtures used to validate
Codira Semgrep guardrails.

These files are not production code.

Each fixture should:

- trigger exactly the intended rule
- remain minimal and deterministic
- avoid overlapping violations where possible

Fixture categories:

- architecture
- plugins
- determinism
