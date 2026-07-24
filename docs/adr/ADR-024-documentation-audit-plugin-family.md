# ADR-024: Documentation Audit Plugin Family

## Status

Accepted

## Context

Codira currently audits Python docstrings with NumPy-style rules in core code.
Issue #4 extends this into a convention-aware documentation audit surface that
must support more than one convention for a language without overloading
language analyzers.

Language analyzers remain responsible for source parsing and artifact
extraction. Documentation audit plugins validate documentation artifacts already
emitted by analyzers.

## Decision

Add a separate `documentation-audit` plugin family.

Documentation audit plugins declare:

- stable plugin name and version
- supported analyzer languages
- supported documentation conventions
- an `audit_documentation` method that receives a normalized documentation
  artifact and returns structured diagnostics

The core runtime selects plugins through explicit ordered routes in
`plugins.documentation_audit_routes`. A route binds a language, convention,
plugin name, and optional include/exclude path globs.

When more than one documentation audit plugin can apply to the same language,
the route list is the authority. Unmatched or ambiguous routing is a
configuration problem, not a silent fallback.

## Consequences

- Analyzer plugins do not need convention-specific validation logic.
- Audit diagnostics can carry plugin name, plugin version, convention, and
  severity provenance.
- Existing NumPy docstring validation can move into a first-party
  documentation-audit plugin while retaining deterministic behavior.
- Operators must opt in through explicit routing before documentation audit
  execution.
