# Mechanical campaign readiness — 2026-10-02

OpenRouter support and its verification are documented in
[OpenRouter campaign readiness](agent-efficiency-openrouter-readiness-2026-10-03.md).

`launch_agent_efficiency_pilot.py --prepare` now runs preparation in one pass.
It resolves the factory campaign, schedule, fixture checkouts, native executable,
managed-login path, interpreter and runtime once. It writes an immutable
`readiness-receipt.json` only after the following required checks pass:

| Check | Required evidence |
| --- | --- |
| Host context | Writable rootless runtime directory, short Unix socket, runtime and tmux access |
| Factory inputs | Validated immutable manifest, schedule, profile and fixture revisions/trees |
| Image runtime | Installed product and analyzer source fingerprints, profile and active analyzers |
| Native tool dispatch | Both arms: writable tool home, denied credential state, shell/Git/uv/Codira CLI; assisted: effective preapproval and real native MCP calls |
| Fixture freshness | Source edits and old cursors rejected, reindex returns fresh source evidence |
| Rubric calibration | All 72 source-curated calibration cases reproduce |
| Complete patch pipeline | All 18 correct/incomplete/wrong cases use offline environment preparation, shared snapshot, actual workspace capture and complete composite oracle |
| Repository gate | Fresh index and successful full `validate_repo.py` in retained tmux with log and terminal exit file |
| Authenticated route | Native: exact model, reasoning and quota through the isolated subscription container. OpenRouter: authenticated `/models/user`, price/context/tool contracts and scoped key budget |
| Model-requested MCP | A bounded real turn from `codex exec`, through the actual selected transport, must call both canary MCP tools successfully and complete its shell marker; complete events, diagnostics, usage and exit status are retained |
| Capacity after canary | Repeat authenticated admission after the canary; retain native quota windows or OpenRouter key budget |

