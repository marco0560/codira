# Agent-efficiency campaign factory

Create every paid agent-efficiency experiment from a versioned JSON
specification. The factory is credential-free and cannot execute a model or
start tmux. It resolves current frozen task and fixture fingerprints, enforces
stage cardinality and accounting, and writes immutable artifacts.

```bash
uv run python scripts/generate_agent_efficiency_campaign.py \
  --spec benchmarks/agent-efficiency/campaign-specs/calibration-template.json \
  --output-dir .artifacts/agent-efficiency/campaigns/codira-calibration-001
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

## Stable harness and experiment variables

Treat the campaign factory, fixture export and admission, prepared image,
offline environment directive, container isolation, provider proxy, Codira
index admission, result/oracle evaluation, paired schedule, and evidence format
as the harness contract. Change one of those only to repair a demonstrated
defect, add a regression test, and qualify it offline before creating another
campaign. Freeze the qualified harness by its code revision, image digest,
runtime-profile fingerprint, fixture/task/oracle fingerprints, and generated
campaign manifest; never retrofit a generated campaign.

Model identity, reasoning effort, task wording/selection, repetitions/seed,
request and token ceilings, and spending ceilings are experiment inputs. Put
them in a new versioned campaign specification and let the factory generate a
fresh immutable manifest. An experiment-input change does not justify rebuilding
the image unless it changes fixture dependencies or environment preparation.
Conversely, a tooling or environment failure is not a reason to raise the model
budget or proceed to another pilot: repair and regression-test the harness,
then create a fresh campaign identity.

The provider proxy persists each exact response before parsing its terminal
usage, accounts input and output tokens independently of the Codex transcript,
and serializes completion requests so only one response can be in flight. Before
forwarding each request, it reserves the UTF-8 request-body byte count plus the
configured maximum completion tokens against the remaining whole-session token
ceiling. Missing usage on a successful response blocks further requests. Runtime
and authenticated preflight also reserve worst-case token-priced cost plus a
response allowance; if the route cannot establish those bounds, admission must
fail closed. The byte-based prompt estimate is deliberately conservative and
must be compared with reported provider usage in every pilot.

## Pre-pilot control checklist

Complete this checklist for every new pilot before generating its campaign. Record
the selected task IDs, fixture revisions, model/provider controls, budgets, image
digest, profile fingerprint, and validation evidence in the versioned spec or
the campaign's durable artifacts.

- **Tasks and scoring:** verify task wording, task IDs, deterministic oracle
  behavior, required fixture coverage, treatment instructions, repetition
  count, and schedule seed. Confirm the tasks still test the intended Codira
  behavior. A task, oracle, prompt, seed, or repetition change requires a fresh
  campaign identity.
- **Fixture admission:** verify each fixture's commit, tree SHA, license, and
  setup-file hashes against its source checkout. Keep the pilot runner's
  required three-fixture coverage. Rebuild the candidate image when fixture
  content, dependencies, or environment preparation changes.
- **Image and runtime:** pin the freshly admitted image digest and the
  `scripts/agent_efficiency/benchmark-codira.toml` fingerprint. Check offline
  dependency preparation, runtime network isolation, MCP startup, index
  readiness and coverage, and the task-relevant capabilities, including cursor
  and whole-item behavior when the task uses pagination.
- **Harness qualification:** compare the factory, runner, provider proxy, MCP
  adapter, prompt construction, schedule, oracle evaluation, and evidence
  format with the qualified harness. Repair a demonstrated harness defect,
  add and run focused regression checks, and qualify it offline before creating
  a fresh campaign. Never change a generated campaign in place.
- **Model controls:** verify the exact model ID on the authenticated route for
  the selected key. Confirm Responses API compatibility, supported reasoning
  effort and mandatory-reasoning rules, context and output limits, usage
  reporting, and current prompt/completion prices at every relevant price tier.
  A model change requires a new versioned spec, fresh campaign identity, and
  recalculated budgets.
- **Provider controls:** verify the provider endpoint, authentication route,
  wire protocol, request and response mapping, usage and cost fields, and
  retry behavior. Confirm the existing proxy adapter supports that provider; a
  new or changed adapter is a harness change and must be regression-tested and
  qualified offline before paid use. A provider change requires a fresh
  campaign identity and authenticated preflight.
- **Budgets and account admission:** set the whole-session token ceiling,
  output ceiling, logical request cap, transport retry cap, timeout,
  per-attempt spend, pilot spend, and daily spend. Reserve each pending request
  before forwarding it, and use the authenticated context and output limits to
  calculate the attempt's worst-case spend. Pilot 020
  reached 507,635 reported tokens against a 500,000 whole-session cap before the
  old admission rule stopped the next request. For the next pilot, use 750,000
  whole-session tokens and 32,000 output tokens as the starting recommendation;
  recalculate for the selected task, model, and provider. With the previously
  admitted price ceilings of $0.25/$0.75 per million tokens and a 1.05-million
  token context, the attempt reserve is about $0.849: $0.5625 for 750,000
  tokens, plus $0.2865 for one context-sized prompt and 32,000 output tokens.
  That implies at least $0.90 per attempt and $5.40 for six attempts, subject to
  the authenticated route, active price tier, key limit, and daily cap. Require
  the offline factory and runtime to cover the declared token/output reserve,
  then require authenticated preflight to cover the actual context-sized
  response reserve. Do not copy these dollar values to another model or provider.
- **Oracle traceability:** confirm the result records each deterministic
  subcheck as pass/fail, including the individual patch/path/protected-command
  stages. Keep protected command exit status, output sizes and digests, and
  sanitized exception class/location; never put raw command output or private
  paths in public reports. Verify known-valid equivalent identifiers (such as
  dotted pytest names and pytest node IDs) are both accepted by the oracle.
- **Trajectory evidence:** confirm attempt summaries expose event and message
  counts, command success/failure/repetition, MCP calls and repetitions, and
  file-change timing without retaining prompt, tool arguments, output, or paths.
  Review these summaries alongside token use and the oracle before labeling a
  failure as non-convergence or concluding that it only needed more room. A cap
  exhaustion without progress evidence is inconclusive on that distinction.
- **Generation and launch gates:** generate only through the factory into a
  fresh output directory. Run offline manifest validation, verify the fixture
  receipt, and run the full repository gate in tmux with a durable log and exit
  status. Then perform authenticated route/key preflight. Start paid execution
  only under explicit authorization for that campaign, after all checks pass.
- **Evidence and retries:** preserve the immutable manifest, launch plan,
  receipt, exact provider responses, usage and cost records, per-attempt
  operational and oracle results, logs, and final report. Do not reuse an
  identity or automatically retry after a changed task, model, provider,
  prompt, budget, runtime, or harness control.

## Fixture-environment image preparation

Before generating a replacement pilot, build a fresh candidate image from the
selected frozen fixture revisions. The build is the only dependency-resolution
boundary: it may use Podman's private build network to populate package caches
and, for an npm fixture without an upstream lockfile, produce the exact lockfile
that will be embedded in that candidate image. The build script archives the
declared Git revisions rather than trusting the current branch tips, writes an
immutable profile with the setup hashes, and validates an offline preparation
inside the build. It never receives provider credentials.

```bash
uv run python scripts/build_agent_efficiency_environment_image.py \
  --base-image localhost/codira-phase6-onnx@sha256:<base-digest> \
  --fixture-source click-public=/absolute/path/to/click \
  --fixture-source picomatch-public=/absolute/path/to/picomatch \
  --fixture-source codira-public=/absolute/path/to/codira \
  --tag localhost/codira-phase6-fixtures:<fresh-tag> \
  --output-profile /absolute/fresh/output/environment-profile.json
