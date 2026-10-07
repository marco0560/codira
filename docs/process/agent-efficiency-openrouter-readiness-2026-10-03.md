# OpenRouter campaign readiness — 2026-10-03

The representative campaign preparation pipeline supports both OpenRouter and
native Codex subscription execution. OpenRouter no longer rejects preparation
solely because it uses the proxy route. All eleven readiness checks remain
mandatory; neither provider has a reduced checklist or launch exemption.

## Authentication and actual model dispatch

The preceding credential-free native tool check explicitly matches the
OpenRouter attempt's inner `dangerFullAccess` policy for `command/exec`.
Otherwise the configuration's inherited workspace sandbox tries a nested
Bubblewrap UID map that the measured container prohibits. The container's
outer isolation remains unchanged, and native subscription permission profiles
remain separate. See the
[procedure's native tool qualification step](campaign-creation-instructions-2026-10-03.md#qualify-native-tools-with-the-measured-transport-policy)
for required evidence, failure diagnosis and regression coverage.

The parent preparation process does not require API credentials. It invokes
the registered OpenRouter SOPS environment only for authenticated children.
Preparation may select `--canary-key codira-tests` together with a positive
`--canary-budget-usd` allowance. This binds the registered tests environment
only to the model-canary child; campaign preflight, post-canary campaign
capacity admission and main execution retain the pilot environment. Both
controls are frozen in the preparation receipt and cannot be replaced at
receipt-based launch. Subscription preparation rejects these dollar/key
overrides. The tests key is never exported into the parent or combined with
the campaign key.
Preparation may additionally bind `--canary-max-total-tokens` to a separately
approved token guard that fits the canary dollar reservation. It is applied to
canary admission, proxy enforcement and received usage without altering the
factory's main token guard, and is rejected for native subscription preparation.
The model-canary child reloads the prepared launch and rejects changed source,
factory or execution bindings before authentication or inference. It repeats
authenticated model/context/price/key-budget admission before its model turn.

The canary uses the same provider executor, proxy, model catalog and isolated
container as campaign attempts, with an already indexed synthetic workspace.
It preserves the frozen model, reasoning, output allowance, request/transport
guards, context and price ceilings, and token guard. The model turn has a
120-second maximum; its enclosing authentication child has a 300-second guard.
The canary also applies the declared attempt and campaign USD ceilings.
When a separate canary allowance is selected, its derived admission and proxy
use that allowance for both dollar guards without changing the campaign
manifest or pool. The received usage must remain within the canary allowance;
crossing it rejects readiness and retains the complete evidence.
Only the local proxy token enters the container; the upstream credential stays
in the host proxy. Subscription login bindings reject this route. Provider
fallback remains disabled and Codira MCP remains explicitly preapproved.

Readiness requires model-requested successful `index_status` and
`context_for_task` calls, a completed shell marker and complete native usage.
It additionally requires successful upstream response evidence and complete
provider token accounting. Missing usage, provider errors, denied or empty
tool results, local guard rejections and changed inputs prevent admission.
There is no automatic retry.

Exact upstream bodies and digests, request/response observations, native events,
diagnostics and terminal exit status remain in the durable readiness directory,
including on failed canaries. `accounting.json` records provider tokens and USD
estimates at the frozen price ceilings, separately from the main campaign's
attempt ledger. These estimates are not actual invoiced charges. A final
authenticated key-budget check must still admit the entire campaign pool after
the canary. Both launcher and runner enforce the resulting readiness receipt.

## Operator procedure

Generate a fresh factory campaign from a versioned spec using the selected
source, model and qualified image. Existing campaign identities are immutable;
the changed harness requires fresh factory artifacts. Run the documented
single preparation command from the authorized host context, supplying every
fixture binding, without either subscription argument:

```bash
uv run python scripts/launch_agent_efficiency_pilot.py \
  --prepare \
  --campaign-dir .artifacts/agent-efficiency/campaigns/<fresh-campaign-id> \
  --execution-root .artifacts/agent-efficiency/executions/<fresh-execution-id> \
  --seed <factory-seed> \
  --fixture-source <fixture-id>=<absolute-frozen-checkout>
```

Repeat `--fixture-source` for every manifest fixture. Do not wrap the entire
pipeline in SOPS. After successful preparation and separate authorization of
the campaign execution, use the receipt-only launch command. The approved
external-admission window is four hours. After expiry, unchanged local bindings
require only a read-only authenticated external-conditions check: unchanged
contracts and sufficient key capacity permit execution without another paid
canary or full preparation. Preserve the original receipt and retain a new
immutable refresh record. Failed preparation still requires a fresh execution
root; changed campaign controls require a fresh factory identity.

The current verifier still enforces fifteen minutes and has no automated refresh
support. See the [procedure and implementation status](campaign-creation-instructions-2026-10-03.md#external-conditions-refresh-after-four-hours)
before relying on the new policy through the launcher.

See [mechanical readiness](agent-efficiency-readiness-2026-10-02.md) for the
complete check inventory, retained tmux requirements and launch command.

## Implementation verification

The focused readiness suite passed all 35 tests. It exercises native and
OpenRouter model-event fixtures, the real local proxy settings and response
artifact writer, failed/empty/denied tools, absent native/provider usage,
provider errors, SOPS child scoping and changed-binding rejection before model
work. Provider network responses and model events were simulated; these tests
do not qualify any particular live model.

The final full repository gate exited zero: 1,262 passed, 3 skipped, 85% coverage,
no blocking Semgrep findings. Its retained tmux session is
`codira-openrouter-readiness-validation-20261003-r2`. Logs and terminal status
are under `.artifacts/agent-efficiency/readiness-openrouter-qualification-20261003/`
as `validation-r2.log` and `validation-r2.exit`. The first gate caught a missing
lint-suppression inventory entry; its failed record and session are retained.
The inventory was corrected before the successful final gate.

No paid model call, campaign execution or campaign readiness receipt was
produced during implementation verification. The 72 rubric and 18 applied
patch calibration checks remain mandatory in actual campaign preparation;
they were not rerun as live container qualifications in this implementation
turn. Campaign 010 and 011 artifacts and completed attempts were preserved.