Every evidence file is bound by digest. The receipt also binds repository validation
inputs, harness, installed product, interpreter and executable digests, factory and
fixture bindings, UID, and the child launch environment. Launch rechecks all of
these; the generated runner repeats admission before credential access. Changed
inputs, failed/missing checks, altered evidence and missing receipts reject execution.
The operator procedure gives authenticated observations a four-hour admission
window. After expiry, repeat only the read-only external-conditions comparison;
unchanged contracts and sufficient capacity permit execution without repeating
offline qualification or the paid canary. Retain new immutable refresh evidence
linked to the original receipt, preserving its timestamp. See the
[external-conditions refresh procedure](campaign-creation-instructions-2026-10-03.md#external-conditions-refresh-after-four-hours).
The execution route also repeats authenticated preflight before model work and
quota checks per attempt. The current verifier still implements fifteen minutes
and does not yet support the approved four-hour/refresh policy.

Preparation stops at the first failure, records its check identity and error class,
and retains diagnostics. It never retries automatically or upgrades a partial pass
to readiness. A failed preparation requires a fresh execution root; expiry
alone requires only the external refresh described above. Changed
experiment/harness controls require a fresh factory campaign identity.
The native subscription and OpenRouter routes support the representative panel.
Other providers and task inventories reject preparation. There is no exemption for unqualified
inventories. Historical launch receipts alone cannot admit execution.

Run preparation from the authorized host context. Container runtime and tmux access
are host operations; the assistant should request host execution directly rather
than first trying them in its outer sandbox. Preparation checks the context before
runtime qualification or authentication. Offline tool probes run without credentials or model turns. After the full gate
and authenticated admission pass, preparation requires one real model
canary with a maximum 120-second timeout and the frozen token guard. It consumes
subscription quota or OpenRouter credits, records preparation usage separately,
and is never retried automatically.
Inputs are rechecked before every boundary, including before this model turn. Native subscription preflight uses the existing managed ChatGPT login;
no API key, SOPS provider environment or OpenRouter fallback is used on that route.

OpenRouter preparation starts without provider credentials in the parent. Both
read-only authenticated admission and the model canary use the registered SOPS
environment in scoped children. The canary rechecks the prepared bindings and
source identity, repeats authenticated admission, and uses the same proxy and
container executor as campaign attempts. Only a generated local proxy token
enters the isolated container; the upstream API key remains outside it. No
subscription login is accepted and provider fallback remains disabled.
Exact upstream response bodies and digests are retained before interpretation,
along with request/response observations and complete native process evidence.
Missing provider usage, unsuccessful responses, local guard rejections, denied
tools or missing native usage reject readiness. `accounting.json` records tokens
and USD estimates at frozen price ceilings, explicitly separate from actual
invoiced charges and the campaign's attempt ledger. The model turn is bounded to
120 seconds; its enclosing authentication child has a 300-second guard. The
post-canary key-budget check must still admit the entire campaign pool.

Both native and proxy configuration builders set
`default_tools_approval_mode = "approve"` on `[mcp_servers.codira]`. The native
probe reads effective configuration and calls `index_status` and `context_for_task`
through the native app-server handler. It requires a usable ready index and actual
canary evidence. These offline checks exercise native dispatch without consuming inference quota.
They cannot replace the mandatory model-requested MCP canary. That separate check
requires completed successful calls from the real `codex exec` event stream; tool
registration, direct server calls and direct app-server RPC calls alone cannot
admit a campaign.

Temporary mounts explicitly use mode `1777`. Tool HOME/config/cache are under
`/workspace/.benchmark`; credentials remain denied under `/codex-state`. Both
arms receive the same prepared CLI profile. Snapshot and capture share exclusions
for installed dependencies and tool state; new source/test files remain captured,
and source symlinks still reject capture. Captured patch text reaches the complete
quality rubric, preserving behavioral results and pending blinded semantic review.
MCP authorization denial is an operational infrastructure failure, even when
tool use is optional. Expected tool-level rejections, such as stale-source checks,
remain task evidence and do not become infrastructure failures.

Use factory-generated artifacts and supply every frozen fixture binding on the
single preparation command. The native route additionally requires the prepared
`--subscription-codex` executable and `--subscription-auth-source` login path:

```bash
uv run python scripts/launch_agent_efficiency_pilot.py \
  --prepare \
  --campaign-dir .artifacts/agent-efficiency/campaigns/<fresh-campaign-id> \
  --execution-root .artifacts/agent-efficiency/executions/<fresh-execution-id> \
  --seed <factory-seed> \
  --subscription-codex <qualified-native-executable> \
  --subscription-auth-source <existing-managed-login-path> \
  --fixture-source <fixture-id>=<absolute-frozen-checkout>
```

Repeat `--fixture-source` for every manifest fixture. No paths or controls are
re-entered at launch:

For OpenRouter use the same preparation command without either
`--subscription-*` argument. Do not wrap the whole preparation pipeline in
SOPS; the pipeline scopes credentials only to its authenticated children.

```bash
uv run python scripts/launch_agent_efficiency_pilot.py \
  --launch \
  --execution-root .artifacts/agent-efficiency/executions/<fresh-execution-id>
```

Launch remains a separately authorized execution stage. Resume enforces readiness
and existing unfinished-start investigation rules. Completed attempts and previous
invocation logs are retained. Gate and campaign tmux panes use `remain-on-exit` and
are retained with their logs and separately written exit statuses.

Implementation verification and raw offline evidence are recorded under
`.artifacts/agent-efficiency/readiness-qualification-20261002-r2/`.
Campaign 011 factory, execution and attempt evidence is unchanged. No new campaign or subscription model canary was executed in this implementation
verification. Offline native dispatch, the 72 rubrics and 18 complete patch cases
were exercised live; the model-canary admission logic was checked with recorded
native event fixtures. A real readiness receipt requires the model canary against
a fresh source-compatible factory campaign and image.
