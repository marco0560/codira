# Campaign 009 selective completion and composite result

Campaign `codira-efficacy-completion-009` filled the six failed or unstarted
slots of `codira-efficacy-campaign-006` without rerunning its 54 completed
task attempts. It used a fresh factory-generated identity. The source plan,
state, and all 55 original records were bound by exact byte digests in the new
launch plan. The parent campaign's failed `patch-002-r05-codira-mcp` record
remains intact; its replacement is used only in the composite analysis.

## Recovery and execution

A power failure interrupted candidate 009 before its authenticated preflight.
Its generated factory artifacts, prepared fixture receipt, and completed
repository gate survived. Its execution state contained no attempt marker,
record, log, or paid response. After restart, the factory check passed, the
pinned runtime image remained cached, and authenticated route and key
preflight passed again. The runner then launched in tmux and exited `0` with
six settled results, no pending attempt, and no operational or oracle failure.
All six records passed immutable-state validation with complete provider usage.

The six attempts charged **$0.48971925** at the frozen price ceilings against
the completion campaign's $2 observed-spend pool. These are accounting
estimates from received provider token usage, not a provider invoice.

| Pair | Codira-MCP result, tokens, cost | Baseline result, tokens, cost |
| --- | --- | --- |
| `patch-002-r05` | Pass; 540,874; $0.14291300 | Pass; 275,416; $0.07209500 |
| `impact-001-r05` | Pass; 232,083; $0.06036375 | Pass; 370,602; $0.09695250 |
| `architecture-001-r01` | Pass; 307,728; $0.08041850 | Pass; 142,778; $0.03697650 |

The patch Codira arm that previously stopped at a local token reservation
completed under observed-spend accounting. Its new result passed patch
application, required path checks, and the protected command. This is one
successful new trajectory, not proof that the previous trajectory would have
converged if continued.

## Composite interpretation

Campaign 006 retains 55 original records: 54 operational passes and one failed
Codira patch attempt. Its frozen grades are 37 oracle passes and 17 literal
text-oracle failures among the 54 completed task attempts. The separate
[answer adjudication](agent-efficiency-campaign-006-adjudication-2026-09-30.md)
found that all 17 rejected text answers contained the required task facts;
a read-only replay of all 28 completed text answers under the revised oracles
passed 28/28. Those retrospective grades do not alter campaign 006's records.

Selecting those 54 completed task attempts and candidate 009's six passes
fills **60 distinct logical slots in 30 pairs**. All 60 have complete
operational results. Under the documented revised text scoring, all 60 satisfy
their applicable task oracles; this is a retrospective composite, not a
single campaign executed under one harness and oracle revision. Report the
parent and completion provenance separately in any comparison. The oracles
check specified facts or protected behavior, not the full quality of every
explanation.

Campaign 006's recorded charge was $4.09832850, including $0.18740500 for
the abandoned patch attempt. Adding the completion run gives **$4.58804775
total observed ceiling-priced spending**. The 60 selected composite results
account for $4.40064275; the difference is the preserved failed attempt's
charge. Neither amount is an invoice total.

## Evidence

- Factory [specification](../../benchmarks/agent-efficiency/campaign-specs/codira-efficacy-completion-009.json), generated [manifest](../../.artifacts/agent-efficiency/campaigns/codira-efficacy-completion-009/campaign.json), and [launch plan](../../.artifacts/agent-efficiency/campaigns/codira-efficacy-completion-009/launch-plan.json).
- Ignored [preflight](../../.artifacts/agent-efficiency/gates/completion-009-20260930/preflight.json), [control checklist](../../.artifacts/agent-efficiency/gates/completion-009-20260930/control-checklist.json), [launch receipt](../../.artifacts/agent-efficiency/executions/c009/launch-receipt.json), [log](../../.artifacts/agent-efficiency/executions/c009/logs/pilot.log), [exit status](../../.artifacts/agent-efficiency/executions/c009/pilot.exit), and [checkpoint](../../.artifacts/agent-efficiency/executions/c009/state/budget/checkpoint-000.json).
- The saved full gate is [log](../../.artifacts/validation/repo-gates/completion-stage-r5-20260930/validation.log) and [exit status](../../.artifacts/validation/repo-gates/completion-stage-r5-20260930/validation.exit): `0`, 1,204 passed, three skipped.
- Final repository validation after the report was staged is [log](../../.artifacts/validation/repo-gates/completion-009-final-20260930/validation.log) and [exit status](../../.artifacts/validation/repo-gates/completion-009-final-20260930/validation.exit): `0`, 1,204 passed, three skipped.

Raw provider bodies, protected-command traces, and fixture locations remain
only in ignored per-attempt evidence. This report contains no credential
values or paths outside the repository.

## Subsequent runtime qualification finding

The [full audience findings](issue-053-audience-findings.md) and
[internal product assessment](issue-053-internal-product-assessment.md)
record the 2026-09-30 forensic follow-up. Offline inspection showed that the
pinned image served the older character-budget `result.context` protocol,
while the public Codira source fixture contained the newer item/cursor code.
The saved context calls confirm the older deployed shape. These results
therefore do not evaluate the current pagination implementation. Composite
selection, spending, original grades, and immutable attempt records are
unchanged; the follow-up adds substantive quality review and corrects protocol
attribution.
