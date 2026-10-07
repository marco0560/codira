# Combined Luna campaign analysis — 2026-10-05

> This execution report preserves the original frozen grades. The
> [2026-10-07 semantic closeout](agent-efficiency-luna-semantic-review-2026-10-07.md)
> adds separate blinded adjudication, independent review and corrected cost
> scopes. The assisted cost below includes the interrupted parent attempt;
> final-slot assisted cost is $1.020210140, with $0.006405485 retained separately
> as recovery spending. No original campaign result is overwritten.

## Original frozen-grade finding

The complete 144-slot schedule ran, but it does **not establish whether Codira-MCP improves answer quality**. In the final slot set, 142 task-oracle results are `not_evaluated` because the frozen quality rubrics require semantic review. The other two slots failed deterministic patch checks, one in each arm. There are no overall oracle passes. Operational completion and recorded usage are complete for all 144 final slots.

The corrected spending procedure worked. Campaign 020 stopped after 59 starts because its ceiling-based ledger reached $7.00343275. Its 857 retained OpenRouter response bodies report actual `usage.cost` totaling $0.846592325. Completion 027 filled the 86 unfinished slots for $1.186210530. Combined task-execution charges were **$2.032802855**, leaving **$4.967197145** of the original $7 pool.

## Schedule and parity

- Campaign 020 scheduled 24 tasks × 3 repetitions × 2 arms = 144 attempts. It started 59: 58 operationally settled and one interrupted by the spend guard.
- Completion 027 selected exactly 86 unfinished slots: 85 never started and the interrupted `panel-u3-r01-codira-mcp` slot. Its original attempt remains preserved; the completion attempt replaces it in final per-slot outcomes. The two records are both included in charges, but the slot is counted once.
- The composite covers **144 unique slots and 72 baseline/Codira-MCP pairs**, with 72 attempts per arm and three repetitions per task.
- The manifests match on model (`openai/gpt-6-luna`, high reasoning), seed (261004), common task and fixture fingerprints, runtime image digest, runtime profile, source fingerprint, resource controls, treatment instructions, output budget, logical-request limit, and transport retry limit. Completion adds the provider-reported spending basis and uses a fresh harness identity for billing and selective recovery. The same OpenRouter model identifier was used on two dates; identical provider-side alias implementation across those dates is not proven.
- Active paid runtime was **4h 20m 46s** for 020 and **5h 21m 18s** for 027, or **9h 42m 04s** combined, excluding the pause between runs.

## Outcomes

| Final per-slot result | Baseline | Codira-MCP | Total |
| --- | ---: | ---: | ---: |
| Operationally passed | 72 | 72 | 144 |
| Terminal outcome `success` | 71 | 71 | 142 |
| Deterministic oracle failure | 1 | 1 | 2 |
| Oracle `not_evaluated` / semantic review required | 71 | 71 | 142 |
| Oracle passed | 0 | 0 | 0 |
| Complete recorded usage | 72 | 72 | 144 |

The Codira-MCP failure was `panel-f2-r01-codira-mcp`: the protected plugin-capability check raised `AttributeError` because `Upper` had no `capabilities` method. The baseline failure was `panel-p3-r03-baseline`: it produced an empty patch, and `git apply --check` reported no valid patches. These failures are in different tasks and opposite arms; they do not establish a relative advantage.

Here, `success` means the run reached a terminal harness outcome without a deterministic oracle failure. It does **not** certify semantic quality. The frozen rubrics mark substance, coverage, grounding, and usability for review. The offline rubric calibration and 18-case patch pipeline passed during readiness, but those checks qualified the grading pipeline; they did not grade these campaign answers.

## Usage and tool adoption

| Measure | Baseline | Codira-MCP |
| --- | ---: | ---: |
| Attempts | 72 | 72 |
| Input tokens | 32,288,627 | 32,605,895 |
| Output tokens | 714,951 | 714,603 |
| Mean input + output tokens per attempt | 458,383 | 462,785 |
| Median input + output tokens per attempt | 267,994 | 253,147 |
| Mean recorded attempt elapsed | 130.9s | 130.9s |
| Provider-reported task cost, including interrupted start | $1.006187230 | $1.026615625 |

