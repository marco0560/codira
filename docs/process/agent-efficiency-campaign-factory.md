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
- `full-campaign`: exactly six tasks across three admitted fixtures, a
  deterministic `seed`, and exactly five repetitions per task: sixty paired
  baseline/Codira-MCP attempts. The specification must pin the runtime image
  and profile. Its launch plan also freezes each selected oracle fingerprint
  and the host harness fingerprint, and requires executor qualification and
  registry image admission.
- `completion`: exactly six unfinished slots in three complete pairs of a
  frozen parent full campaign. The versioned specification names the parent
  campaign directory, state root, seed, and six attempt IDs with paths inside
  this repository. The factory checks the parent schedule and saved records,
  then freezes their exact byte digests. It rejects cherry-picked subsets,
  completed slots, and changed parent evidence. A completion uses a fresh
  campaign identity and observed shared pool. Its results can join the parent
  in a labeled composite analysis, not an unchanged-harness run.

Check an existing factory output against the current specification, tasks,
fixtures, and (for a full campaign) oracles without rewriting its artifacts:

```bash
uv run python scripts/generate_agent_efficiency_campaign.py \
  --check \
  --spec benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-006.json \
  --output-dir .artifacts/agent-efficiency/campaigns/codira-efficacy-campaign-006
```

Generation and this offline check do not admit paid execution. The deterministic
executor accepts pilots, full campaigns, and completions. Full campaigns and
completions use the registered pilot runner with `--full-campaign --launch-plan`;
a pilot invocation still rejects shared-pool accounting. Plan verification
checks all sixty members of a full campaign or the six selected parent members
of a completion, plus the applicable oracles, harness fingerprint, and six-hour
checkpoint before credential access.
The legacy accounting field `max_estimated_pilot_spend_usd` means the aggregate
spending allowance for the selected stage, including a full campaign.

`accounting.budget_reservation_mode` accepts `sum-attempt-ceilings` (the
default) or `shared-pool`. The default retains the bounded pilot's upfront
attempt reservations. A full campaign's `shared-pool` instead stops on
observed aggregate charges under the frozen spending basis. It admits the next attempt while the recorded total is below
the pool, and its proxy admits the next completion while that attempt has not
used the remaining pool. The final response may cross the threshold; no
further completion or attempt is admitted. This can leave an incomplete pair.
The full-campaign token and per-attempt dollar figures are planning estimates,
not additional execution stops. The output-per-response, logical request,
transport retry, and timeout controls remain enforced. The runner uses an
exclusive process lock and immutable start and settlement files under
`state/budget/`. A settlement requires complete received provider usage and
a matching immutable result record. Unfinished starts, unknown billing,
changed budget identity, operational failures, and oracle-contract defects
block automatic resumption. Scored task failures remain results and do not
add attempts.

For new OpenRouter campaigns using `shared-pool`, the factory always freezes
`accounting.spend_basis` as `provider-reported` and rejects ceiling-based
stopping. The proxy retains terminal
Responses `usage.cost` as an exact decimal `provider_cost_usd` observation;
both completion admission and campaign settlement use that charge. Zero is
valid. Missing, negative, nonfinite, malformed, or incomplete billing blocks
further requests and settlement. Token usage and conservative price-ceiling
estimates remain available separately; they are not actual spending. Provider
price ceilings still qualify the route before execution. One final response
may cross the soft pool threshold, as before.

The omitted or explicit `price-ceilings` basis preserves historical manifests
only; the factory rejects it for new shared pools.
It charges all input tokens at the frozen input ceiling, including cached
input, and must be described as a conservative estimate rather than a bill.
It can substantially overstate charges and stop an otherwise affordable run.
Never change a frozen campaign or relabel its settlement files. A changed
basis requires a fresh factory identity; provider-reported journal identities
bind the basis explicitly, so resuming under another basis fails. An aggregate
key usage figure includes other runs and does not identify a campaign's cost.
For forensic reconciliation, sum hash-verified terminal response costs in a
separate report while retaining the original journals.

