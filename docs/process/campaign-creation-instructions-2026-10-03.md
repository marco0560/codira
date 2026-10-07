# Campaign creation instructions — 2026-10-03

This procedure creates fresh representative agent-efficiency campaigns through
OpenRouter or the native Codex subscription route. It separates input selection,
credential-free factory generation, complete readiness preparation, authorized
campaign execution and analysis. Preparation includes a real model canary and
therefore consumes credits or subscription quota even though it does not start
the main campaign.

Run commands from the repository root. Replace every `<placeholder>` before
execution. Commands below are templates, not authorization to spend credits,
consume quota, publish an image or launch a campaign. Stop on a failed command;
do not continue through a partial preparation.

## 1. Establish the supported experiment and operator parameters

Read these current sources before acting:

- [AGENTS.md](../../AGENTS.md).
- [Factory and pre-pilot checklist](../process/agent-efficiency-campaign-factory.md).
- [Mechanical readiness](../process/agent-efficiency-readiness-2026-10-02.md).
- [OpenRouter readiness](../process/agent-efficiency-openrouter-readiness-2026-10-03.md).
- [Native subscription provider](../process/agent-efficiency-subscription-provider.md).
- [Historical preparation](../process/agent-efficiency-campaign-preparation-2026-10-02.md),
  for experiment intent and historical evidence, not current prices or capacity.
- [Artifact layout and retention](../../.artifacts/MANIFEST.md).

The current complete readiness pipeline admits `representative-campaign` with
the existing representative panel: 24 tasks in eight families, two paired arms,
and one to five repetitions. One repetition means 48 attempts per model. The
factory also knows legacy stages, but their existence does not make them
admissible through this complete readiness pipeline. A new inventory or panel
requires explicit harness/calibration support before execution.

The comparison is optional Codira MCP availability against the baseline shell
condition. Codira CLI remains installed in both arms. Preserve the common
instructions, `mcp-optional-v3` treatment and paired controls when comparing
models. The readiness canary must actually use MCP; campaign tasks may choose
whether to use it. Report freshness/diagnostic tasks separately where appropriate.

Resolve these parameters once and retain their approved values:

| Parameter | Required decision |
| --- | --- |
| Campaign identity | Fresh campaign ID per provider/model/control set |
| Execution identity | Fresh execution root per preparation attempt |
| Source | Exact serving source revision or immutable snapshot, including required recent modifications |
| Task fixture | Keep the admitted Codira fixture, or explicitly update it and regenerate its references/calibrations |
| Provider/model | Exact authenticated model ID and route; never choose a fallback |
| Reasoning | Supported policy for that exact model; identical labels need not mean equal computation across models |
| Schedule | Seed and repetitions; retain `20261002` and one repetition if intentionally matching the old schedule |
| Runaway guards | Timeout, token planning/guard value, output allowance, logical request and transport retry limits |
| OpenRouter budget | Positive prompt/completion price ceilings, attempt estimate/canary ceiling, campaign pool and daily ceiling |
| Native login | Qualified native executable and existing managed ChatGPT login path |
| Evidence/reporting | Durable artifact IDs and dated report names |

Models such as DeepSeek V4.1 Flash, Grok 4.7 and Qwen use OpenRouter model IDs
only if the scoped authenticated catalog admits them. Do not reuse old model
prices, infer availability from a public page or assume every model supports
the same reasoning settings. Three models at one repetition mean three fresh
campaigns and 144 main attempts, plus their separately accounted canaries.

### Input-selection prompt

```text
Prepare the parameters for a new representative Codira efficacy campaign.
Read AGENTS.md and docs/proces/campaign-creation-instructions-2026-10-03.md,
then the authoritative factory, readiness and provider documents it references.

Use campaign 010 as the experimental-design reference. Preserve the 24-task
paired baseline/optional-Codira-MCP intent and common instructions.
Provider: <OpenRouter or native Codex subscription>.
Model(s): <exact candidates>.
Serving source: <revision or latest checkout including the required modifications>.
Codira task fixture: <retain the admitted fixture or update to selected revision>.
Repetitions/seed: <values>.
Runaway guard preferences: <time/tokens/requests/retries>.
Budget: <OpenRouter USD pool and daily ceiling, or native quota only>.

Inspect the existing implementation and local state. Ask only for unresolved
material choices, together in one parameter summary. Distinguish serving-source
updates from task-fixture updates. Identify any unsupported inventory or route.
Do not launch, make model calls, read credential contents, or invent model prices.
Return concrete parameters and the source/image/fixture work needed before
factory generation. Resolve host-only execution requirements before using tools.
```

## 2. Freeze source and fixture inputs

Inspect the selected checkout through Codira first. Record the actual revision,
working-tree changes and installed serving identity:

```bash
git status --short
git log -1 --format='%H %cI %s'
uv run python -c 'import json; from codira.runtime_identity import runtime_identity; print(json.dumps(runtime_identity(), indent=2, sort_keys=True))'
```

HEAD alone does not include uncommitted or untracked modifications. Complete and
freeze required modifications before generation; obtain commit authorization
if a commit is needed. Preserve unrelated work. Do not describe an old image as
the latest source merely because it is used as the base image.

The serving fingerprint also includes ignored generated Python files such as
`src/codira/_version.py`. A clean Git status does not prove that those bytes
match the image. Wheel tests must build the core from a disposable source copy
and preserve the live generated metadata; setuptools-scm builds in the live
checkout rewrite that file for the current commit. The integration test
`test_core_can_discover_installed_first_party_packages_from_built_wheels`
asserts that the live metadata survives its real wheel build unchanged.
Inspect runtime identity in a fresh Python process after validation as well as
before factory generation. A mismatch blocks model work and requires diagnosis
and a newly qualified identity when serving bytes change. Preserve accidental
validation side effects and their rollback evidence; do not hand-edit version
fields or rewrite campaign artifacts to conceal a mismatch.