Across both arms the recorded total was 66,324,076 input-plus-output tokens. Input usage includes cached input, so cached tokens are not added again. Across all 72 pairs, Codira-MCP used a mean **4,402 more input-plus-output tokens per attempt** (median difference +9,484); **38 pairs used more and 34 fewer**. The 2026-10-07 independent review corrected the earlier 36/36 count and regenerated the 2,000-resample bootstrap over canonically sorted task means with seed 53: its 95% interval is **−84,733 to +82,360 tokens** for the assisted-minus-baseline mean. The earlier −80,009 to +81,049 interval lacked explicit calculation-order provenance; the reproducible recheck is retained in `all-pair-recheck.json` under the semantic-review evidence identity. Both intervals span zero, so these data do not show a reliable token-efficiency change. The 70 pairs where neither arm had a deterministic failure were also mixed (mean difference −3,408; median +8,596), and were ungraded at this checkpoint. The subsequent semantic closeout uses reviewed quality to define its matched subset.

The assisted arm made **188 Codira-MCP calls in 23 of 72 attempts**. Of those calls, 182 succeeded, six failed, and 18 were repeated. The other 49 assisted attempts made no MCP calls. This shows limited treatment adoption, not answer correctness. Baseline made no MCP calls, as configured.

## Spending reconciliation

Cost reconstruction read `usage.cost` from each retained terminal response body after checking its SHA-256 against the attempt observation.

| Execution | Upstream response bodies | Provider-reported cost | Missing costs | Digest mismatches |
| --- | ---: | ---: | ---: | ---: |
| Initial 020, including interrupted attempt | 857 | $0.846592325 | 0 | 0 |
| Completion 027 | 1,164 | $1.186210530 | 0 | 0 |
| Total | 2,021 | **$2.032802855** | 0 | 0 |

The old 020 ceiling ledger was about **8.27×** the provider-reported cost and stopped a run that had spent $0.84659 by the response-level evidence. The completion journal carried that verified parent amount forward and stopped on provider-reported charges; all 86 remaining slots settled under the original pool.

Task-execution spending excludes readiness canaries on the separate tests key. The two 027 readiness canaries charged $0.004118270 in total. The initial 020 canary retained a $0.00962475 ceiling estimate but no exact provider charge, so its actual charge cannot be added from the preserved record.

## Interpretation

**Operational result:** complete. The original 144-slot schedule is fully represented, with complete usage and retained response evidence. Accounting by provider-reported cost prevented the earlier ceiling estimate from prematurely ending the continuation.

**Efficacy result:** inconclusive. The campaign has no overall oracle passes because 142 semantic answers were not adjudicated. Its two deterministic patch failures are balanced across arms. Neither exit code, provider response, nor successful MCP call proves answer quality.

**Model-adequacy result:** this experiment cannot establish that Luna is inadequate or effective. It shows one deterministic patch failure in each arm and incomplete MCP use, while semantic quality for the other answers remains unknown.

A defensible efficacy conclusion requires blinded independent grading of the 142 `review_required` answers against the frozen rubrics, with arm labels hidden until grades are locked. The two deterministic failures should remain failures; retrospective grading should be reported separately from the immutable campaign records.

## Evidence

- Initial factory manifest and plan: `.artifacts/agent-efficiency/campaigns/codira-efficacy-campaign-020/`.
- Completion factory manifest and plan: `.artifacts/agent-efficiency/campaigns/codira-efficacy-completion-027/`.
- Initial execution, records, raw response bodies, log, and exit: `.artifacts/agent-efficiency/executions/luna020-20261004-r1/` (`pilot.exit` = 2; terminal status `budget_exhausted`).
- Completion execution, records, raw response bodies, log, and exit: `.artifacts/agent-efficiency/executions/luna027-20261005-r2/` (`pilot.exit` = 0; 86 new records, no pending attempts).
- Billing and continuation changes: commits `18f8e85`, `2822c77`, `9bb4620`, `387380d`. Completion readiness gate: 1,374 passed, 3 skipped, 86% coverage.

