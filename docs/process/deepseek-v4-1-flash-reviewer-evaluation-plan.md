# DeepSeek V4.1-Flash reviewer evaluation plan

Status: `r2`–`r5` are terminal non-comparative records. `r5` passed its fresh
preflight and repository gate, but its first Grok response failed the literal
verdict parser before a valid attempt could be recorded. It produced no paired
evidence and cannot support a replacement decision.

Approved on: 2026-09-15.

## Objective and scope

Determine whether DeepSeek V4.1-Flash can replace `x-ai/grok-build-0.1`
in `scripts/run_agent_efficiency_phase6_review.py` while preserving useful
defect detection, reliable verdicts, and reproducible evidence.

This evaluation concerns the supplemental independent reviewer. Changing the
model constant alone is not yet established as sufficient: parameter support,
reasoning behavior, response parsing, and accounting require verification.

Approval authorizes saving this plan only. Implementation and paid evaluation
require subsequent authorization. A default-model switch requires a separate
approval informed by the evaluation results.

## Implementation checkpoint (2026-09-16)

The bounded evaluator, frozen six-diff corpus, response-admission checks, and
credential-free provider/cost preflight have been implemented and validated by
the repository gate. The refreshed preflight reproduced all six diffs, verified
both exact model IDs plus `max_tokens` and reasoning support, and estimated a
USD 1.6071094 worst-case cost for the 24-request trial using one token per
prompt character.

One earlier provider-request attempt ended after its timeout without a durable
per-attempt record or raw response. Its completion and billing state are
unknown. It is not trial evidence. The evaluator now fails closed on any prior
state, atomically claims the `r2` identity, verifies the scoped key can cover
the conservative estimate, and requires explicit execution. The operator
authorized the new USD 2-capped trial on 2026-09-16. Its ignored artifacts are
kept under a distinct `r2` identity root rather than replacing the earlier
attempt's surviving preflight record.

`r2` verified a USD 3.00 scoped-key limit with USD 2.8660008 remaining before
its first request. That request reached the local response-admission boundary
but yielded no admitted review, raw response, or usage record. It is terminal
with zero completed attempts and unknown provider billing. The response parser
now opts into OpenRouter router metadata and obtains provider identity from the
documented successful-attempt record. A new identity and authorization are
required before another paid request.

`r3` verified the same USD 3.00 key limit and failed before retaining a review
or usage record. Its non-billing post-run key check still reported USD 3.00
remaining and USD 0.00 daily usage. The evaluator now preserves only a safe
HTTP status for future transport failures, enabling diagnosis without retaining
an error body, review text, or credential.

The `r4` diagnostic used its own ignored artifact root and atomically recorded
one pre-request state. It submitted only the first frozen known-defect case to
the Grok control model, then terminated with safe failure category `HTTP 400`.
The post-run non-billing key check remained USD 3.00 available with USD 0.00
daily usage, so it has zero observed provider usage. It cannot produce a
DeepSeek-versus-Grok conclusion or authorize a later request.

The subsequent authenticated model catalog established the cause: the scoped
key exposes Grok as mandatory-reasoning, while `r4` incorrectly requested
`reasoning.enabled: false`. The helper now preserves each model's provider
default and requires authenticated model admission before any future completion.

The operator subsequently authorized the fresh
`phase6-deepseek-v4-1-flash-r5-20260917` trial. It uses the corrected request
contract, a new ignored artifact root, and the original frozen 24-request cap;
it must stop at the first incomplete or unverified result.

`r5` stopped after its first Grok control response with `independent review
verdict is malformed`; there were zero completed attempts. The then-current
helper discarded the response body when validation failed, so the precise model
format cannot be recovered from this immutable record. This is a protocol
defect, not evidence about either model's review quality. The helper now writes
every received provider body into the ignored per-attempt artifact before
semantic validation and records only its path and SHA-256 in terminal state.
Any future experiment requires a new identity and explicit authorization.

## 1. Verify the provider contract

Confirm the exact OpenRouter model ID, available providers, pricing, context
limits, supported parameters, reasoning controls, and usage reporting. Record
the verification date and avoid moving model aliases or silent model
substitutions.

Use authenticated `/models/user` for key-specific availability and reasoning
requirements; public `/models` is only a model-wide capability and price source.

## 2. Prepare a frozen comparison set

Select six historical diffs: three with independently confirmed defects and
their three corrected counterparts.

Cover path safety, credential separation, protected grading, immutable records,
and failure handling where historical evidence permits. Freeze base/head SHAs
and diff hashes. Define expected findings before submitting requests; previous
Grok verdicts alone are not ground truth.

## 3. Make the review helper evaluation-ready

Add explicit model selection while retaining Grok as the default. Support
reproducible historical inputs and record request settings, model/provider
identity, timing, usage, and cost.

Tighten verdict handling: malformed output, truncation, and transport errors
must be recorded as failures rather than interpreted as valid review verdicts.
Preserve the scoped SOPS credential workflow.

## 4. Run a bounded paired trial

Use identical review evidence and instructions for both models:

- Six diffs × two models × two repetitions: **24 requests maximum**.
- Proposed total spending ceiling: **USD 2**, subject to a preflight estimate.
- Set explicit output and timeout limits; count failed requests toward the
  budget.
- Stop if model identity or required accounting cannot be verified.

Keep raw evidence outside Git; persist only safe summaries and reproducibility
metadata.

## 5. Assess suitability

Report per-case results, including:

- Confirmed defects detected and missed.
- Unsupported findings on corrected diffs.
- Verdict-format reliability and run-to-run consistency.
- Latency and cost per usable review.

### Acceptance gate

DeepSeek must detect every designated critical defect in both repetitions,
match or exceed Grok's confirmed-defect coverage, produce no more unsupported
findings, and return valid, complete verdicts for all 12 attempts.

Treat this as a small operational qualification, with any disagreements
inspected against code and tests.

## 6. Validate and recommend

Run focused helper tests and the required repository gate:

```bash
uv run python scripts/validate_repo.py
```

Produce a recommendation to replace Grok, retain it, or expand the evaluation.
A default-model switch follows a separate approval informed by those results.