Bind fixtures to the revisions/trees declared by their fixture documents.
Preserve checkouts durably, outside `.Temp`, with stable absolute paths. For a
Git fixture whose declared revision is already selected, a detached worktree
can be created with:

```bash
git -C '<fixture-source-repository>' worktree add --detach \
  '<durable-new-checkout-path>' '<declared-fixture-revision>'
```

The current panel uses these six fixture IDs:

- `click-public`
- `picomatch-public`
- `codira-current-public`
- `python-service-synthetic`
- `typescript-workspace-synthetic`
- `go-service-synthetic`

Advancing the serving Codira source does not advance `codira-current-public`.
Updating the investigated fixture requires compatible task seeds, reference
answers, protected assets, setup hashes and rubric/patch examples. Update source
inputs through their existing generators, then check generated documents:

```bash
uv run python scripts/generate_agent_efficiency_panel.py --check
uv run python scripts/calibrate_agent_efficiency_panel.py --check
```

If intentionally changing panel inputs, run the corresponding generator without
`--check`, inspect the changes, then rerun checks. Do not rewrite frozen campaign
artifacts. This generator currently targets `representative-v1`; it is not a
generic new-panel factory. A changed inventory requires implementation work.

## 3. Resolve host execution and build the environment image

Podman, tmux, rootless runtime/socket access and controlled dependency downloads
are host operations. An assistant should request the required host context
directly using the applicable tool permission mechanism, rather than repeatedly
attempting these commands inside an incompatible outer sandbox. Host execution
does not relax the measured container's isolation.

Use `.Temp` only for disposable build/scratch material. Retain image profiles,
logs, source snapshots and campaign evidence under durable repository locations.
Do not supply provider credentials to an image build.

The repository image builder copies the current checkout's core source and
Python/TypeScript/Go analyzers, reinstalls them in the pinned base, exports the
declared fixture revisions and prepares offline environments. Its serving
identity must agree with the inspected host source. `--codex-bin` takes a
directory containing `codex` and `codex-code-mode-host`, with the sibling
`codex-resources/bwrap`; it does not take a package-manager launcher script.

```bash
uv run python scripts/build_agent_efficiency_environment_image.py \
  --runtime podman \
  --base-image '<qualified-base-image@sha256:digest>' \
  --codex-bin '<absolute-qualified-native-binary-directory>' \
  --fixture-source 'click-public=<absolute-frozen-checkout>' \
  --fixture-source 'picomatch-public=<absolute-frozen-checkout>' \
  --fixture-source 'codira-current-public=<absolute-frozen-checkout>' \
  --fixture-source 'python-service-synthetic=<absolute-frozen-checkout>' \
  --fixture-source 'typescript-workspace-synthetic=<absolute-frozen-checkout>' \
  --fixture-source 'go-service-synthetic=<absolute-frozen-checkout>' \
  --tag '<fresh-candidate-image-tag>' \
  --output-profile '.artifacts/agent-efficiency/environment-images/<fresh-build-id>/environment-profile.json'
```

Use the returned `runtime_image` digest, not the mutable tag. Preserve failed
build logs and choose fresh build output identities. If registry publication is
needed, treat it as a separately authorized action; the build command does not
publish an image. All qualification must use the final selected digest.

Before selecting the final image reference, check campaign image admission as
shown below. Full, completion and representative campaigns admit digest-pinned
`ghcr.io/marco0560/codira-agent-benchmark@sha256:...` references and
`localhost/...@sha256:...` references. Both require the same image/source/profile
qualification and complete readiness evidence. A local image reference does
not imply registry publication. Mutable tags and other namespaces are rejected
before preparation or authenticated preflight, and checked again at execution.

Record the runtime-profile fingerprint separately from the environment-image
profile fingerprint:

```bash
uv run python -c 'from scripts.run_agent_efficiency_phase6_pilot import runtime_profile_fingerprint; print(runtime_profile_fingerprint())'
```

The image qualification later verifies installed source/analyzer identities,
profile and active analyzers. A successful build alone is not readiness.

Temporary repositories created by fixture tests must also run offline. The
attempt runner installs the qualified base profile at
`/workspace/.benchmark/home/.config/codira/config.toml`, shared by both arms.
This user-level profile supplies the baked ONNX model when a library call
indexes a temporary root without its own configuration; repository-local
settings still take precedence. `CODIRA_CONFIG_FILE` alone is a CLI path
selection and does not supply that fallback to direct library calls.

The credential-free native shell probe must index and query a temporary
repository with the isolated HOME, in addition to checking CLI operation.
Create that sample in the container's normal temporary directory, outside
excluded paths such as `.benchmark`; assert a nonempty symbol result as well
as successful indexing. A probe inside an excluded tree can return a zero-file
index despite valid model configuration.
When selecting Codira fixture tests, qualify their temporary-root behavior in
the exact network-disabled image as well. A successful host test gate may use
cached models unavailable to the measured container and cannot replace this
check. Preserve the offline proof and require a fresh factory identity after
changing these harness bindings; do not repair a historical campaign in place.

### Qualify native tools with the measured transport policy

The recurrent `bwrap: setting up uid map: Operation not permitted` failure
means the native command tried to create an inner user namespace inside the
rootless measured container. Host execution alone does not resolve this
nested-sandbox incompatibility. A successful `codex features list`, image build
or direct shell command also does not exercise native tool dispatch.

Before paid contact, require the pipeline's credential-free
`native-tool-dispatch` check to pass for both baseline and MCP arms on the final
image. Its shell probe must use the same permissions as the measured transport:

- OpenRouter attempts already use `codex exec --sandbox danger-full-access`
  inside the isolated container. The native app-server `command/exec` probe
  must explicitly send `sandboxPolicy = {"type": "dangerFullAccess"}` too.
  An omitted policy inherits `workspace-write` from the isolated configuration
  and attempts the unsupported Bubblewrap namespace again.
