# DeepSeek V4.1-Flash reviewer evaluation plan

Status: approved for persistence; execution pending authorization.

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

## 1. Verify the provider contract

Confirm the exact OpenRouter model ID, available providers, pricing, context
limits, supported parameters, reasoning controls, and usage reporting. Record
the verification date and avoid moving model aliases or silent model
substitutions.

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
