# Phase 6 r7 reviewer evaluation report

Status: complete on 2026-09-18. This is a valid paired **reviewer-transport**
comparison, not an Issue #53 Codira-efficiency measurement.

## Scope correction

This report does not answer whether Codira is useful as a token-saving device.
Issue #53 measures provider-reported tokens for successful, paired repository
tasks with and without Codira MCP; it is model-agnostic at the product level.
This experiment instead tested two models' responses to a small, partial-diff
review corpus. It neither exercised Codira MCP as the treatment nor used the
Issue #53 task-oracle success contract.

Accordingly, the results below are limited to the evaluator helper's transport,
accounting, and response-admission behavior. They must not support a model
replacement decision, a model-quality ranking, a Codira product claim, or a
decision to launch Phase 7.

## Phase 6 chronology and prior results

The records below are retained because they explain the controls used by r7.
They are not pooled with r7 or used to make a model-quality conclusion.

| Record | Completed paired attempts | Result | Evidentiary status |
| --- | ---: | --- | --- |
| Initial attempt | 0 | Timed out without a durable per-attempt record. | Provider completion and billing unknown; non-comparative. |
| r2 | 0 | First Grok request failed local admission; no raw body or complete usage remained. | Non-comparative; provider billing unknown. |
| r3 | 0 | Failed before a review or usage record; the post-run key check showed USD 0.00 daily usage. | Non-comparative; zero observed provider usage. |
| r4 diagnostic | 0 | One Grok request received HTTP 400. Authenticated catalog evidence later showed that the request disabled mandatory Grok reasoning. | Non-comparative; zero observed provider usage. |
| r5 | 0 | First Grok response failed the old literal verdict parser; its body was not retained by that version of the helper. | Runner defect, not model-quality evidence. |
| r6 | 2 Grok only | Strict-schema calibration admitted both models; the paired run then stopped when DeepSeek returned `finish_reason: length` with null content after reasoning consumed the 12,000-token allowance. Grok also reported completion usage above that old requested cap. | Incomplete and non-comparative. It motivated raw-body retention, finish-reason-first classification, provider-cap rejection, and representative long-diff calibration. |
| r7 | 24 | Full paired comparison completed with exact-model, strict-schema, no-fallback, accounting, and cap evidence. | The only comparative result. |

The r7 artifact roots also preserve two pre-completion administrative records:
the first calibration launch refused the then-hard-coded r6-only artifact path,
and the first comparison launch refused insufficient key budget. Neither reached
a provider completion. Their repaired successors used distinct `-r2` artifact
identities, following the no-resume rule.

## Controls and evidence

- Frozen corpus: six immutable diffs, each reviewed twice by each model (24
  requests).
- Grok: `x-ai/grok-build-0.1`; DeepSeek:
  `deepseek/deepseek-v4.1-flash` with `reasoning_effort: "none"`.
- Each request required the exact model, no fallback, required parameters,
  strict JSON output, a 50,000-token cap, and a 300-second request timeout.
- Calibration succeeded for both models before comparison. The ignored artifact
  roots retain raw responses, provider identity, usage, request settings, and
  terminal state.
- Comparison artifact: `phase6-deepseek-v4-1-flash-r7-20260918-comparison-r2`.
  It completed all 24 attempts with no malformed, truncated, over-cap, or
  unaccounted response.

## Results

| Model | Verdict matches | Known-defect term matches | Corrected cases passed | Actual cost | Total latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| Grok Build 0.1 | 6/12 | 0/6 | 0/6 | USD 0.51795320 | 2,924.62 s |
| DeepSeek V4.1 Flash | 6/12 | 5/6 | 0/6 | USD 0.01907868 | 730.11 s |

The six verdict matches for each model are the six known-defect reviews. Both
models returned `NEEDS_FIXES` for every corrected diff. That outcome cannot be
classified as a false positive from this corpus alone: the prompt asks for a
broader review while each case supplies only a partial diff, so a response may
reasonably identify an unproven surrounding concern. Likewise, the expected
finding terms are corpus labels, not an independently adjudicated measure of
review completeness. Grok did not match the required terms in the six
known-defect reviews; DeepSeek matched five of six, missing one repeat of
`synthetic-git-defect`. Those are only rubric-observation counts.

Calibration cost was USD 0.05788593; comparison cost was USD 0.5370318812;
total observed r7 provider cost was USD 0.5949178112.

## Decision

No model-selection decision follows from r7. The experiment confirms that the
reviewer helper can preserve and account for 24 bounded responses under its
specified controls. It does not establish reviewer quality or the suitability
of DeepSeek as a replacement for Grok, because its semantic oracle is not
aligned with a whole-change code-review claim.

The Issue #53 next step is an evidence-first analysis of the six immutable
Pilot 018 task records and their oracle failures. Its purpose is to redesign
and validate a minimal successful-pair pilot before any new paid benchmark run.
No further reviewer comparison is implied.