- Native subscription probes retain their configured filesystem permissions,
  including the `/codex-state` denial protecting managed authentication. The
  OpenRouter override is specific to that transport.

The outer measured container retains `--network=none`, its read-only root,
`--cap-drop=ALL`, `no-new-privileges` and resource limits. Fix a probe/attempt
policy mismatch in
[`native_tool_qualification.py`](../../scripts/agent_efficiency/native_tool_qualification.py);
do not change those outer controls to make the probe pass. The regression test
`test_native_shell_probe_matches_transport_and_retains_failures` verifies
transport selection, retained shell responses and blocking failures.

On this error, inspect the retained `native.stderr` and `native.shell.json`
under `readiness/native-tool-dispatch/<arm>/`. Older failed checks may lack the
shell response; preserve them and use a separate credential-free diagnostic
identity. Preserve each failed execution root. A harness correction requires
a fresh factory identity and complete preparation, rather than reusing the
failed receipt or automatically retrying model work. Require effective MCP
approval and actual successful native `index_status` and `context_for_task`
dispatch in the same check.

The [official app-server command contract](https://learn.chatgpt.com/docs/app-server#command-execution)
documents the explicit `sandboxPolicy` field. The later model canary separately
proves model-requested tools; this offline check is a prerequisite for it.

## 4. Create a versioned specification and generate factory artifacts

Use campaign 010's versioned spec as the OpenRouter design template, or 011's
as the subscription template. They are historical inputs, not ready launch
artifacts for the current harness.

```bash
cp --no-clobber benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-010.json \
  benchmarks/agent-efficiency/campaign-specs/<fresh-openrouter-campaign-id>.json
```

```bash
cp --no-clobber benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-011.json \
  benchmarks/agent-efficiency/campaign-specs/<fresh-subscription-campaign-id>.json
```

Use only the applicable template. Edit the new spec before generation:

- Set the fresh `campaign_id`, selected seed and repetitions.
- Set the final `runtime_image`, current `runtime_source_fingerprint` and
  `runtime_profile_fingerprint`. Obtain serving source SHA-256 from
  `runtime_identity()`; do not substitute a Git commit SHA.
- Set approved model/reasoning, budgets and accounting. Preserve resource and
  treatment controls unless a deliberate experiment change was approved.
- Preserve `stage="representative-campaign"`, the supported panel/task set and
  `max_total_tokens_scope="whole-session"` for this procedure.

| Field | OpenRouter | Native subscription |
| --- | --- | --- |
| `provider.name` | `openrouter` | `codex-subscription` |
| `provider.wire_api` | `responses` | `codex-cli` |
| Model spelling | Exact OpenRouter ID | Exact native catalog ID |
| Prompt/completion price ceilings | Positive USD per million tokens | `0` means not applicable |
| `budget_reservation_mode` | `shared-pool` | `subscription-quota` |
| Daily/attempt/campaign USD fields | Positive approved values | All `0`, not applicable |
| Authentication | Registered SOPS children | Existing managed ChatGPT login |

The retained 1,000,000-token value is a session planning/guard parameter, not the
model's context window. Keep limits generous enough to stop runaway work without
forcing otherwise useful tasks to stop prematurely. Output, logical requests,
transport retries and timeout are independent controls. On OpenRouter main
shared-pool execution, the token/attempt figures are planning estimates and the
observed USD pool stops new work; the readiness canary additionally applies
token and attempt/campaign USD guards. Native session tokens are checked after
the turn; its proxy request/output/retry values are planning controls, not
equivalent enforcement. Declare these differences in cross-provider analysis.
Provider-reported prompt/completion prices may be zero; a valid zero price is
admitted separately from the positive proxy/factory safety ceilings. Include
cache-write rates when selecting a conservative input ceiling: Luna's $0.20/M
long-context prompt rate has a $0.25/M cache-write rate. The shared-pool ledger
uses frozen ceilings even for a zero-priced provider, so report that ledger
separately from actual provider-reported cost.

Do not increase limits mid-campaign. Evaluate limit-triggered failures at the
end; a changed-limit rerun is a new campaign.

Before freezing the campaign, reconcile the exact suppression locations and
Semgrep exceptions in
[lint and Semgrep hygiene](lint-and-semgrep-hygiene.md) with the final harness.
Moved Ruff suppression lines require updated exact inventory locations even
when no suppression was added. Complete source, specification and documentation
edits, then run this focused check before factory generation:

```bash
uv run pytest -q tests/test_quality_policy.py
```

Stop on failure and repair the inventory before freezing campaign artifacts.
Repeat the check after any further harness or policy edit. This avoids finding
stale inventory after container calibration; it does not replace the full
repository gate during readiness preparation.

Generate and check only through the factory after that check passes:

```bash
uv run python scripts/generate_agent_efficiency_campaign.py \
  --spec benchmarks/agent-efficiency/campaign-specs/<fresh-campaign-id>.json \
  --output-dir .artifacts/agent-efficiency/campaigns/<fresh-campaign-id>

uv run python scripts/generate_agent_efficiency_campaign.py \
  --check \
  --spec benchmarks/agent-efficiency/campaign-specs/<fresh-campaign-id>.json \
  --output-dir .artifacts/agent-efficiency/campaigns/<fresh-campaign-id>
```

The output directory must be absent for generation. Never hand-author or repair
`campaign.json` or `launch-plan.json`. Review their attempt count, task inventory,
paired schedule, hashes, provider and accounting before inference. Finalize all
source, spec and documentation changes before readiness: its identity includes
Git-visible validation inputs, including new untracked files.

### Check image admission before paid preparation

Use the same reference validator as preparation, authenticated preflight and
paid execution. This credential-free check admits only supported namespaces
with an exact SHA-256 digest. Reference admission does not replace offline
image qualification, fixture checks or a complete readiness receipt.

```bash
uv run python - '.artifacts/agent-efficiency/campaigns/<fresh-campaign-id>/campaign.json' <<'PY'
import json
import sys
from pathlib import Path
from scripts.run_agent_efficiency_phase6_pilot import validate_campaign_image_reference

manifest = json.loads(Path(sys.argv[1]).read_text())
validate_campaign_image_reference(manifest.get("runtime_image"))
print("Image reference admitted; complete readiness remains required")
PY
```

Campaign 016's local digest passed preparation before the former execution-only
registry-prefix restriction rejected its first launch. Its one-time operator
exception remains historical evidence. Fresh campaigns now use the common
reference validator and retain all digest, source, profile and readiness checks;
no historical receipts or campaign manifests are rewritten.

## 5. Authorize preparation, then run it once

First check that the selected canary dollar allowance is compatible with its
whole-session token guard and the actual proxy reservation policy. The proxy
reserves all remaining session tokens at the highest frozen token price plus
one response's input/output allowance before forwarding a request. A
2,500,000-token guard at $0.60 per million already reserves $1.50 before that
response reserve; it cannot admit a $0.25 canary. Resolve incompatible controls
with the operator before lengthy calibration, preserving main campaign
controls when choosing separate canary controls. Verify this with the real
`ProxySettings.local_token_cap_reason` calculation and a representative native
request size; replayed successful model events alone cannot prove admission.
A local reservation rejection is not provider throttling and does not prove
that a paid request occurred. Preserve its observations and classify upstream
contact before deciding how to continue.

Factory generation and offline checks are credential-free. Complete preparation
is not: its bounded real model canary consumes quota or credits. Authorize that
step explicitly, separately from the main campaign.

### Preparation prompt

```text
Prepare <fresh-campaign-id> through the complete machine-validated readiness
pipeline. Read AGENTS.md and docs/proces/campaign-creation-instructions-2026-10-03.md.
Use the versioned specification and factory artifacts under
.artifacts/agent-efficiency/campaigns/<fresh-campaign-id>/.
Use fresh execution root
.artifacts/agent-efficiency/executions/<fresh-execution-id>/.

I authorize the bounded readiness model canary through <provider>, using
<exact model> and <reasoning policy>, under the frozen preparation guards.
This authorization does not launch the main campaign.

Use the selected frozen image/source and these six fixture bindings:
<fixture-id=absolute-checkout, repeated for all fixtures>.
For subscription only: native executable <path> and managed login <path>.
For OpenRouter only: use the registered SOPS environment in scoped children.

Run host-only operations directly in the authorized host context. Use
scripts/launch_agent_efficiency_pilot.py --prepare; do not assemble an ad-hoc
runner or omit checks. Require default_tools_approval_mode="approve" for Codira
MCP and prove actual unattended model-requested calls in the isolated container.
Reject missing, failed, stale or mismatched controls before further model work.
Preserve failed checks, exact provider evidence where available, diagnostics,
protected-check traces, logs and exit status. Do not retry inference automatically.
Return the ready receipt, all check results, canary accounting and concrete
receipt-based launch command. Do not launch the main campaign.
```

### OpenRouter preparation command

```bash
uv run python scripts/launch_agent_efficiency_pilot.py \
  --prepare \
  --campaign-dir .artifacts/agent-efficiency/campaigns/<fresh-campaign-id> \
  --execution-root .artifacts/agent-efficiency/executions/<fresh-execution-id> \
  --runtime podman \
  --seed <factory-seed> \
  --fixture-source 'click-public=<absolute-frozen-checkout>' \
  --fixture-source 'picomatch-public=<absolute-frozen-checkout>' \
  --fixture-source 'codira-current-public=<absolute-frozen-checkout>' \
  --fixture-source 'python-service-synthetic=<absolute-frozen-checkout>' \
  --fixture-source 'typescript-workspace-synthetic=<absolute-frozen-checkout>' \
  --fixture-source 'go-service-synthetic=<absolute-frozen-checkout>'
```

Do not wrap the entire command in SOPS or export API credentials into the parent.
The launcher scopes authenticated admission and the canary to children using
`~/.config/personal-secrets/secrets/openrouter_codira_agent_efficiency_pilot.env`.
Confirm the registered environment exists without printing decrypted values.
The upstream key stays outside the agent container. No subscription bindings
are accepted and provider fallback is disabled.

For a separately funded preparation canary, add `--canary-key codira-tests`
and a positive `--canary-budget-usd <approved-allowance>` to the preparation
command. The tests key comes from the registered
`openrouter_codira_tests.env` environment and is used only by the canary child.
Its exact model/reasoning route and allowance are admitted independently.
Main campaign preflight, post-canary capacity checks and execution continue
using the pilot environment. These preparation bindings are frozen in the
receipt; launch does not accept replacement key or allowance arguments.

For a separately bounded token guard, also add
`--canary-max-total-tokens <approved-count>`. This changes only the canary's
derived manifest, proxy guard and received-usage validation; main campaign
tokens remain frozen in the factory manifest. The count must be at least the
output allowance and no greater than the campaign session guard, is bound in
the receipt and cannot be replaced at launch. At the campaign 016 ceilings,
200,000 canary tokens fit the separately approved $0.25 allowance; the main
2,500,000-token guard remains unchanged.

### Native Codex subscription preparation command

```bash
uv run python scripts/launch_agent_efficiency_pilot.py \
  --prepare \
  --campaign-dir .artifacts/agent-efficiency/campaigns/<fresh-campaign-id> \
  --execution-root .artifacts/agent-efficiency/executions/<fresh-execution-id> \
  --runtime podman \
  --seed <factory-seed> \
  --subscription-codex '<absolute-qualified-native-codex-executable>' \
  --subscription-auth-source '<existing-managed-login-path>' \
  --fixture-source 'click-public=<absolute-frozen-checkout>' \
  --fixture-source 'picomatch-public=<absolute-frozen-checkout>' \
  --fixture-source 'codira-current-public=<absolute-frozen-checkout>' \
  --fixture-source 'python-service-synthetic=<absolute-frozen-checkout>' \
  --fixture-source 'typescript-workspace-synthetic=<absolute-frozen-checkout>' \
  --fixture-source 'go-service-synthetic=<absolute-frozen-checkout>'
```

Use the actual qualified native executable, not a shell wrapper. Managed login
is mounted read-only, never copied into scratch or inspected for documentation.
Do not supply API credentials, invoke SOPS or fall back to OpenRouter. Native
quota buckets do not necessarily identify their model mapping; a quota snapshot
is not a reservation for all attempts.

### Mandatory readiness checks

| Check | Mechanical pass requirement |
| --- | --- |
| Host context | Runtime/tmux/Git access, writable rootless runtime context and short socket |
| Factory inputs | Frozen manifest/schedule/source/profile/fixture bindings |
| Image runtime | Installed serving product and analyzer identities match |
| Native tool dispatch | Actual shell/Git/uv/Codira CLI in both arms; assisted effective preapproval and native MCP calls |
| Fixture freshness | Edits and old cursors rejected; reindex yields fresh evidence |
| Rubric calibration | All 72 curated rubric cases reproduce |
| Complete patch pipeline | All 18 applied cases through preparation, snapshot, capture and composite oracle |
| Repository gate | Fresh index, successful full validation in retained tmux, log and exit file |
| Authenticated route | Exact model/reasoning and current quota, or authenticated OpenRouter model/price/context/key budget |
| Model-requested MCP | Real isolated model turn: successful nonempty index/status and task-context calls, shell marker and complete usage |
| Capacity after canary | Repeat quota/key-budget admission after consumption |

MCP registration, direct server calls and app-server calls alone do not satisfy
the model-requested check. Both configuration builders set
`default_tools_approval_mode = "approve"` for `[mcp_servers.codira]`.
Temporary mounts use mode `1777`; tool HOME/config/cache stay under
`/workspace/.benchmark`, separate from denied `/codex-state` credential state.

The full gate is run automatically in retained tmux. Wait at least four minutes
before its first status check, then poll no more often than once per minute.
Gate logs and terminal exit files live under `.artifacts/validation/repo-gates/`.
Preparation examines and reports the terminal result, preserves a digest and
summary in its readiness receipt, then removes successful gate files and the
completed session. Failed or unfinished gates retain their evidence for diagnosis.
Campaign evidence is retained independently. Do not run a second ad-hoc gate
merely to duplicate the one preparation already runs.

Only all passing checks produce `readiness-receipt.json`. It binds evidence
digests and validation/harness/product/executable/environment identities.
The authenticated observation has a four-hour validity window at launch or
resume. After four hours, follow the external-conditions refresh below; elapsed
time alone does not require full preparation or another paid canary. Any source
or control change still invalidates its qualification; finalize changes before
preparation. The launcher and generated child must both enforce admission.

### External-conditions refresh after four hours

Preserve the original readiness receipt and all qualification evidence. First
verify their digests and the unchanged source, harness, product, executable,
image, fixture, campaign-control and environment bindings. Then repeat only
the read-only authenticated preflight through the same selected provider,
model, reasoning policy and registered credential route. Do not request a
model completion or repeat the canary merely because the window elapsed.

Compare the new observations with the previous authenticated admission:

- OpenRouter: authenticated `/models/user` visibility for the exact model;
  mandatory reasoning and supported effort, tools, context/output limits,
  provider route and prices; key status and configured spending limits.
- Native subscription: the same managed login, selected model, reasoning and
  qualified transport; current quota windows and sufficient available quota.
- Both routes: capacity remains sufficient for the authorized remaining work.
  Expected balance/quota consumption or a normal quota-window reset is not
  itself a contract change; it must still pass current capacity admission.

Retain the sanitized observations, comparison, timestamp and terminal status
as a new immutable record under the existing execution root. Bind that record
to the original receipt digest and frozen campaign identity; do not overwrite
the receipt or change its `authenticated_at`. A successful comparison starts
a new four-hour external-admission window, preserving the original offline
qualification and model-canary evidence.

If the external contracts and configured limits are unchanged and capacity
passes, the campaign is good to launch or resume under its existing execution
authorization and remaining guards. Do not require a fresh execution root,
full repository gate or paid canary solely for expiry. If observations changed,
are unavailable or capacity fails, stop and report the difference; requalify
the affected boundary before execution. Changes to frozen experiment controls
require a fresh factory identity. Unfinished paid starts remain a separate
resume blocker even when the external comparison passes.

**Implementation status:** this is the operator-approved procedure. The current
`scripts/agent_efficiency/readiness.py` still enforces a fifteen-minute window
and does not consume an external-refresh record. Automated four-hour admission
and refresh require a launcher implementation change. This documentation does
not supply a working refresh CLI or implicitly authorize bypassing the current
verifier. Preserve active campaign execution and existing evidence when adding
that support.

OpenRouter canary accounting is separate from main attempts and records USD
estimates at frozen price ceilings, not an invoice. Native canary usage consumes
quota; dollar accounting is not applicable. Both retain complete native events,
diagnostics and exit status. OpenRouter additionally retains exact upstream
bodies and hashes. The model turn is limited to 120 seconds; the enclosing
OpenRouter authentication child has a 300-second guard.

## 6. Review the ready receipt and authorize the main campaign

```bash
jq '{schema_version,status,authenticated_at,created_at,checks}' \
  .artifacts/agent-efficiency/executions/<fresh-execution-id>/readiness-receipt.json

jq '{campaign_id,stage,provider,budgets,accounting,runtime_image}' \
  .artifacts/agent-efficiency/campaigns/<fresh-campaign-id>/campaign.json

jq '{campaign_id,scheduled_attempt_count,repetitions,seed}' \
  .artifacts/agent-efficiency/campaigns/<fresh-campaign-id>/launch-plan.json
```

Inspect the private receipt locally; do not copy local credential/source paths
or raw provider text into a public report. The main execution authorization
must name the concrete model, campaign/execution identities, attempt count,
guards and USD pool or native quota route. Launch within the four-hour window
or complete the external-conditions refresh after expiry; an approval delay
alone does not require another paid canary.

### OpenRouter launch prompt

```text
Launch <fresh-campaign-id> from its factory artifacts and prepared execution
root .artifacts/agent-efficiency/executions/<fresh-execution-id>/.
Read AGENTS.md and docs/proces/campaign-creation-instructions-2026-10-03.md.

I authorize its <48 times repetitions> attempts through OpenRouter using
<exact model ID>, <reasoning policy>, the frozen guards and <USD pool>.
Use only the registered scoped SOPS credentials and disable provider fallback.

Verify the complete readiness receipt, freshness, source/image/harness/fixture
fingerprints, successful full gate, 72 rubric and 18 applied patch calibrations,
actual model-requested MCP qualification and post-canary key-budget admission.
Report any mismatch before execution. Preserve all frozen controls.
Launch only through scripts/launch_agent_efficiency_pilot.py in durable tmux.
Preserve raw responses, native events, diagnostics, protected-check traces,
logs and exit status. Report preparation and campaign USD accounting separately.
Preserve completed attempts and investigate unfinished starts before resuming.
Provide progress and a dated task-by-task and paired report under docs/process;
separate operational outcomes, deterministic correctness and blinded semantic
adjudication. Do not launch any other campaign.
```

### Native subscription launch prompt

```text
Launch <fresh-campaign-id> from its factory artifacts and prepared execution
root .artifacts/agent-efficiency/executions/<fresh-execution-id>/.
Read AGENTS.md and docs/proces/campaign-creation-instructions-2026-10-03.md.

I authorize its <48 times repetitions> attempts through my existing managed
ChatGPT Codex subscription login using <native model> at <reasoning policy>.
Use the frozen guards. Dollar accounting is not applicable.

Verify the complete readiness receipt, freshness, source/image/harness/fixture
fingerprints, successful full gate, 72 rubric and 18 applied patch calibrations,
actual model-requested MCP qualification and post-canary quota admission.
Report any mismatch before execution. Preserve all frozen controls.
Use subscription authentication exclusively, without API credentials or
OpenRouter fallback. Launch only through scripts/launch_agent_efficiency_pilot.py
in durable tmux with the receipt-bound native executable and managed login.
Preserve complete native events, diagnostics, protected-check traces, logs and
exit status. Report preparation and campaign token/quota usage separately.
Preserve completed attempts and investigate unfinished starts before resuming.
Provide progress and a dated task-by-task and paired report under docs/process;
separate operational outcomes, deterministic correctness and blinded semantic
adjudication. Do not launch any other campaign.
```

Both routes use the same receipt-only command, with no replacement bindings:

```bash
uv run python scripts/launch_agent_efficiency_pilot.py \
  --launch \
  --execution-root .artifacts/agent-efficiency/executions/<fresh-execution-id>
```

Do not add model, seed, fixture or credential arguments to receipt-based launch.
Do not invoke the internal runner directly or use an ad-hoc `codex exec` command.

## 7. Monitor, retain evidence and handle interruption

Use the actual session name returned by the launcher:

```bash
tmux list-panes -t '<returned-session-name>' \
  -F '#{pane_dead} #{pane_dead_status}'
tmux capture-pane -pt '<returned-session-name>' -S -40
tail -n 40 .artifacts/agent-efficiency/executions/<fresh-execution-id>/logs/pilot.log
cat .artifacts/agent-efficiency/executions/<fresh-execution-id>/pilot.exit
```

The exit file does not exist while the invocation is running. A dead pane or
exit zero is an operational observation, not proof that all attempts completed
or tasks were correct. Inspect `state/campaign-state.json`, `state/records/` and
provider/quota/checkpoint state. Retain completed tmux panes with
`remain-on-exit`, logs, status files and raw evidence; do not kill them as cleanup.

OpenRouter unfinished budget starts live under `state/budget/`; native starts
live under `state/subscription-starts/`. Compare them with settlements/result
records. An unfinished start can imply uncertain paid usage even when no answer
was captured. Investigate before any resumption; never delete start files,
invent settlements, reset a campaign or rerun completed slots.

If all resume conditions, authorization and readiness freshness still hold:

```bash
uv run python scripts/launch_agent_efficiency_pilot.py \
  --resume \
  --execution-root .artifacts/agent-efficiency/executions/<existing-execution-id>
```

For resume after the four-hour window, repeat only the external-conditions
refresh above when local qualification bindings are unchanged. Preserve all
completed records and investigate unfinished starts independently. A passing
external comparison permits resume under existing authorization; it does not
settle unknown billing or authorize rerunning completed attempts.

**Current implementation limitation:** the launcher still requires the original
receipt to pass its fifteen-minute age check and has no supported refresh
command. Implement the approved four-hour/refresh policy before relying on it
for automated resume. Do not extend original timestamps, overwrite evidence
or migrate records to another root to hide this limitation.

### Investigation and resume prompt

```text
Investigate the stopped campaign <id> in execution root <path> without making
model calls or changing evidence. Read its immutable plan, native/provider
events, quota or USD ledger, starts, settlements, records, logs and exit status.
Explain operational failure separately from task correctness. Identify every
unfinished start and any uncertain billing. Preserve all completed attempts.
Check local readiness bindings and whether the four-hour external-admission
window has expired. If expired, perform only the read-only authenticated
external-conditions comparison and retain new immutable refresh evidence.
If conditions are unchanged and capacity passes, recommend resume under the
existing controls without another paid canary. Report any current launcher
implementation blocker explicitly; do not edit original receipts or start a
replacement campaign automatically.
Return an evidence-backed resume recommendation for operator authorization.
```

## 8. Produce task-by-task and paired analysis

Persist dated public-safe analysis under `docs/process/`. Keep raw evidence in
the ignored artifact roots. Report:

- Expected slots, started/completed slots, provider/runner failures and canary
  usage; distinguish token/request/time guard stops from provider throttling.
- Deterministic patch/oracle results, including failed protected checks and
  their decisive traces.
- Pending or completed blinded semantic adjudication. Calibration is not
  automatic correctness adjudication of campaign answers.
- Baseline versus assisted results paired by task and repetition; unmatched
  attempts, successful/failed/denied/unattempted MCP calls and diagnostic tasks.
- Tokens, duration and OpenRouter ceiling-priced USD estimates, or native quota
  usage with dollars not applicable. Do not treat estimated prices as invoices.
- Limits that affected otherwise productive tasks and whether a fresh campaign
  with higher runaway guards is justified.
- Changed harness/source/fixture controls relative to historical campaigns.
  Such comparisons are not pure model-only experiments.

For a failed native turn, inspect the retained provider response observations
and exact received bodies before reporting token or dollar usage. The current
normalizer can leave zero usage with `usage_complete=false` when `turn.failed`
has no final native usage event. Those zeros represent missing native terminal
accounting, not zero paid usage. Reconstruct provider totals only from complete,
hash-verified received responses; retain their distinct provenance and leave
the immutable result untouched. If response usage is missing or uncertain,
report that uncertainty rather than inventing totals or settlements.

Report these OpenRouter amounts separately: provider-reported response cost
when present, the campaign settlement computed at frozen price ceilings, and
the preparation canary allowance/usage. Cached input and reasoning output are
subsets of their corresponding token totals; do not add them twice. The
conservative ledger need not equal provider-reported cost, and neither is an
invoice. A failed task can still have a complete, reconcilable provider ledger.

For deterministic report artifacts, use the existing reporter after recovering
the exact runner configuration from prepared inputs. This wrapper supplies
every task and the frozen repetition count rather than a guessed subset:

```bash
uv run python - '<execution-root>' '<fresh-report-output-directory>' <<'PY'
import json
import sys
from pathlib import Path
from scripts.launch_agent_efficiency_pilot import load_prepared_inputs
from scripts.report_agent_efficiency_benchmark import main

launch = load_prepared_inputs(Path(sys.argv[1]))
output = Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=False)
configuration = {
    "manifest": launch.manifest,
    "image": launch.manifest["runtime_image"],
    "runtime": launch.runtime,
    "seed": launch.seed,
    "launch_plan": launch.plan,
}
configuration_path = output / "configuration.json"
with configuration_path.open("x") as handle:
    json.dump(configuration, handle, indent=2, sort_keys=True)
arguments = [
    "--state-root", str(launch.execution_root / "state"),
    "--output-dir", str(output / "generated"),
    "--campaign-id", str(launch.manifest["campaign_id"]),
    "--seed", str(launch.seed),
    "--repetitions", str(launch.plan["repetitions"]),
    "--configuration-json", str(configuration_path),
]
for task_id in sorted(launch.manifest["task_fingerprints"]):
    arguments.extend(["--task-id", task_id])
raise SystemExit(main(arguments))
PY
```

Use a durable output such as
`.artifacts/agent-efficiency/reports/<fresh-report-id>/`. Reporting does not
require a fresh readiness receipt or perform authentication/inference; changed
factory/harness inputs can nevertheless prevent prepared-input re-admission.
Preserve the frozen source needed to read historical records. If the generic
reporter rejects a route or record contract, retain the rejection and analyze
validated evidence explicitly; do not modify historical records to make it fit.
The generated report does not replace detailed failure review or blinded
semantic adjudication, and native zero USD sentinels must be explained as N/A.

### Analysis prompt

```text
Analyze campaign <id> from factory artifacts <path> and execution evidence <path>.
Do not make model calls, alter records or resume work.
First summarize completion and compare the paired baseline/Codira-MCP arms.
Then provide task-by-task results and detailed failure causes with evidence.
Separate provider/runner outcomes, deterministic correctness and blinded
semantic adjudication; leave unadjudicated semantics explicitly pending.
Account for canaries separately, report OpenRouter USD estimates and uncertainty
or native token/quota usage with dollars not applicable. Identify guard stops
and recommend any changed-limit rerun only as a fresh proposed campaign.
Persist the dated report under docs/process and preserve all raw evidence.
```

## 9. Apply the campaign 012–016 lessons before another paid run

Use the preceding steps as the operative commands. This checklist records
what the failures established and what their successful checks did not prove.

| Boundary | Lesson and required action |
| --- | --- |
| Native sandbox | Match the app-server shell policy to the real provider transport; host execution alone does not fix a nested Bubblewrap namespace. Retain shell diagnostics and verify both arms before inference. |
| Model route | Use exact authenticated model/reasoning admission and current price bounds. A public catalog, a remembered price or a reasoning label from another model does not establish the key-visible contract. |
| MCP first page | Omit cursor or send null on the first call. Copy only an exact returned page.next_cursor for continuation; profiles must use supported enum names. Publish this guidance in actual list-tools schemas and actionable rejection messages. |
| Canary tool failures | Use explicit first-page arguments and sequential index_status then context_for_task. Reject any tool failure even if later calls succeed; do not silently admit a retry loop. |
| Argument preservation | Check nullable and omitted fields plus tool schemas offline through the provider mapper. Compare digest-verified raw JSON/SSE function-call arguments with native MCP dispatch, accounting for parallel ordering. This tests the local path, not transformations inside the provider. |
| Canary reservation | Test the real proxy's reservation rule before inference. The 2.5m-token reservation could not fit $0.25; the separately approved 200,000-token guard could. Keep tests-key canary accounting separate from main-key admission and execution. |
| Serving identity | Check fresh-process runtime fingerprints after validation. A clean Git tree can conceal a rewritten ignored `_version.py`; wheel tests must build disposable source copies. |
| Quality policy | Update exact suppression-line inventory after moving code and run `tests/test_quality_policy.py` before freezing inputs. Passing selected tests does not establish the full gate. |
| Image admission | Validate the digest-pinned reference before preparation and authenticated preflight, then qualify the exact image and bind it in readiness. Fresh campaigns admit supported local and registry references through the same validator used at execution. |
| Admission age | Preserve the approved four-hour/unchanged-external-conditions policy and its implementation-status distinction above. The current verifier still has a fifteen-minute block; documenting a policy does not implement its CLI. |
| Offline fixture tests | Prepare user-level baked model settings for temporary library repositories in both arms. Qualify those tests with the actual isolated HOME, cache, network and image; the host gate can conceal missing models. |
| Sample indexing | Put temporary smoke repositories outside excluded paths and require a nonempty query result. A successful zero-file index does not qualify library behavior. |
| Request limits | Inspect local versus upstream response observations. In campaign 016, 45 upstream HTTP 200 completions were followed by one local 429 on request 46; this was logical-continuation exhaustion, not provider throttling or exhaustion of three transport retries. |
| Budget semantics | In full-campaign `shared-pool` mode, session tokens and per-attempt USD are planning figures. The output/request/time controls and observed USD pool are execution stops; describe and approve those semantics before launch. |
| Failed-turn accounting | Missing native final usage can coexist with complete upstream usage and a valid settlement. Reconcile both sources and distinguish provider-reported cost from ceiling-priced pool charges. |
| Campaign stopping | Operational failure halts the full campaign even when money remains. A matching settlement resolves that attempt's ledger; it does not permit automatic resume past a terminal failure. |
| Scientific interpretation | One failed assisted attempt and no completed baseline pair establish no model ranking or Codira efficiency claim. Evaluate task control and environment separately before deciding what to change. |

### Diagnose request exhaustion before increasing the cap

Read the task's requested deliverable and the completed tool trajectory. Count
invalid tool arguments, repeated or overlapping source reads, failed commands,
successful MCP evidence, time spent on environment setup, and whether the
answer file exists. Cursor arguments must follow the tool contract: omit an
unused cursor or pass JSON null; an empty string is rejected.

Campaign 016's first task asked for an impact assessment and relevant tests,
then an answer file. The complete eleven direct callers were available by
request 4. The model executed 35 shell commands before its selected tests at
request 30, and fifteen more afterward. Two selected tests tried to download
an absent default embedding model in the network-isolated environment. The
model continued investigating, reread overlapping source ranges, and did not
write the answer before the request guard stopped it. Identifying relevant
tests did not require making every test pass before reporting the assessment.

This supports weak scoping, prioritization and stopping on that attempt as a
possible model limitation. It does not prove general model inadequacy or that
a larger request allowance would produce a correct answer. The environment
detour is independently evidenced, and much exploration preceded it. Separate
those observations from causal inference. Readiness's successful model canary
proves tool and usage compatibility, not competence on the full task panel.

Correct and qualify environmental gaps first. To assess model adequacy, use a
small matched task comparison with the same prompt, image, assistance,
reasoning and request controls, changing only the model. Compare deliverable
completion and correctness as well as exploration and cost. Treat a cap or
instruction change as a separate approved experiment, with a fresh factory
identity; do not raise limits in a historical campaign or repeatedly pay for
an unchanged failed slot.

### Preserve exceptions and distinguish admission from execution

Campaign 016 started only after the operator explicitly authorized narrow
age and exact-image registry-prefix exceptions under the former admission rule. Those per-execution records
and wrappers are historical evidence, not a supported reusable launcher flag
or standing permission for later campaigns. Preserve original receipts,
timestamps, image digests, frozen controls and every other verification. Any
separately authorized exception must record its exact scope, authorization,
affected receipt/image hashes and invocation; never conceal it by rewriting
readiness evidence. Prefer implementing the approved admission policy and
qualifying it before another campaign needs such an exception.

The first invocation exited 2 on image admission with an empty state directory
and no paid start. That clean admission stop was independently verified before
the authorized relaunch; its original log and exit file were retained under a
separate invocation. Later, the first paid attempt had one matching start and
settlement and an operational failure. These states require different handling:
an empty pre-provider admission failure does not establish uncertain billing,
while a paid failure must be reconciled and remains a terminal-resume blocker.
Report both explicitly. Do not equate a successful launcher return or a live
tmux pane with successful task execution.

The forensic record for `glm016-20261004-r1` remains in its ignored execution
root; the reconciled analysis is under
`.artifacts/agent-efficiency/reports/campaign-016-failure-analysis-20261004-r1/`.
Its 45 verified provider bodies contain 3,435,330 total tokens, including
3,197,888 cached input tokens and 4,090 reasoning output tokens. Provider-reported
cost sums to $0.1250259408; its conservative pool settlement is $0.55353624.
These figures exclude preparation canaries. No task answer or completed pair
was available for correctness or efficiency evaluation.

## Completion criteria

A campaign is prepared only when the complete machine-validated receipt exists;
it is launched only after concrete execution authorization; it is operationally
complete only when the frozen slots and terminal state establish that outcome.
Correctness and semantic completion require their own evidence and review.
Never convert a partially successful setup, visible model, running tmux pane or
zero process exit into an efficacy claim.
