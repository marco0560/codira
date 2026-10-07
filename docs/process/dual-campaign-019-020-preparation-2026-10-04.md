# Campaigns 019 and 020 — parallel execution handoff

Factory manifests and readiness receipts are the authoritative execution state.
Both campaigns retain campaign 016's tasks, fixtures, treatment, image, seed
and resource controls. They include the corrected offline temporary-repository
configuration and common local-image admission. Historical 016 evidence remains
immutable; its harness differs from these two fresh campaigns.

| Control | Campaign 019 | Campaign 020 |
| --- | --- | --- |
| Route | OpenRouter Responses | OpenRouter Responses |
| Model | `stealth/space-bunny-alpha` | `openai/gpt-6-luna` |
| Reasoning | `max` (mandatory reasoning) | `high` |
| Input/output ceilings, USD per million | 0.16 / 0.60 | 0.25 / 0.75 |
| Attempts | 144 | 144 |
| Schedule | 24 tasks, two arms, three repetitions, seed 261004 | Same |
| Session token planning | 2,500,000 | Same |
| Output per response | 64,000 | Same |
| Logical requests / transport attempts | 45 / 3 | Same |
| Attempt timeout | 1,800 seconds | Same |
| Campaign pool / daily ceiling / attempt estimate, USD | 7 / 8 / 1.75 | Same |
| Canary key / allowance / token guard | codira-tests / 0.25 USD / 200,000 | Same |

The scoped authenticated catalog admits both routes and their exact reasoning
policies. Space Bunny reports zero input/output price; positive frozen ceilings
are required by the current proxy/factory. Its conservative ledger can therefore
exhaust the campaign pool despite zero provider cost. Luna ceilings cover the
long-context prompt, output and cache-write tiers as well as the base price. Provider-reported cost and the
ceiling-priced ledger must be reported separately.

Each execution root owns its state, proxy, attempts, journal and process lock.
The shared-pool lock applies within a campaign, not across both campaigns.
The two $7 ledgers are independent; the harness does not enforce a joint $8
daily ledger. Both use the registered main pilot key after readiness; canaries
use only the separately scoped tests key. Retain the provider key's aggregate
limit and recheck its capacity before both launches. A price change requires
fresh admission; zero price is not permission to remove guards or use a fallback.

Running simultaneously shares host CPU, memory and provider capacity. Record
overlap in analysis and do not treat durations as isolated performance results.

The final preparation and selection findings are in
[the dual-campaign selection outcome](agent-efficiency-dual-campaign-selection-outcome-2026-10-04.md).

## Earlier admission failures

Campaigns 017 and 018 passed the offline checks and repository gates but stopped
before any canary. The parser rejected valid zero prices, and Luna admission
correctly included a $0.25/M long-context cache-write price omitted from the
initial $0.20/M input ceiling. Fresh campaigns 019 and 020 bind the corrected
parser and approved $0.25/M Luna ceiling. Keep the old specs, factory outputs,
execution evidence and gate records unchanged; no paid attempt started there.

## Preparation

The operator authorized both model canaries at the bounds above on 2026-10-04.
This does not authorize launching either main campaign. Preparation must finish
with a complete passing readiness receipt; a live session or factory generation
is not readiness. Use the current procedure and retain failure evidence.

Campaign 019:

```bash
uv run python scripts/launch_agent_efficiency_pilot.py --prepare --campaign-dir .artifacts/agent-efficiency/campaigns/codira-efficacy-campaign-019 --execution-root .artifacts/agent-efficiency/executions/spacebunny019-20261004-r1 --runtime podman --seed 261004 --canary-key codira-tests --canary-budget-usd 0.25 --canary-max-total-tokens 200000 --fixture-source click-public=/home/marco/Personalia/Progetti/Software/Python/codira/.artifacts/agent-efficiency/attempts/011/fixture-sources/click --fixture-source codira-current-public=/home/marco/Personalia/Progetti/Software/Python/codira/.artifacts/agent-efficiency/executions/fixture-update-20261003-r1/fixture-sources/codira-current-public --fixture-source go-service-synthetic=/home/marco/Personalia/Progetti/Software/Python/codira/benchmarks/agent-efficiency/synthetic/go-service --fixture-source picomatch-public=/home/marco/Personalia/Progetti/Software/Python/codira/.artifacts/agent-efficiency/attempts/011/fixture-sources/picomatch --fixture-source python-service-synthetic=/home/marco/Personalia/Progetti/Software/Python/codira/benchmarks/agent-efficiency/synthetic/python-service --fixture-source typescript-workspace-synthetic=/home/marco/Personalia/Progetti/Software/Python/codira/benchmarks/agent-efficiency/synthetic/typescript-workspace
```

Campaign 020:

```bash
uv run python scripts/launch_agent_efficiency_pilot.py --prepare --campaign-dir .artifacts/agent-efficiency/campaigns/codira-efficacy-campaign-020 --execution-root .artifacts/agent-efficiency/executions/luna020-20261004-r1 --runtime podman --seed 261004 --canary-key codira-tests --canary-budget-usd 0.25 --canary-max-total-tokens 200000 --fixture-source click-public=/home/marco/Personalia/Progetti/Software/Python/codira/.artifacts/agent-efficiency/attempts/011/fixture-sources/click --fixture-source codira-current-public=/home/marco/Personalia/Progetti/Software/Python/codira/.artifacts/agent-efficiency/executions/fixture-update-20261003-r1/fixture-sources/codira-current-public --fixture-source go-service-synthetic=/home/marco/Personalia/Progetti/Software/Python/codira/benchmarks/agent-efficiency/synthetic/go-service --fixture-source picomatch-public=/home/marco/Personalia/Progetti/Software/Python/codira/.artifacts/agent-efficiency/attempts/011/fixture-sources/picomatch --fixture-source python-service-synthetic=/home/marco/Personalia/Progetti/Software/Python/codira/benchmarks/agent-efficiency/synthetic/python-service --fixture-source typescript-workspace-synthetic=/home/marco/Personalia/Progetti/Software/Python/codira/benchmarks/agent-efficiency/synthetic/typescript-workspace
```

## Start both campaigns

After both preparations pass, run these receipt-only commands from the repository
root. Each launcher creates its own durable tmux execution session and returns,
so invoking both starts overlapping campaigns. No model, credential or image
replacements are accepted at launch.

The current launcher still enforces fifteen-minute authenticated admission
freshness; the approved four-hour refresh policy is not implemented. Start both
while their receipts are fresh. If either is expired, stop and obtain supported
fresh readiness; do not alter timestamps or reuse campaign 016's exception.

```bash
uv run python scripts/launch_agent_efficiency_pilot.py --launch --execution-root .artifacts/agent-efficiency/executions/spacebunny019-20261004-r1
uv run python scripts/launch_agent_efficiency_pilot.py --launch --execution-root .artifacts/agent-efficiency/executions/luna020-20261004-r1
```

The authoritative records for each root are `readiness-receipt.json`,
`launch-receipt.json`, `logs/pilot.log`, `pilot.exit`, and
`state/campaign-state.json`. Preserve the receipt-bound fixtures, source,
harness, image, model controls and raw evidence. Report canaries separately;
judge deterministic correctness and paired outcomes independently of transport
success. An operational failure stops its campaign and blocks automatic resume.
