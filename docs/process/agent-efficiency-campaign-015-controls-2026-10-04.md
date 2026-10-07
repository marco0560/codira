# Approved campaign 015 controls — 2026-10-04

Historical approved price controls. Campaign 015 was superseded after a local
canary rejection; its original specification and evidence remain immutable.
See [the preparation history](agent-efficiency-preparation-history-2026-10-07.md)
for outcomes and replacements. This record is not a preparation instruction
or renewed authorization.

The specification remains
`benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-015.json`.

Campaign 014 passed the image, both native tool arms, fixture freshness, rubric
calibration, all 18 applied-patch cases and the full repository gate. The gate
reported 1,295 passed, three skipped, 85% coverage and no blocking scan findings.
Authenticated admission then rejected the public input price above its frozen
ceiling. No paid model call occurred. Its execution root and complete evidence
remain immutable under
`.artifacts/agent-efficiency/executions/glm014-20261004-r1/`.

The refreshed public catalog listed `z-ai/glm-5.3-flash` at $0.15 input and $0.50
output per million tokens. The scoped authenticated pilot catalog observed at
2026-10-04T07:03:09Z listed $0.0352 input and $0.50 output, with mandatory
reasoning and supported efforts `max`, `high` and `low`. The admission contract
must cover both catalogs. Raw public model metadata and sanitized authenticated
controls are retained under
`.artifacts/agent-efficiency/analysis/glm-campaign-selection-20261003-r1/` as
`public-controls-20261004-r1.json` and `controls-campaign-20261004-r1.json`.

| Control | Campaign 014 | Approved campaign 015 |
| --- | --- | --- |
| Prompt ceiling per million | $0.04 | $0.16 |
| Completion ceiling per million | $0.60 | $0.60 |
| Attempt planning estimate | $1.60 | $1.75 |
| Campaign shared pool | $7 | $7 |
| Daily ceiling | $8 | $8 |
| Separate tests-key canary allowance | $0.25 | $0.25 |

The revised planning estimate covers the conservative token reservation:
2,500,000 session tokens at $0.60 per million, plus a 1,048,576-token context
reserve at $0.16 per million and 64,000 output tokens at $0.60 per million,
totaling $1.70617216. Main shared-pool execution retains its existing observed
pool enforcement; this estimate does not promise completion of the schedule.

The model, mandatory `max` reasoning, image and fixture identities, three
repetitions, 24 tasks, 144 paired attempts, seed 261004, 2,500,000 session tokens,
64,000 output tokens, 1,800-second attempt timeout, 45 logical requests and
three transport attempts per response remain as selected. The bounded readiness
canary uses `codira-tests-key` and a 120-second turn timeout. Main execution
continues to require separate authorization.
