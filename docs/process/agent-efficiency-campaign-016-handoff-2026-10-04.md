# Campaign 016 preparation and launch handoff — 2026-10-04

The operator approved a separate 200,000-token readiness canary guard with the
$0.25 allowance on `codira-tests-key`. Main campaign controls remain unchanged:
2,500,000 session tokens, 64,000 output tokens, $7 shared pool, $8 daily ceiling,
`z-ai/glm-5.3-flash` with mandatory `max` reasoning, three repetitions and 144
paired attempts. The approved campaign 015 price revision is retained.

Campaign 015 passed its full offline and repository gate, but the proxy rejected
the canary locally before forwarding a completion because its inherited token
reservation could not fit $0.25. That failed evidence remains immutable. The
new harness binds the separate token guard into canary admission, execution,
received usage and readiness receipts, leaving main execution controls intact.
Actual proxy guard admission and receipt isolation are covered by focused
checks. Main execution remains separately authorized; readiness requires its
current immutable receipt and all eleven checks.

## Selected controls

| Control | Value |
| --- | --- |
| Specification | `benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-016.json` |
| Factory directory | `.artifacts/agent-efficiency/campaigns/codira-efficacy-campaign-016/` |
| Factory fingerprint | `9014d8624fd75e546f621e3b637e919a203fa52e58fce34103a753266abdb505` |
| Execution root | `.artifacts/agent-efficiency/executions/glm016-20261004-r1/` |
| Panel and repetitions | `representative-v1`, 24 tasks, three repetitions |
| Schedule | 144 attempts, 72 per arm, seed `261004` |
| Model and reasoning | `z-ai/glm-5.3-flash`, mandatory reasoning, `max` |
| Session controls | 2,500,000 tokens; 64,000 output tokens; 1,800 seconds |
| Request controls | 45 logical requests; three transport attempts per response |
| Main accounting | $7 shared pool; $8 daily ceiling; $1.75 attempt planning estimate |
| Price ceilings per million | $0.16 prompt; $0.60 completion |
| Canary selection | `codira-tests-key` through `--canary-key codira-tests` |
| Approved separate canary allowance | $0.25 |
| Canary turn timeout | 120 seconds |
| Separate canary token guard | 200,000; main remains 2,500,000 |

The authenticated catalog observed on 2026-10-03 admitted `max`, `high` and
`low`, mandatory reasoning, a 1,048,576-token context and 131,072 maximum output
tokens. Observations are retained under
`.artifacts/agent-efficiency/analysis/glm-campaign-selection-20261003-r1/`.
Preparation must repeat authenticated admission for each selected key; these
historical observations do not substitute for fresh readiness.

The main shared pool stops admission of new work at the observed threshold.
The token and attempt figures are planning estimates for main execution, and
an in-flight response can cross the remaining pool. The $7 pool does not promise
completion of all 144 scheduled attempts. The canary additionally applies its
own token and dollar guards and rejects usage beyond its allowance. Canary
accounting is separate from the main campaign ledger; ceiling-based estimates
are not actual invoiced charges.

## Frozen source and environment

The selected clean serving checkout is commit
`6a3c025e119a4113323bf3eef7b3c2a376a301fe`. Its core serving fingerprint is
`c090198e2cd98b19472bc0cc604041c050d7249873c0afd28c81a56a43c142e5`.
The updated Codira task fixture uses that commit and tree
`06a7593e5387f7fa20589a643873ef0de1d3fa9b`. Panel references and calibration
documents were regenerated through their repository generators.

The environment image is
`localhost/codira-glm-campaign@sha256:4353282d3fefec0e8807317053bc980a4856dbcd086d41bb37ebcbab3ff54d53`.
Its image-profile fingerprint is
`3f9a6ab2e93095a7c0ea21217bc1990700550cf0959173d8920f93cfcb20d7f7`;
the distinct runtime-profile fingerprint is
`fa064e8d8a4d607aa67ddca2f9ab23dcc20df1494468c17bdec0b3770fe128d2`.
Build and offline image-qualification evidence is retained under
`.artifacts/agent-efficiency/environment-images/glm-20261003-r1/`.
The qualified native executable is version `0.159.3` and accepts `max`.

Harness, specification and documentation changes must be finalized before
readiness. The resulting receipts bind their actual bytes. Do not modify the
factory manifests or receipt-bound inputs to repair a mismatch.

## Complete preparation, after authorization

Use the repository procedure in
[campaign creation instructions](campaign-creation-instructions-2026-10-03.md).
The operator authorized one bounded canary on the tests key with a $0.25
allowance. Execute this command from the repository root in the host context:

```bash
uv run python scripts/launch_agent_efficiency_pilot.py \
  --prepare \
  --campaign-dir .artifacts/agent-efficiency/campaigns/codira-efficacy-campaign-016 \
  --execution-root .artifacts/agent-efficiency/executions/glm016-20261004-r1 \
  --runtime podman \
  --seed 261004 \
  --canary-key codira-tests \
  --canary-budget-usd 0.25 \
  --canary-max-total-tokens 200000 \
  --fixture-source 'click-public=/home/marco/Personalia/Progetti/Software/Python/codira/.artifacts/agent-efficiency/attempts/011/fixture-sources/click' \
  --fixture-source 'picomatch-public=/home/marco/Personalia/Progetti/Software/Python/codira/.artifacts/agent-efficiency/attempts/011/fixture-sources/picomatch' \
  --fixture-source 'codira-current-public=/home/marco/Personalia/Progetti/Software/Python/codira/.artifacts/agent-efficiency/executions/fixture-update-20261003-r1/fixture-sources/codira-current-public' \
  --fixture-source 'python-service-synthetic=/home/marco/Personalia/Progetti/Software/Python/codira/benchmarks/agent-efficiency/synthetic/python-service' \
  --fixture-source 'typescript-workspace-synthetic=/home/marco/Personalia/Progetti/Software/Python/codira/benchmarks/agent-efficiency/synthetic/typescript-workspace' \
  --fixture-source 'go-service-synthetic=/home/marco/Personalia/Progetti/Software/Python/codira/benchmarks/agent-efficiency/synthetic/go-service'
```

Do not wrap the parent command in SOPS. The launcher scopes the registered
tests environment to the canary child. Main preflight, post-canary capacity
admission and campaign execution retain the pilot environment. Preserve the
complete preparation log, terminal exit status and all eleven check records.
The pipeline runs the full repository gate under tmux before inference; do not
run a duplicate gate simply to repeat that check. Run the independent Codira
audit before preparation. A failed check requires investigation and a fresh
execution root; do not retry inference automatically. Changed frozen controls
require a fresh factory campaign identity.

## Receipt-based launch, separately authorized

Require a successful `readiness-receipt.json` in the execution root, every
required check admitted, actual successful model-requested `index_status` and
`context_for_task` calls, shell-marker completion, complete usage, post-canary
main-key capacity admission and unchanged receipt bindings. Inspect the actual
accounting evidence; offline tests or successful HTTP transport do not qualify
the model or prove task correctness.

After explicit main-campaign authorization, use only the receipt bindings:

```bash
uv run python scripts/launch_agent_efficiency_pilot.py \
  --launch \
  --execution-root .artifacts/agent-efficiency/executions/glm016-20261004-r1
```

Readiness expires after fifteen minutes. Expired preparation requires a fresh
execution root and renewed bounded preparation authorization where needed.
Preserve existing evidence. Report operational completion and deterministic
task-oracle correctness separately when evaluating the campaign.
