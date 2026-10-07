# Agent-efficiency preparation history — 2026-10-07

This historical register replaces superseded handoffs. It contains no launch
instructions or current authorization. Campaign specifications, generated
manifests, readiness receipts, provider responses and failed execution evidence
remain unchanged in their original identities.

Use [campaign creation instructions](campaign-creation-instructions-2026-10-03.md)
and [the campaign factory](agent-efficiency-campaign-factory.md) for fresh work.
The exact removed documents, including commands and authorization wording, are
recoverable from the pre-cleanup Git snapshot recorded below.

## GLM preparations 012–015

The common model was `z-ai/glm-5.3-flash`, mandatory `max` reasoning. Controls
were the 24-task representative panel, three repetitions, 144 attempts, seed
261004, 2,500,000 session tokens, 64,000 output tokens, 1,800 seconds, 45 logical
requests and three transport attempts. The common frozen source, image and
profile fingerprints are retained in each identity section below.

| Identity | Result and approved progression |
| --- | --- |
| 012 | Stopped at the credential-free native shell probe: nested Bubblewrap could not create a UID map. No authentication or model call. Replaced by 013. |
| 013 | Corrected the native sandbox probe. First preparation was interrupted with exit 130 before paid contact to freeze the prevention procedure; the next stopped at the repository gate on six stale suppression references. No paid model call. Replaced by 014. |
| 014 | Passed offline checks and repository gate, then failed authenticated admission because the public prompt price exceeded the frozen $0.04/M ceiling. No paid canary. Replaced by the approved 015 price revision. |
| 015 | Raised prompt ceiling to $0.16/M and attempt estimate to $1.75; completion ceiling $0.60/M, pool $7 and daily ceiling $8 stayed fixed. Passed offline/gate/admission checks, then the canary failed locally with `attempt_spend_cap_reservation_exceeded`; no upstream completion. Replaced by 016 with a separate canary token guard. |

The operator approved bounded $0.25 tests-key readiness canaries and preparation
changes, separately from main campaign execution. [The exact 015 approved
controls](agent-efficiency-campaign-015-controls-2026-10-04.md) retain the price
comparison and reservation calculation. [Campaign 016](agent-efficiency-campaign-016-handoff-2026-10-04.md)
records the fresh 200,000-token canary guard and continuation controls.

## Frozen GLM source and environment

All four preparations retained the following source/image bindings:

| Binding | Historical value |
| --- | --- |
| Serving commit | `6a3c025e119a4113323bf3eef7b3c2a376a301fe` |
| Core serving fingerprint | `c090198e2cd98b19472bc0cc604041c050d7249873c0afd28c81a56a43c142e5` |
| Codira task-fixture tree | `06a7593e5387f7fa20589a643873ef0de1d3fa9b` |
| Environment image | `localhost/codira-glm-campaign@sha256:4353282d3fefec0e8807317053bc980a4856dbcd086d41bb37ebcbab3ff54d53` |
| Image-profile fingerprint | `3f9a6ab2e93095a7c0ea21217bc1990700550cf0959173d8920f93cfcb20d7f7` |
| Runtime-profile fingerprint | `fa064e8d8a4d607aa67ddca2f9ab23dcc20df1494468c17bdec0b3770fe128d2` |
| Image qualification | `.artifacts/agent-efficiency/environment-images/glm-20261003-r1/` |
| Authenticated controls | `.artifacts/agent-efficiency/analysis/glm-campaign-selection-20261003-r1/` |
| Native executable | `0.159.3`, accepting `max` |

The 2026-10-03 catalog observation admitted mandatory reasoning at `max`,
`high` and `low`, 1,048,576 context tokens and 131,072 output tokens. These are
historical observations, not current provider admission. Main accounting used
a $7 shared pool and $8 daily ceiling; an in-flight response could cross the
pool. The $7 pool did not promise completion. Canary accounting was separate:
$0.25 tests-key allowance and 120-second turn timeout. For 012 that allowance
was proposed, subject to explicit authorization; subsequent bounded canaries
were approved. Ceiling-based reservations were not actual invoiced charges.