OpenRouter documents returned cost accounting in its
[usage-accounting reference](https://github.com/OpenRouterTeam/docs/blob/main/cookbook/administration/usage-accounting.mdx).

Accounting declares the meaning of `budgets.max_total_tokens` through the
optional `accounting.max_total_tokens_scope`. Fresh multi-continuation pilots
use `whole-session`, so the ceiling is reserved once per execution; historical
manifests without the field retain the conservative `per-continuation`
reservation. For full-campaign `shared-pool` mode, that field is a planning
estimate; the measured dollar pool is the budget stop. Logical continuation
and transport-retry caps remain independent operational limits.

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
and serializes completion requests so only one response can be in flight.
Bounded pilots still reserve the UTF-8 request-body byte count plus maximum
completion tokens against their token ceiling. Full campaigns use observed
ceiling-priced provider usage against their shared pool instead. Missing usage
on a successful response blocks further requests in either mode. Authenticated
preflight still verifies the selected route, price ceilings, context/output
limits, and at least the declared pool remaining on the scoped key. Its
`context_response_upper_bound_usd` is an informational upper bound for the
authorized final-response overshoot, not an upfront reservation.

## Pre-pilot control checklist

Complete this checklist for every new pilot before generating its campaign. Record
the selected task IDs, fixture revisions, model/provider controls, budgets, image
digest, profile fingerprint, and validation evidence in the versioned spec or
the campaign's durable artifacts.

The [campaign 011 forensic review](agent-efficiency-campaign-011-forensic-analysis-2026-10-02.md)
adds mandatory qualification of the actual execution boundaries. Component
checks alone do not qualify a runner. Before another campaign:

- Qualify rootless Podman and tmux from the actual authorized host launch
  context. Record which operations require that context instead of repeatedly
  attempting them inside an incompatible outer agent sandbox.
- Resolve source/interpreter, native client and fixture bindings once into the
  prepared receipt. Verify imports, standard-library resolution and source
  fingerprints inside the generated tmux child. Do not depend on hand-entered
  paths or mutate tmux's global environment to recover a frozen product source.
- Exercise ordinary shell, Git, uv, Codira CLI and task tests under the exact
  native permissions profile. Keep writable tool home/config/cache separate
  from denied credential state; consistently bind the qualified profile,
  offline model assets and index paths in both arms.
- Prove successful native MCP authorization and dispatch, rather than only
  server startup, tool discovery or direct MCP qualification. Optional agent
  tool use does not waive tool availability. Count successful, denied and
  unattempted MCP exposure separately; systemic denial blocks an efficacy claim.
- Replay correct, incomplete and wrong cases through the full campaign path:
  export, prepare, snapshot, edits, runner patch capture, complete composite
  oracle, record and report. Include installed dependency symlinks and new test
  files. Patch-only or curated-text calibration cannot substitute for this
  replay. Preserve prior subcheck results if a later rubric branch errors.
- Validate semantic decisions against frozen source and execution evidence.
  Digests and answer quotes establish integrity, not factual correctness.

The deterministic executor now assembles these checks in one `--prepare` pass
and writes `readiness-receipt.json` only after every required boundary passes.
The launch path and the generated runner independently enforce that receipt.
Both OpenRouter and native subscription representative campaigns use this
pipeline. OpenRouter authentication and its genuine model-requested MCP canary
run in scoped SOPS children through the campaign proxy; preparation records
their USD usage separately and repeats key-budget admission afterward.
See [mechanical readiness admission](agent-efficiency-readiness-2026-10-02.md)
for the exact check inventory, expiration rule, commands and coverage limits.
Changed harness controls require a fresh factory identity; campaign 011 remains
an immutable historical record.

- **Tasks and scoring:** verify task wording, task IDs, deterministic oracle
  behavior, required fixture coverage, treatment instructions, repetition
  count, and schedule seed. Confirm every protected command script is present
  in the admitted fixture or has a matching, digest-verified protected asset
  record, and that the grader can prepare and execute it offline. Confirm the
  tasks still test the intended Codira behavior. A task, oracle, prompt, seed,
  or repetition change requires a fresh campaign identity.
- **Fixture admission:** verify each fixture's commit, tree SHA, license, and
  setup-file hashes against its source checkout. Keep the selected stage's
  required fixture coverage; representative campaigns use their generated
  panel inventory rather than the legacy pilot's three-fixture rule.
  Rebuild the candidate image when fixture
  content, dependencies, or environment preparation changes.
- **Image and runtime:** pin the freshly admitted image digest and the
  `scripts/agent_efficiency/benchmark-codira.toml` fingerprint. Full, completion
  and representative campaigns admit digest-pinned references under
  `ghcr.io/marco0560/codira-agent-benchmark@sha256:` or `localhost/`. The common
  validator runs before preparation/authenticated preflight and again at
  execution. Both namespaces require identical image/source/profile and
  readiness qualification. Follow the
  [image admission check](campaign-creation-instructions-2026-10-03.md#check-image-admission-before-paid-preparation)
  and resolve any rejection before a model canary. Check offline
  dependency preparation, runtime network isolation, MCP startup, index
  readiness and coverage, and the task-relevant capabilities, including cursor
  and whole-item behavior when the task uses pagination.
- **Harness qualification:** compare the factory, runner, provider proxy, MCP
  adapter, prompt construction, schedule, oracle evaluation, and evidence
  format with the qualified harness. Repair a demonstrated harness defect,
  add and run focused regression checks, and qualify it offline before creating
  a fresh campaign. Before factory generation, reconcile exact suppression
  locations and exceptions in `docs/process/lint-and-semgrep-hygiene.md` and
  require `uv run pytest -q tests/test_quality_policy.py` to pass on the final
  edits. Never change a generated campaign in place.
- **Model controls:** verify the exact model ID on the selected authenticated
  route. Confirm supported reasoning effort, mandatory-reasoning rules, model
  limits and usage reporting. For OpenRouter, check Responses compatibility and
  current prompt/completion prices at every relevant tier through the scoped
  key. For native subscription, check the qualified native client, managed login,
  exact model/effort and quota; dollar prices are not applicable and planning
  limits must not be represented as proxy-enforced controls.
  A model change requires a new versioned spec, fresh campaign identity, and
  recalculated budgets.
- **Provider controls:** verify the provider endpoint, authentication route,
  wire protocol, request and response mapping, usage and cost fields, and
  retry behavior. Confirm the existing proxy adapter supports that provider; a
  new or changed adapter is a harness change and must be regression-tested and
  qualified offline before paid use. A provider change requires a fresh
  campaign identity and authenticated preflight.
- **Budgets and account admission:** set the planning token amount,
  output ceiling, logical request cap, transport retry cap, timeout,
  per-attempt estimate, campaign pool, and daily spend. For bounded pilots,
  retain request and attempt reservations and calculate worst-case spend from
  authenticated context/output limits. Pilot 020 reached 507,635 reported
  tokens against its 500,000 whole-session cap. Pilot 021 used a 750,000-token
  cap, but the patch Codira-MCP attempt had its 21st response denied after 20
  upstream responses. Its trajectory had no file change after 58 events, 18
  commands (8 failed), and 2 MCP calls, so the run does not establish that more
  tokens would make the task converge. For the next pilot, use 1,000,000
  whole-session tokens and 32,000 output tokens as a diagnostic ceiling, with a
  progress-based stop rule; recalculate for the selected task, model, and
  provider. Recalculate the worst-case spend reserve from the authenticated
  context and active price tiers; the earlier $0.849 reserve was for 750,000
  tokens and is not valid for the new ceiling. Require the offline factory and
  runtime to cover the declared token/output reserve, then require authenticated
  preflight to cover the actual context-sized response reserve. Do not copy
  dollar values to another model or provider.
  For a full campaign using a shared pool, verify persisted observed charges,
  per-response stopping at the remaining pool, and the authorized possibility
  of one response crossing the threshold. Do not apply the pilot's token or
  per-attempt dollar stops to this mode. A smaller pool can stop execution
  before all scheduled attempts complete, including within a pair; preserve
  pending identities rather than silently expanding the pool. The factory's
  offline admission is not proof of runtime enforcement.
- **Oracle traceability:** check known-correct answer variants against each
  text oracle, including paraphrases that retain the requested facts, and
  known-wrong answers that omit a required identity or path. Do not make an
  explanatory phrase an exact-match requirement unless the task explicitly
  asks for that phrase. Confirm the result records each deterministic
  subcheck as pass/fail, including the individual patch/path/protected-command
  stages. For patch tasks, require the exact necessary source and test paths and
  reject every undeclared changed path. Keep protected command exit status,
  output sizes and digests, and sanitized exception class/location in the
  public-safe checks. Retain complete protected stdout/stderr bytes and the
  exact command/stage manifest under the ignored per-attempt `oracle-trace/`
  directory for forensic review. Never put raw command output, trace manifests,
  or private paths in public reports.
  Verify known-valid equivalent identifiers (such as dotted pytest names and
  pytest node IDs) are both accepted by the oracle.
- **Trajectory evidence:** confirm public attempt summaries expose event and
  message counts, command success/failure/repetition, MCP calls and repetitions,
  and file-change timing without exposing prompt, tool arguments, output, or
  paths. The private attempt artifacts retain the full event stream and
  captured process diagnostics for forensic review.
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

## Full-campaign checkpoints and resume

Full campaigns checkpoint between complete pairs after six hours. The original
launch receipt and frozen schedule remain unchanged. Use the deterministic
executor with the same campaign directory, execution root, seed, runtime, and
fixture sources, replacing `--launch` with `--resume`. Each invocation gets a
separate `resume-NNN-receipt.json`, log, exit file, and tmux session; no completed
result or earlier log is overwritten. The runner revalidates the entire budget
journal before executing pending attempts.

A key top-up can resolve a clean authenticated admission stop, and a daily
allowance reset can fund a later invocation. Neither changes the campaign's
fixed aggregate ceiling. Current route admission requires
the entire declared aggregate allowance to remain available on the key;
execution in smaller funded chunks is not yet qualified. The key's `limit`
may exceed the local campaign ceiling when earlier key usage leaves the
full allowance available. The persistent campaign pool is a soft observed
spending threshold, and the final response may cross it; the ordinary pilot
retains its stricter key-limit check. Once observed charges reach the pool,
the campaign stops with its pending schedule preserved, possibly including
the unmatched arm of a pair. Changing the frozen campaign ceiling needs
explicit approval and a new immutable experiment identity; do not edit the
budget journal.

A provider or transport failure during an attempt requires diagnosis: topping
up does not make uncertain billing or an unfinished start safe to retry.
Preserve the failed attempt and its raw evidence. Automatic retries of failed
attempts are not qualified. Explicit paid authorization remains required for
initial launch and for a restart after a diagnosed stop.

## Recorded route qualification

Pilot 025 provides a bounded qualification record for the exact OpenRouter
Responses route `openai/gpt-6-luna` at high reasoning, using the harness
revision recorded by its campaign, the `mcp-required-v2` treatment, and its
pinned runtime image and profile. Authenticated preflight and all six scheduled
attempts completed successfully; see the [Pilot 025 comparison](agent-efficiency-pilot-025-comparison-2026-09-29.md)
and its linked immutable evidence.

This qualifies that route and harness combination for the recorded pilot only.
It does not establish general model quality, an MCP treatment effect, or
qualification of another OpenRouter model, provider, reasoning setting, or
harness revision. The pre-pilot checklist above remains mandatory: verify the
current authenticated route, limits, prices, usage contract, and harness before
every campaign, even when its proposed settings match Pilot 025.

## Fixture-environment image preparation

Before generating a replacement pilot, build a fresh candidate image from the
selected frozen fixture revisions. The build is the only dependency-resolution
boundary: it may use Podman's private build network to populate package caches
and, for an npm fixture without an upstream lockfile, produce the exact lockfile
that will be embedded in that candidate image. The build script archives the
declared Git revisions rather than trusting the current branch tips, writes an
immutable profile with the setup hashes, and validates an offline preparation
inside the build. It never receives provider credentials.

The builder also retains recipe-only reconstruction records by default under
`.artifacts/agent-efficiency/image-rebuilds/`, including the generated source
context and post-build dependency inventory. Rebuilt images can differ and must
receive fresh campaign identities. See [image rebuild retention](image-rebuild-retention.md)
for reconstruction commands, parent-image requirements and historical-image review.

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

For the representative campaign, prepare and then launch the factory artifacts
through the deterministic executor. Other inventories require complete calibration
coverage before this executor admits them. The supplied seed must reproduce
the complete frozen schedule. Every fixture source is re-admitted both during
preparation and immediately before tmux starts:

```bash
uv run python scripts/launch_agent_efficiency_pilot.py \
  --prepare \
  --campaign-dir .artifacts/agent-efficiency/campaigns/<campaign-id> \
  --execution-root .artifacts/agent-efficiency/executions/<campaign-id>-execution \
  --seed <factory-seed> \
  --subscription-codex <qualified-native-executable> \
  --subscription-auth-source <existing-managed-login-path> \
  --fixture-source click-public=<absolute-click-source> \
  --fixture-source picomatch-public=<absolute-picomatch-source> \
  --fixture-source codira-current-public=<absolute-codira-source> \
  --fixture-source python-service-synthetic=<absolute-python-source> \
  --fixture-source typescript-workspace-synthetic=<absolute-typescript-source> \
  --fixture-source go-service-synthetic=<absolute-go-source>

uv run python scripts/launch_agent_efficiency_pilot.py \
  --launch \
  --execution-root .artifacts/agent-efficiency/executions/<campaign-id>-execution
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
the operator temporary directory defined in `AGENTS.md`, mounted at the stable in-container path
`/codex-state/provider.sock`; do not put durable campaign state in `.Temp`,
`/tmp`, or a user-wide cache.

The provider proxy persists each exact upstream response body to the ignored
attempt artifact directory before parsing or forwarding it. The runner also
retains captured environment/index preparation output, the Codex JSONL event
stream, container stderr, and protected oracle stdout/stderr there. These
private traces can contain diagnostics and paths; public reports expose only
the safe summaries and digests. Keep raw traces while the campaign may need
forensic review; remove them only with explicit operator approval under the
repository artifact retention policy. Preserve immutable records and their
fingerprints. Public-safe observations bind provider bodies
and protected command streams by digest and byte count. Routing disables
fallbacks and pins the approved model, reasoning, and price controls. Provider
parameter filtering remains disabled because the complete Responses/tool
request contains provider-specific fields that would otherwise produce a
false no-endpoint rejection; the proxy still rejects model or reasoning
substitution locally.

## Additional pre-pilot controls: product and representative panel

Apply these checks before every fresh pilot or campaign, including model or
provider changes; they extend the existing Pre-pilot control checklist.

- [ ] Pin serving core/analyzer source hashes, actual registered MCP schemas,
  profile hash and image digest. Require offline indexed image qualification
  before authenticated provider preflight; reject legacy or mismatched images.
- [ ] Probe limit-one continuation, wrong-query/stale cursors, owner-qualified
  methods, whole definition expansion and truthful static coverage.
- [ ] Calibrate each task rubric on known-correct, incomplete, subtly wrong and
  equivalent answers. Plan blinded quote-bound review; pending review is not a
  passing task. Preserve original oracle decisions and all raw traces.
- [ ] For `representative-campaign`, check `representative-v1` generated assets,
  all 24 tasks, eight families, 12/12 development/holdout balance and frozen
  synthetic inventories/protected hashes. Admit one to five repetitions.
- [ ] Separate optional MCP (`mcp-optional-v3`, shared common prompt) from the
  required-use ablation (`mcp-required-v3`). Identify interface-only controls
  in analysis and inspect baseline CLI use.
- [ ] Confirm byte/timing/cache/failure-cost instrumentation and task-level
  paired distributions. First-reference detection is a proxy, not semantic
  quality. Use small synthetic fixture results within their measured scope.
- [ ] Generate a fresh immutable factory identity after any control change;
  re-run offline validation and the full gate, then authenticated route checks
  and explicit paid authorization. No qualification check is a paid launch.

See [implementation and limits](agent-product-harness-improvements-2026-10-01.md).

## Native subscription controls

See [Native Codex subscription provider](agent-efficiency-subscription-provider.md)
for the route contract, isolation qualification and evidence limitations.
Extend the pre-pilot checklist when selecting this route:

- [ ] Freeze a separate provider identity and native model ID; never reuse an
  OpenRouter campaign or silently switch routes during a campaign.
- [ ] Confirm the exact client executable, bundled sandbox binary and image
  digest. Run the public credential-denial canary before mounting managed login.
- [ ] Read plan, exact model/effort and quota through the actual container route,
  without a model turn; retain only sanitized admission facts.
- [ ] Treat native USD accounting as not applicable. Confirm timeout, quota and
  checkpoint controls, and acknowledge that native request/output caps are not
  proxy-enforced and the session token ceiling is checked after a completed turn.
- [ ] Retain complete native events and diagnostics. Label raw provider HTTP
  evidence unavailable rather than reporting empty evidence as successful capture.
- [ ] Exercise quota exhaustion, interrupted starts, explicit resume, rejected
  routes and provider/accounting schema combinations in focused checks.
- [ ] Calibrate every task against the admitted frozen source, including whole
  responses and applied patch behavior. A correct reference phrase alone is not
  proof that the complete rubric or protected oracle accepts correct work.


## Representative continuation after a budget stop

Use a new `completion` campaign specification with `panel_id: representative-v1`,
the parent's repetition count and seed, and `completion_source` pointing to the
parent campaign directory, state directory and exact unfinished attempt IDs.
The factory verifies the entire original paired schedule and selects every
unfinished slot in parent order, including a single arm whose counterpart is
already settled. It rejects omissions, repeated completed slots, active parent
executors, unknown billing starts, failed operational parent records other than a diagnosed campaign-budget
interruption with verified complete provider billing, and changed source
evidence. Task/oracle identities, runtime image and core source, provider,
resource controls, response budgets and treatment instructions remain bound to
the parent; the host accounting harness changes under a fresh identity.

The plan retains digests of all parent records and billing journals. Parent
reported charges are reconstructed from every exact, SHA256-verified retained
terminal provider response. Missing or malformed charges block generation and
readiness. Those charges seed the new budget journal, so the original campaign
pool funds the parent and continuation together. Reports distinguish initial
parent spending, new spending, and cumulative charges. Existing parent records
and conservative historical settlements are never rewritten. Fresh readiness,
authenticated route admission and explicit operator launch authorization still
apply. Generation is not execution.

Git worktrees may read parent artifacts from their shared repository root;
repository-relative paths remain confined to the trusted checkout or its Git
common root. Retain both worktrees and all source/run evidence while a
continuation is active.
