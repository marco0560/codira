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

Record the runtime-profile fingerprint separately from the environment-image
profile fingerprint:

```bash
uv run python -c 'from scripts.run_agent_efficiency_phase6_pilot import runtime_profile_fingerprint; print(runtime_profile_fingerprint())'
```

The image qualification later verifies installed source/analyzer identities,
profile and active analyzers. A successful build alone is not readiness.

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
Do not increase limits mid-campaign. Evaluate limit-triggered failures at the
end; a changed-limit rerun is a new campaign.

Generate and check only through the factory:

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

## 5. Authorize preparation, then run it once

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

The full gate is run automatically in retained tmux. Wait at least three minutes
before its first status check, then poll no more often than once per minute.
Preparation preserves the gate session, log and terminal exit file. Do not run a
second ad-hoc gate merely to duplicate the one preparation already runs.

Only all passing checks produce `readiness-receipt.json`. It binds evidence
digests and validation/harness/product/executable/environment identities.
The final authenticated observation must be no older than fifteen minutes at
launch. The launcher and generated child both verify admission. Any source or
control change invalidates the receipt; finalize changes before preparation.

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
guards and USD pool or native quota route. Be ready to launch promptly after
preparation; approval delays do not make a stale receipt valid.

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

**Current limitation:** resume also requires the original readiness receipt to
be fresh. A long run or six-hour checkpoint will ordinarily outlive its
fifteen-minute admission window. There is currently no supported receipt
refresh-in-place command; `--prepare` requires a fresh execution root. Do not
extend timestamps, overwrite evidence or move completed records into a new
root to bypass this boundary. Preserve the interrupted run, report the blocker
and obtain a supported requalification/completion workflow before more work.
Fresh preparation alone does not migrate or authorize its unfinished attempts.

### Investigation and resume prompt

```text
Investigate the stopped campaign <id> in execution root <path> without making
model calls or changing evidence. Read its immutable plan, native/provider
events, quota or USD ledger, starts, settlements, records, logs and exit status.
Explain operational failure separately from task correctness. Identify every
unfinished start and any uncertain billing. Preserve all completed attempts.
Check whether readiness freshness and the current launcher permit resume.
If they do not, describe the concrete supported remediation needed; do not
edit receipts, weaken admission or start a replacement campaign automatically.
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

## Completion criteria

A campaign is prepared only when the complete machine-validated receipt exists;
it is launched only after concrete execution authorization; it is operationally
complete only when the frozen slots and terminal state establish that outcome.
Correctness and semantic completion require their own evidence and review.
Never convert a partially successful setup, visible model, running tmux pane or
zero process exit into an efficacy claim.
