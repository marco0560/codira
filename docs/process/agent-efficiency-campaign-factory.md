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

Accounting declares the meaning of `budgets.max_total_tokens` through the
optional `accounting.max_total_tokens_scope`. Fresh multi-continuation pilots
use `whole-session`, so the ceiling is reserved once per execution; historical
manifests without the field retain the conservative `per-continuation`
reservation. Logical continuation and transport-retry caps remain independent
operational limits and do not multiply a declared whole-session token ceiling.

Fresh campaign specifications may declare `treatment_protocol.agent_instruction`
for a directive applied identically to baseline and assisted prompts. Protocol
`mcp-required-v2` requires that common directive in addition to the
assisted-only `codira_mcp_instruction`. Use the common field for controls such
as exact identifier case, history-free fixture semantics, offline dependency
policy, edit completion, and focused validation; never put a task advantage in
only one arm.

After generation, perform offline validation and the full tmux repository gate,
then authenticated route/key admission. A distinct explicit authorization is
required before any paid execution. Never edit a generated manifest, reuse its
output directory, or assemble a replacement launch command by hand.

For a paired pilot, prepare and then launch the factory artifacts through the
deterministic executor. The supplied seed is accepted only when it reproduces
the immutable six-attempt schedule, and every fixture source is re-admitted
both when the receipt is created and immediately before tmux starts:

```bash
uv run python scripts/launch_agent_efficiency_pilot.py \
  --prepare \
  --campaign-dir .artifacts/agent-efficiency/<campaign-id> \
  --execution-root .artifacts/agent-efficiency/<campaign-id>-execution \
  --seed <factory-seed> \
  --fixture-source click-public=/absolute/path/to/click \
  --fixture-source picomatch-public=/absolute/path/to/picomatch \
  --fixture-source codira-public=/absolute/path/to/codira

uv run python scripts/launch_agent_efficiency_pilot.py \
  --launch \
  --campaign-dir .artifacts/agent-efficiency/<campaign-id> \
  --execution-root .artifacts/agent-efficiency/<campaign-id>-execution \
  --seed <factory-seed> \
  --fixture-source click-public=/absolute/path/to/click \
  --fixture-source picomatch-public=/absolute/path/to/picomatch \
  --fixture-source codira-public=/absolute/path/to/codira
```

The exported agent fixture deliberately has no commit or remote, but its
immutable archive baseline is staged in the synthetic Git index. This permits
ordinary `git diff` capture without exposing history. Runtime admission must be
performed against that exact representation. Before any provider setup, an
assisted attempt must prove a positive staged path count, a positive and
plausible indexed path count, a ready non-partial generation, and zero failed
files. A zero-file index is an infrastructure failure, even when the index
process exits successfully.

The provider proxy persists each exact upstream response body to the ignored
attempt artifact directory before parsing or forwarding it. Public-safe
observations bind those bodies by digest and byte count. Routing disables
fallbacks and requires support for requested parameters so the frozen model
and reasoning controls cannot be silently substituted or dropped.
