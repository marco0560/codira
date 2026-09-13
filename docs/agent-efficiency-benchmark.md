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

## Campaign workflow

All campaign state is outside Git. The runner creates a frozen state directory
from a public configuration JSON and deterministic schedule; its state-inspection
entry point performs no paid execution:

```bash
uv run python scripts/run_agent_efficiency_benchmark.py \
  --state-root /path/to/ignored-state \
  --campaign-id pilot-001 \
  --task-id symbols-001 \
  --task-id patch-001 \
  --repetitions 1 \
  --seed 7 \
  --configuration-json /path/to/configuration.json
```

Prepare host prerequisites with the Phase 0 helper. A future bounded Phase 6
runner records each completed attempt atomically and resumes only missing
attempts; it never overwrites immutable records. Evaluate and render a campaign
only through the dedicated reporting command using the same frozen identity:

```bash
uv run python scripts/report_agent_efficiency_benchmark.py \
  --state-root /path/to/ignored-state \
  --output-dir /path/to/public-report \
  --campaign-id pilot-001 \
  --task-id symbols-001 \
  --task-id patch-001 \
  --repetitions 1 \
  --seed 7 \
  --configuration-json /path/to/configuration.json
```

The command validates state, configuration fingerprints, record integrity, and
run-result contracts before writing `report.json` and `report.md`. Markdown is
derived only from canonical JSON. Per-attempt public records intentionally omit
raw JSONL, stderr, and transcript text; path-, URL-, or token-like failure
content is rendered as `redacted`. Pairs missing one variant or complete usage
are reported as exclusions and are not included in paired token statistics.
Elapsed-time statistics cover all recorded attempts, including attempts excluded
from token comparisons. Supply every task ID from the frozen campaign schedule
to both commands, in any order.

Do not create or run the campaign branch until the Phase 5 implementation is
reviewed and validated. The later pilot requires a separately approved bounded
manifest; neither state inspection nor reporting authorizes paid execution.