This analysis reconciles the preserved response bodies and immutable result records. It does not modify either campaign or supply the missing semantic adjudication.

## Forensic audit addendum — 2026-10-05

This addendum applies the evidence-first method used in the campaign 011 audit to the two Luna executions. It inspected the frozen attempt records, task prompts and rubrics, saved attempt events, before-workspace snapshots, submitted patch artifacts, and protected-command traces for the two deterministic failures. It did not alter campaign records, rerun a model, or make provider calls. The 020 interrupted `panel-u3-r01-codira-mcp` attempt remains retained as an earlier attempt; completion 027 remains the final slot outcome, as in the composite above.

### Grader and harness findings

The two deterministic failures are reproducible from the recorded patch artifacts and protected results. They are not 011-style oracle contract exceptions: the grader reached the patch checks and recorded concrete failure evidence. For `panel-f2-r01-codira-mcp`, patch validation and application passed, then the protected probe failed. For `panel-p3-r03-baseline`, patch application validation failed on the empty artifact, so the protected behavior probe was not run. The quality grader consistently left semantic rubric criteria as `review_required`; those statuses are the configured semantic boundary, not evidence of a grader crash or of an answer passing.

The offline readiness calibration remains a qualification of the grading pipeline on curated cases. It did not adjudicate these campaign answers and did not prevent either observed task failure. No systemic runtime, response-retention, usage-normalization, or composite-oracle defect was found in these two traces. This targeted audit does not constitute a source-grounded review of all 142 semantic answers, so their status remains `not_evaluated` and the campaign efficacy result remains inconclusive.

### Failure analysis

| Attempt | Trace-level failure | Root cause | Attribution |
| --- | --- | --- | --- |
| `panel-f2-r01-codira-mcp` | `git apply --check` and application passed; the protected command exited 1 with `AttributeError: 'Upper' object has no attribute 'capabilities'`. | The patch added a `case_conversion` boolean attribute to `Upper` and `Lower`, and made `Adapter.capabilities()` read that attribute. The task contract and protected probe require built-in plugins to expose the optional `capabilities()` interface themselves; the adapter must discover it and use a false fallback for legacy render-only plugins. The agent's added test checked only the adapter's attribute-based result, so it repeated the same mistaken interpretation and never exercised `Upper.capabilities()`. The readiness correct-case fixture implements plugin `capabilities()` methods and the protected probe passes against that contract. | Genuine implementation/contract miss. The attempt was assigned to the Codira-MCP arm but recorded zero MCP calls, so this failure provides no evidence that MCP retrieval was used or ineffective. |
| `panel-p3-r03-baseline` | `.benchmark/fix.patch` is zero bytes. `git apply --check` exited 128 with `No valid patches in input`; no protected behavior command ran. The attempt changed zero files. | The trajectory found the seeded defect (`Limit <= 0` rejects zero) and the baseline Go tests passed. It then tried to invoke an `apply_patch` shell command, which was absent from the isolated image. The attempt verified that the command was unavailable but did not switch to another way to produce the required patch. Thus this is failure to deliver a patch artifact; the attempt produced no code fix whose correctness could be assessed. | Genuine task-attempt failure caused by tool-use recovery failure. This was a baseline attempt with zero MCP calls; the trace does not show a provider, fixture-preparation, or grader failure. |

Both failures occurred in patch tasks, but they are in different tasks and opposite arms. The F2 failure is a behavioral contract miss after a valid patch was applied; the P3 failure is an absent patch after the agent failed to recover from an unavailable shell utility. They should not be collapsed into one model-quality cause or used to claim that either arm won. Across the 36 scheduled patch attempts, these are the two observed deterministic failures; the remaining protected checks passed, while semantic completeness for those patches still requires review.

### Updated interpretation

The forensic findings make the two concrete task failures actionable and rule out the specific kind of grader-contract defect found in campaign 011 for these attempts. They did not supply correctness grades for the other 142 answers at this checkpoint. The subsequent [semantic closeout](agent-efficiency-luna-semantic-review-2026-10-07.md) supplies separate retrospective reviews; the frozen `not_evaluated` results remain unchanged.