```

Use the resulting immutable image identity in the new factory specification;
do not alter an earlier campaign. Every later environment-preparation, index,
and agent container runs with `--network=none`. The model receives a directive
that the project environment is already ready and must not install dependencies.

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
  --campaign-dir .artifacts/agent-efficiency/campaigns/<campaign-id> \
  --execution-root .artifacts/agent-efficiency/executions/<campaign-id>-execution \
  --seed <factory-seed> \
  --fixture-source click-public=/absolute/path/to/click \
  --fixture-source picomatch-public=/absolute/path/to/picomatch \
  --fixture-source codira-public=/absolute/path/to/codira

uv run python scripts/launch_agent_efficiency_pilot.py \
  --launch \
  --campaign-dir .artifacts/agent-efficiency/campaigns/<campaign-id> \
  --execution-root .artifacts/agent-efficiency/executions/<campaign-id>-execution \
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

Use a short execution-root name: the receipt keeps all resumable state beneath
`<execution-root>/state`, including records and response evidence. The provider
socket is a short-lived artifact under
`/home/marco/Personalia/Progetti/.Temp`, mounted at the stable in-container path
`/codex-state/provider.sock`; do not put durable campaign state in `.Temp`,
`/tmp`, or a user-wide cache.

The provider proxy persists each exact upstream response body to the ignored
attempt artifact directory before parsing or forwarding it. Public-safe
observations bind those bodies by digest and byte count. Routing disables
fallbacks and pins the approved model, reasoning, and price controls. Provider
parameter filtering remains disabled because the complete Responses/tool
request contains provider-specific fields that would otherwise produce a
false no-endpoint rejection; the proxy still rejects model or reasoning
substitution locally.
