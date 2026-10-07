# Issue 53 audience findings: legacy and representative campaigns

Updated: 2026-10-07. Scope: legacy Campaign 006 / Completion 009 and newer
representative Campaign 020 / Completion 027. Independent evidence closeout
is complete; no publication is implied.

## Latest representative finding

After blinded retrospective review, the 144-slot Campaign 020 / Completion 027
composite has **65/72 baseline passes and 63/72 assisted passes** under its
frozen all-required rubrics and protected checks. The assisted-minus-baseline
difference is −2.8 percentage points; a task-resampled 95% bootstrap interval
is −9.7 to +4.2 points. This does not establish an answer-quality advantage.
The 142 semantic answers have 128 reviewed passes and 14 reviewed failures;
two additional deterministic patch failures remain failures, one per arm.
Frozen `not_evaluated` records are unchanged by these separate reviews.

Among 61 pairs where both arms pass reviewed quality, baseline → assisted totals are
25,565,750 → 24,419,184 tokens, $0.798761260 → $0.776750615 in provider-reported
charges, and 7,502.9 → 7,151.3 seconds of summed agent execution. These are
descriptive reductions of 4.5%, 2.8% and 4.7% respectively, not a general
efficiency claim. The median paired token change is +8,835; the equally
weighted mean over 23 represented tasks is +5,892 tokens with a 95% bootstrap
interval of −98,108 to +115,434. Weighting and outcome selection change the
summary; uncertainty spans both benefit and overhead. The other 11 pairs
remain in the all-slot quality results and retained spending.

The deployed runtime passed item/cursor, generation and source-evidence
qualification. This is separate from the older legacy-runtime experiment below;
results from the two treatment protocols must not be pooled. See the
[semantic closeout](agent-efficiency-luna-semantic-review-2026-10-07.md) for all
24 task results, amendments, selection and source-grounded failure findings.

All task-execution spending was $2.032802855 in provider-reported charges.
That includes $0.006405485 for the interrupted parent attempt, which is preserved
but excluded from final-slot counts. Final-slot costs are $1.006187230 baseline
and $1.020210140 assisted. These differ from both readiness costs and the
ceiling-priced estimates in the legacy experiment.

Only 23/72 assisted attempts called MCP: this measures assignment to optional
assistance, not the effect of actually calling MCP. The fixed task bank,
synthetic controls, rubric/prompt mismatches, imperfect answer masking and
separate agent reviewers restrict interpretation. Operational completion,
successful tool calls and passing named checks do not establish comprehensive
semantic quality, general productivity or model ranking.

## Legacy composite finding and protocol correction — 2026-09-30

The selected 60 results form a completed retrospective composite. Codira
assistance reduced shell exploration but did not demonstrate an overall task
quality or efficiency advantage on the tested tasks. Both arms met the
specified checks after the documented retrospective text adjudication. The
assisted arm used 11.5% more tokens, cost 11.6% more at the frozen price
ceilings, and accumulated 12.1% more agent execution time.

The subsequent forensic inspection found an essential limitation absent from
the initial quantitative response: **the pinned image ran the older Codira
context protocol, not the current item-and-cursor implementation**. The image
contains Codira `2.0.2.post1.dev49`; its context method accepts `query` and
`output_budget`, and returns `result.context`. The current checkout accepts
`cursor`, `limit`, and `search_profile`, returning `result.items` and page
metadata. Every successful saved context call used the older shape. The
Codira source fixture contained the new implementation and its regression
test, but that source was the object of investigation, not the installed MCP
runtime. Finding the new test therefore did not exercise the new protocol.

The numbers below remain valid for the deployed treatment. They cannot be
used to judge the effectiveness of the current pagination changes. See the
[internal product assessment](issue-053-internal-product-assessment.md) for
runtime evidence, answer review, and recommendations.

## Experiment and provenance

Six fixed tasks were repeated five times in both arms, giving 30 pairs and
60 selected attempts. The model identifier was `openai/gpt-6-luna`, through
OpenRouter Responses, with high reasoning. Both arms had ordinary shell
facilities and fresh isolated workspaces. The assisted arm additionally had
Codira MCP and instructions requiring index readiness and an initial indexed
query. This tests that assistance protocol, not unconstrained optional tool
use.