## GLM identity bindings

Each specification is `benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-<id>.json`;
each immutable factory directory is
`.artifacts/agent-efficiency/campaigns/codira-efficacy-campaign-<id>/`.

| Identity | Factory fingerprint | Execution root | Prompt/completion ceiling per million | Attempt estimate |
| --- | --- | --- | --- | --- |
| 012 | `94ad18a865c35e1d4213ab3c7f60a6057a1f38dfdb917a9a9ecbd01166787e12` | `.artifacts/agent-efficiency/executions/glm012-20261003-r1/` | $0.04 / $0.60 | $1.60 |
| 013 | `26a958add21897e34e12cbd79e52d200c28603ab40fab99d40cd2fb46679e956` | `.artifacts/agent-efficiency/executions/glm013-20261004-r2/` | $0.04 / $0.60 | $1.60 |
| 014 | `ba567ed07a3684ecb51d54f113fb2e498cadd9c4d424b53d1d0a0596ef97eaa1` | `.artifacts/agent-efficiency/executions/glm014-20261004-r1/` | $0.04 / $0.60 | $1.60 |
| 015 | `8902187ff70ba814f508f4cd2b1a3f774188d9591496debf9ee119aab66dc745` | `.artifacts/agent-efficiency/executions/glm015-20261004-r1/` | $0.16 / $0.60 | $1.75 |

The interrupted first 013 preparation remains at
`.artifacts/agent-efficiency/executions/glm013-20261004-r1/`; its replacement
used `r2` without rewriting the first record.

## Campaigns 017 and 018

Both were superseded after preflight rejection; neither became ready or launched,
and no canary started. The operator authorized bounded canaries, not the main
campaigns. The successor is [019/020 preparation](dual-campaign-019-020-preparation-2026-10-04.md).

| Control | Campaign 017 | Campaign 018 |
| --- | --- | --- |
| Route | OpenRouter Responses | OpenRouter Responses |
| Model | `stealth/space-bunny-alpha` | `openai/gpt-6-luna` |
| Reasoning | `max` (mandatory reasoning) | `high` |
| Input/output ceilings, USD per million | 0.16 / 0.60 | 0.20 / 0.75 |
| Attempts | 144 | 144 |
| Schedule | 24 tasks, two arms, three repetitions, seed 261004 | Same |
| Session token planning | 2,500,000 | Same |
| Output per response | 64,000 | Same |
| Logical requests / transport attempts | 45 / 3 | Same |
| Attempt timeout | 1,800 seconds | Same |
| Campaign pool / daily ceiling / attempt estimate, USD | 7 / 8 / 1.75 | Same |
| Canary key / allowance / token guard | codira-tests / 0.25 USD / 200,000 | Same |

The historical catalogs admitted both exact routes and reasoning policies.
Space Bunny reported zero price, but positive frozen ceilings still drove its
conservative ledger. Luna ceilings covered the long-context tier. The two $7
campaign ledgers were independent: the harness did not enforce a joint $8 daily
ledger. Overlapping runs would share host/provider resources and would not
establish isolated timing performance. Actual provider charges and conservative
reservations required separate reporting.

Historical execution bindings were
`.artifacts/agent-efficiency/executions/spacebunny017-20261004-r1/` and
`.artifacts/agent-efficiency/executions/luna018-20261004-r1/`. Their failed
admission evidence remains immutable.

## Luna completion 024: actual billing and unfinished slots

Campaign 020 stopped on a conservative ledger of $7.00343275. Its 857 retained
upstream responses report only $0.846592325 in actual charges. All response
body digests were verified. The key-wide daily usage snapshot of $0.971618246
is a separate measure and includes activity outside this campaign.

