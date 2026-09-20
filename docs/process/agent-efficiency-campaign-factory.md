# Agent-efficiency campaign factory

Create every paid agent-efficiency experiment from a versioned JSON
specification. The factory is credential-free and cannot execute a model or
start tmux. It resolves current frozen task and fixture fingerprints, enforces
stage cardinality and accounting, and writes immutable artifacts.

```bash
uv run python scripts/generate_agent_efficiency_campaign.py \
  --spec benchmarks/agent-efficiency/campaign-specs/calibration-template.json \
  --output-dir /tmp/codira-calibration-001
```

The output directory must not exist. The factory writes:

- `campaign.json`: the immutable execution manifest;
- `launch-plan.json`: stage, fingerprints, deterministic schedule, and the
  required non-executing/paid-stage gates.

Stages are intentionally constrained:

- `calibration`: exactly one task and one Codira-MCP request;
- `pilot`: exactly three tasks, a required deterministic `seed`, and six
  paired baseline/Codira-MCP requests.

After generation, perform offline validation and the full tmux repository gate,
then authenticated route/key admission. A distinct explicit authorization is
required before any paid execution. Never edit a generated manifest, reuse its
output directory, or assemble a replacement launch command by hand.
