# Campaign 015 preparation and launch handoff — 2026-10-04

The operator approved the [revised price controls](agent-efficiency-campaign-015-controls-2026-10-04.md)
and the bounded $0.25 readiness canary on `codira-tests-key`. Campaign 015
retains the model, image, fixtures, panel, schedule and all remaining controls.
Prior failed preparation evidence is preserved. Main execution requires separate
authorization. Readiness is proven only by its current immutable receipt.

Read-only authenticated admission for this revised specification passed before
complete preparation. The wheel integration test now builds a disposable core
source copy, preserving the ignored generated version file in the serving
checkout. Its real build passed and retained the qualified core fingerprint.
The exact image-generated metadata was restored after hash verification;
before/after bytes and rollback evidence remain under
`.artifacts/agent-efficiency/analysis/glm-campaign-selection-20261003-r1/generated-version-rollback/`.

## Selected controls

This preparation passed all 18 patch calibration cases, the full repository
gate (1,295 passed, three skipped, 85% coverage) and authenticated route admission.
The model canary then stopped locally with
`attempt_spend_cap_reservation_exceeded`: its inherited 2,500,000-token session
guard reserves more than the approved $0.25 allowance. Provider observations
contain one local rejection and no upstream response; no completion was
forwarded. The serving fingerprint remained unchanged after validation.
Preserve this failed execution root and do not retry its commands. The operator
must choose a separate 200,000-token canary guard at $0.25, or retain the
2,500,000-token canary guard with a $1.75 allowance, before fresh preparation.
Both alternatives passed the actual local proxy guard with the retained native
request size in a credential-free, network-free check. Evidence is under
`.artifacts/agent-efficiency/analysis/glm-campaign-selection-20261003-r1/canary-guard-alternatives.json`.
The operator selected the separate 200,000-token guard at $0.25; continue with
the fresh [campaign 016 handoff](agent-efficiency-campaign-016-handoff-2026-10-04.md).

| Control | Value |
| --- | --- |
| Specification | `benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-015.json` |
| Factory directory | `.artifacts/agent-efficiency/campaigns/codira-efficacy-campaign-015/` |
| Factory fingerprint | `8902187ff70ba814f508f4cd2b1a3f774188d9591496debf9ee119aab66dc745` |
| Execution root | `.artifacts/agent-efficiency/executions/glm015-20261004-r1/` |
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
  --campaign-dir .artifacts/agent-efficiency/campaigns/codira-efficacy-campaign-015 \
  --execution-root .artifacts/agent-efficiency/executions/glm015-20261004-r1 \
  --runtime podman \
  --seed 261004 \
  --canary-key codira-tests \
  --canary-budget-usd 0.25 \
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
  --execution-root .artifacts/agent-efficiency/executions/glm015-20261004-r1
```

Readiness expires after fifteen minutes. Expired preparation requires a fresh
execution root and renewed bounded preparation authorization where needed.
Preserve existing evidence. Report operational completion and deterministic
task-oracle correctness separately when evaluating the campaign.