The new factory defaults OpenRouter shared pools to provider-reported USD.
Terminal usage.cost is retained exactly; unknown billing stops execution.
Price ceilings qualify the route but do not decide spending-based stopping.
Historical parent journals remain immutable and are not repriced in place.

Completion 024 selects exactly 86 unfinished slots from campaign 020: 85 never
started and one interrupted by campaign_spend_limit_reached. The 58 operationally
finished attempts are excluded, including scored task failures. The interrupted
attempt is retained as a failed parent record; its complete provider charges
remain included. No paid work is launched merely by generating the campaign.

The new journal carries forward $0.846592325 of parent charges against the same
$7 total pool, leaving $6.153407675. The daily ceiling remains $8. Model:
OpenRouter openai/gpt-6-luna, high reasoning. Seed 261004; 64,000 output tokens;
45 logical response requests; 3 transport attempts; 1,800-second timeout.
The 2,500,000-token value remains a full-campaign planning estimate. Provider,
image, core source, response budgets, task/oracle definitions, resource controls,
treatment instructions and parent order are unchanged. Only the host accounting
and continuation harness changes under a new immutable identity.

Source and execution pointers:

- Specification: benchmarks/agent-efficiency/campaign-specs/codira-efficacy-completion-024.json
- Factory artifacts: .artifacts/agent-efficiency/campaigns/codira-efficacy-completion-024
- New execution: .artifacts/agent-efficiency/executions/luna024-20261004-r1
- Parent execution: .artifacts/agent-efficiency/executions/luna020-20261004-r1
- Fix worktree: .artifacts/agent-efficiency/worktrees/luna-billing-continuation-20261004-r1
- Operational records and logs: .artifacts/agent-efficiency/analysis/luna-billing-continuation-20261004-r1

The operator requested fixing, committing, generating and executing only
unfinished Luna slots. That historical authorization did not permit rewriting
campaign 020 or merging Space Bunny MCP changes into the run. No model calls
occurred in preparations 024, 025 or 026.

### Completion preparation history

The completion identities were advanced only after a specific offline gate
rejected the preceding fresh identity; no model calls occurred in campaigns
024, 025, or 026:

- Campaign 024 stopped at the launcher's fixed six-attempt cardinality check.
  The launcher now validates the exact selective schedule length; regression
  tests cover 85 and 86 slots. Campaign 025 records the fresh retry.
- Campaign 025 passed protected patch qualification but stopped at the full
  repository gate because five lint-suppression line references were stale.
  Campaign 026 records the retry after updating that inventory.
- Campaign 026 passed the repository gate but stopped before authenticated
  provider contact because the runner required exactly three completion tasks.
  The runner now derives the task count from the validated schedule. Campaign
  027 records the fresh retry and its 86 unfinished attempts.

The versioned specifications for all three superseding identities remain under
`benchmarks/agent-efficiency/campaign-specs/`; their generated factory and
execution evidence remains under the corresponding ignored `.artifacts/`
paths. The failed preparation evidence remains preserved with those identities.

The combined result for the initial campaign 020 and its campaign 027
continuation, including the forensic failure analysis, is in the
[Luna combined campaign report](agent-efficiency-luna-combined-campaign-results-2026-10-05.md).

## Original handoff recovery

The complete controls, commands and authorization wording remain in Git at
`f7d27c8b66777a5d0ec0b5bd231e4ddedb36ec42`. Recover each original document with:

```bash
git show 'f7d27c8b66777a5d0ec0b5bd231e4ddedb36ec42:docs/process/<original-filename>'
```

Original filenames:

- `agent-efficiency-campaign-012-handoff-2026-10-04.md`
- `agent-efficiency-campaign-013-handoff-2026-10-04.md`
- `agent-efficiency-campaign-014-handoff-2026-10-04.md`
- `agent-efficiency-campaign-015-handoff-2026-10-04.md`
- `dual-campaign-017-018-preparation-2026-10-04.md`
- `luna-completion-024-2026-10-04.md`
