# Agent-efficiency benchmark methodology

## Deterministic oracle example

Each agent writes `.benchmark/result.json`; the protected grader evaluates the
public oracle outside the agent container. This example is exercised by
`tests/test_agent_efficiency_oracles.py`.

```json
{
  "all_of": [
    {"contains_symbols": [{"qualified_name": "codira.mcp.context_for_task"}]},
    {"contains_paths": ["src/codira/mcp/adapter.py"]},
    {"normalized_artifact": {"summary": "deterministic output"}}
  ]
}
```

Patch oracles copy the protected fixture to a new temporary directory, reject
untrusted patch headers that can escape that copy, require `git apply --check`,
apply the candidate patch, and run an independent, argument-vector test
command. Custom evaluators are available only when the protected grader
registers both the callable and its reviewed script identity, and the
specification declares a non-empty rationale, `no_llm: true`, and
`variant_identity_access: false`. The definition's script path and SHA-256
must match that protected registry binding before the callable runs.

Run the executable example checks with:

```bash
uv run pytest -q tests/test_agent_efficiency_oracles.py
```
