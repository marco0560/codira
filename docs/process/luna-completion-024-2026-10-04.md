# Luna completion 024: actual billing and unfinished slots

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

The operator explicitly requested fixing, committing, generating and executing
only unfinished Luna work. Fresh preparation must pass the full repository gate,
offline image/native/fixture/rubric/patch qualification, an authenticated
/models/user route check, and one readiness canary on codira-tests capped at
$0.25 and 200,000 tokens. Launch through scripts/launch_agent_efficiency_pilot.py
only after its readiness receipt is complete and fresh. Preserve the generated
manifest, source snapshot, raw response evidence, logs and terminal exit files.
Do not mutate campaign 020 or include Space Bunny's MCP changes in this run.

## Completion preparation history

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