Campaign 006 supplied 54 operationally completed attempts. Completion 009
supplied six results: a replacement for the failed fifth Codira patch attempt
and the five originally unstarted slots. No completed parent answer was rerun.
All original records, including the unsuccessful paid patch attempt, remain
immutable. Fixture fingerprints, selected task fingerprints, model controls,
runtime image, and runtime profile match between the parent and supplement.
Host harness fingerprints differ; text oracles were revised. Each supplemented
pair has both arms from Completion 009. This composite is a retrospective
diagnostic, not one homogeneous execution under a single scoring revision.

The source specifications are
[campaign 006](https://github.com/marco0560/codira/blob/main/benchmarks/agent-efficiency/campaign-specs/codira-efficacy-campaign-006.json)
and [completion 009](https://github.com/marco0560/codira/blob/main/benchmarks/agent-efficiency/campaign-specs/codira-efficacy-completion-009.json).
The fixtures are the admitted public Codira, Click, and Picomatch snapshots;
repetitions are repeated tasks, not 30 independent repository problems.

## Overall measurements

| Measure, 30 selected attempts per arm | Baseline | Codira MCP | Assisted difference |
| --- | ---: | ---: | ---: |
| Tokens | 7,960,188 | 8,877,307 | +11.5% |
| Estimated cost at frozen ceilings | $2.07931500 | $2.32132775 | +11.6% |
| Sum of agent elapsed times | 2429.2 s | 2722.1 s | +12.1% |
| Provider response requests | 340 | 365 | +7.4% |
| Shell commands | 533 | 334 | -199 |
| Nonzero-exit shell commands | 85 | 74 | -11 |
| MCP calls | 0 | 143 | All 30 assisted attempts used MCP |
| Retrospective specified task checks | 30/30 | 30/30 | No demonstrated pass advantage |

These elapsed times measure individual agent container execution. They are not
campaign wall-clock duration, and this table does not add environment
preparation, index preparation, or protected grading time. Index preparation
has saved traces but no directly comparable separate timing field here.
Nonzero shell exit is not synonymous with an agent error: intentional
reproductions and `git diff --no-index` also return nonzero.

Cost is computed as `(input_tokens * 0.25 + output_tokens * 0.75) / 1,000,000`.
It uses frozen admission ceilings and prices cached input at the same ceiling;
it does not apply provider caching discounts or constitute an invoice.
Cached tokens are included in token totals. Both agent effort and estimated
spending must therefore be distinguished from provider billing.

Codira consumed fewer tokens in 13/30 pairs, lower estimated cost in 12/30,
and less agent time in 14/30. The median paired token difference was +21,008;
the median paired elapsed difference was about +5.0 seconds. Fewer shell
commands alone did not yield lower overall resource use.

## Task results

The percentages below compare five assisted attempts with five baseline
attempts for the same task. Positive values mean more assisted resource use.

| Task | Baseline tokens | Assisted tokens | Token difference | Cost difference | Agent-time difference |
| --- | ---: | ---: | ---: | ---: | ---: |
| Picomatch architecture | 1,279,904 | 1,368,550 | +6.9% | +7.8% | +28.8% |
| Context implementation and regression test | 1,574,482 | 1,529,969 | -2.8% | -2.7% | -10.7% |
| Picomatch usage guide | 1,332,583 | 1,103,425 | -17.2% | -16.8% | +4.4% |
| MCP adapter contract impact | 1,555,489 | 1,753,918 | +12.8% | +12.4% | -3.4% |
| Click Sentinel diagnosis | 940,767 | 1,528,504 | +62.5% | +62.0% | +56.7% |
| Click Sentinel source fix and regression test | 1,276,963 | 1,592,941 | +24.7% | +24.4% | +21.8% |

Context identification had the clearest combined benefit: modest token and
cost reductions, and 10.7% lower aggregate agent time. Documentation reduced
tokens and estimated cost substantially, with a small time increase. Impact
was slightly faster but costlier. Architecture was mixed, with aggregate time
higher. Sentinel diagnosis was consistently worse on resource use in all five
pairs. Patching was dominated by the fifth selected assisted attempt: the
first four patch pairs together cost about 4.3% more with Codira, whereas the
fifth selected pair cost nearly twice as much.

The original 27 complete pairs already had about 8.8% higher assisted estimated
cost. Recovery increased the overhead; it did not create the entire pattern.
The detailed Sentinel causes and output quality are reviewed in the internal
assessment rather than inferred from token totals.

## Frozen grades, retrospective review, and actual failures

Campaign 006 retains 55 records: 54 operational completions and one local
reservation failure. Of the completed attempts, 37 passed their frozen
oracles and 17 failed exact-text rules; five scheduled attempts had no record.
Manual adjudication found all 17 rejected text answers supplied the requested
identifiers and paths. A read-only replay of all 28 completed text answers
under revised rules passed 28/28. Completion 009's six new results passed.
Thus the selected composite contains 43 frozen passes and 17 frozen text
failures, while all 60 satisfy the documented retrospective specified checks.
Neither description overwrites the historical records.

The original fifth assisted patch received 23 successful upstream responses,
consuming 707,926 tokens and $0.18740500 at the ceilings. The local proxy
rejected request 24 with `session_token_reservation_exceeded` before measured
usage reached one million tokens; this was not evidence of provider throttling
or $10 pool exhaustion. Its malformed editing trajectory also lacked a
complete patch and regression test. The replacement used 540,874 tokens and
passed protected grading, compared with 275,416 tokens in its paired baseline.
A successful new trajectory does not establish that the stopped one would
have converged.

See the [original adjudication](agent-efficiency-campaign-006-adjudication-2026-09-30.md)
and [completion report](agent-efficiency-completion-009-results-2026-09-30.md).
The broader answer review found substantive diagnoses and useful guides, but
also impact completeness gaps and a shared empty-flags prose omission that
the identifier oracles could not score.
The current text checks must not be described as comprehensive quality grades.

Total spending across both executions was **$4.58804775** at the ceilings.
The selected composite accounts for **$4.40064275**; the remaining $0.18740500
is the preserved unsuccessful patch attempt. No additional paid call was made
for this forensic analysis.

## Claims supported by this experiment

A defensible descriptive claim is: on these six repeated public-fixture tasks,
under the deployed older MCP runtime and required-use protocol, Codira
assistance reduced shell exploration by 37.3%, while increasing aggregate
model tokens, ceiling-priced cost, and agent execution time. Both arms met
the specified task checks after retrospective text adjudication.

The experiment does not establish a general productivity gain, an advantage
in comprehensive answer quality, or the effectiveness of the current context
pagination implementation. It also does not establish that a different model
would improve the comparison. Five repetitions characterize trajectory
variation on six tasks; they do not create broad task or repository coverage.
Model/provider deployment details could also change behind a fixed identifier.

## Reproduction and evidence

The immutable generated plans and result records are under
`.artifacts/agent-efficiency/campaigns/` and
`.artifacts/agent-efficiency/executions/c006/` and `c009/` respectively.
The derived read-only analysis is retained under
`.artifacts/analysis/c006-c009-forensic-20260930/`:

- `analyze.py` reconstructs the 60-slot selection and derived statistics.
- `metrics.json` records result, transcript, and answer byte digests with
  repository-relative evidence paths, all per-attempt metrics, and MCP summaries.
- `guide-example-checks.json` records 31 independently executed guide blocks,
  all 73 expected boolean outcomes, and the host Node version.
- `guide-claim-probes.json` records three additional checks of the flags
  precedence prose, including the empty-string exception omitted by six guides.
- `runtime-inspection.json` records offline cached-image identity, package
  version, method signature, and adapter/server source hashes.

Recompute the derived records with:

```bash
uv run python .artifacts/analysis/c006-c009-forensic-20260930/analyze.py
```

This reads original artifacts, invokes local Node to corroborate guide examples,
and writes only the derived analysis directory. It invokes no agent or provider.
The guide check is host-Node corroboration, not a replay in the paid runtime.
Raw provider responses and full transcripts remain ignored and immutable.
This tracked report contains no credentials or paths outside the repository.

## Appendix: all 30 paired measurements

Deltas are assisted minus baseline; negative values favor the assisted arm.
The source column identifies the selected pair's execution provenance.

| Pair | Source | Token delta | Ceiling-cost delta | Agent-time delta |
| --- | --- | ---: | ---: | ---: |
| `architecture-001-r01` | c009 | +164,950 | $+0.04344200 | +43.65 s |
| `architecture-001-r02` | c006 | -110,033 | $-0.02740475 | -3.75 s |
| `architecture-001-r03` | c006 | -57,049 | $-0.01471475 | -0.16 s |
| `architecture-001-r04` | c006 | -96,362 | $-0.02436000 | -0.01 s |
| `architecture-001-r05` | c006 | +187,140 | $+0.04883000 | +52.55 s |
| `context-page-001-r01` | c006 | +52,767 | $+0.01265225 | -23.65 s |
| `context-page-001-r02` | c006 | -28,909 | $-0.00722475 | +3.05 s |
| `context-page-001-r03` | c006 | -37,634 | $-0.00837200 | -5.53 s |
| `context-page-001-r04` | c006 | -7,982 | $-0.00143850 | +6.89 s |
| `context-page-001-r05` | c006 | -22,755 | $-0.00649625 | -37.28 s |
| `documentation-001-r01` | c006 | -91,465 | $-0.02337975 | -14.49 s |
| `documentation-001-r02` | c006 | +57,532 | $+0.01485950 | +12.14 s |
| `documentation-001-r03` | c006 | +38,077 | $+0.01050975 | +28.14 s |
| `documentation-001-r04` | c006 | -66,972 | $-0.01759800 | -8.58 s |
| `documentation-001-r05` | c006 | -166,330 | $-0.04246350 | -2.94 s |
| `impact-001-r01` | c006 | +268,626 | $+0.06919000 | +57.31 s |
| `impact-001-r02` | c006 | +67,617 | $+0.01693975 | -7.65 s |
| `impact-001-r03` | c006 | +2,502 | $+0.00042900 | -14.18 s |
| `impact-001-r04` | c006 | -1,797 | $+0.00052275 | +13.03 s |
| `impact-001-r05` | c009 | -138,519 | $-0.03658875 | -66.21 s |
| `localize-001-r01` | c006 | +67,454 | $+0.01749250 | +23.12 s |
| `localize-001-r02` | c006 | +172,176 | $+0.04427000 | +43.14 s |
| `localize-001-r03` | c006 | +124,355 | $+0.03244725 | +32.51 s |
| `localize-001-r04` | c006 | +125,741 | $+0.03261125 | +32.55 s |
| `localize-001-r05` | c006 | +98,011 | $+0.02555725 | +35.65 s |
| `patch-002-r01` | c006 | +53,738 | $+0.01480800 | +25.31 s |
| `patch-002-r02` | c006 | +10,091 | $+0.00051775 | -18.02 s |
| `patch-002-r03` | c006 | -45,234 | $-0.01196050 | -1.02 s |
| `patch-002-r04` | c006 | +31,925 | $+0.00811725 | +10.60 s |
| `patch-002-r05` | c009 | +265,458 | $+0.07081800 | +76.67 s |

## Validation status

The derived analysis verified all 60 logical slots against the frozen parent
schedule, complete usage and operational status, and all 73 guide outcomes.
Source-level output review and runtime inspection are recorded in the internal
assessment. The full repository gate passed with exit `0`, 1,204 tests passed,
three skipped, and 86% coverage. Durable evidence is
`.artifacts/validation/repo-gates/phase8-assessment-20260930/validation.log`
and `validation.exit`. Report links, whitespace, privacy, and recommendation
counts were also checked. The independent claim review is now complete; the 2026-10-07 closeout
record below supersedes this historical validation checkpoint.


## Closeout validation — 2026-10-07

Separate reviewers verified the legacy claims, the final 142 answer reviews and
14 appended amendments, all 24 task rows, paired estimates and their uncertainty,
cost scopes, source attribution and local links. Final receipts are retained in
`.artifacts/agent-efficiency/analysis/luna-semantic-review-20261007-r1/`;
the [semantic review](agent-efficiency-luna-semantic-review-2026-10-07.md)
documents methods and limitations.

The full repository gate passed: exit `0`, 1,394 tests passed, three skipped,
86% coverage and no blocking Semgrep findings. Log and exit evidence are retained
under `.artifacts/validation/repo-gates/issue053-closeout-20261007-r1/`.
Final documentation corrections after the full gate received focused integrity,
table, link and noncode checks. Phases 7–8 are complete and issue #53 is ready
for closure; publication and GitHub closure have not been performed.
