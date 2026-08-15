# ADR-028 — Host-target runtime decoupling

**Date:** 13/08/2026
**Status:** Accepted

## Context

ADR-017 correctly established the Python version needed to execute Codira, but
its wording could be read as a restriction on the Python repositories Codira
analyzes. Those are independent concerns. Codira is normally an external tool:
it reads a target repository and must not require that repository's environment
to execute it.

The original Slice 1 baseline recorded host-parser behavior before the parser
migration. The completed implementation now keeps Python parsing in the
first-party analyzer's Tree-sitter layer and publishes target compatibility as
a fixture-backed contract rather than inferring it from the host interpreter.

## Decision

Codira will keep a separate host-runtime contract and target-source
compatibility contract.

- The host runtime is the Python interpreter that executes Codira and its
  plugins. ADR-017 continues to set its current minimum at Python 3.13.
- A target repository is analyzed as filesystem content. Ordinary analysis
  must not import or execute target repository code or depend on its virtual
  environment.
- Target Python compatibility is declared independently from host support by
  the first-party Tree-sitter analyzer and its tested compatibility matrix.
- Named workspaces, a shared per-user model store, and workspace-scoped MCP
  and services are implemented alongside retained direct-path routing.

The complete ordered work and acceptance criteria live in the
[host-target runtime decoupling execution ledger](../process/host-target-runtime-decoupling-execution-ledger.md).
ADR-028 supersedes the host/target interpretation of ADR-017, while retaining
ADR-017 as the host-runtime policy.

## Consequences

### Positive

- Release documentation can state host and target compatibility without
  conflating them.
- Parser migration has frozen artifact behavior and a shrinking host-AST
  inventory as explicit safety rails.
- Future workspace and model-store work can evolve without making target
  environments execution dependencies.

### Negative

- Target-Python support is restricted to the published, fixture-backed matrix;
  a host runtime's ability to parse a file is not a compatibility claim.

### Neutral / trade-offs

- This ADR does not add a public Python API stability promise.
- Repository-local installation remains an advanced compatibility mode; it is
  not the recommended deployment model for target repositories.
