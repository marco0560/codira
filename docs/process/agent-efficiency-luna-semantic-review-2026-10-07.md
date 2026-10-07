# Luna Campaign 020 / Completion 027 semantic evidence closeout

## Findings

The reviewed composite has **65/72 baseline passes and 63/72 Codira-MCP
passes** under the frozen all-required rubrics and protected checks. The
assisted-minus-baseline pass-rate difference is −2.8 percentage points; a
2,000-resample bootstrap over 24 task means gives a 95% interval of −9.7 to
+4.2 points. This is not evidence of an answer-quality advantage.

All 142 answers received blinded source-grounded review: 128 pass and 14 fail
retrospectively. The two deterministic patch failures remain failures, yielding
128/144 final reviewed passes. Frozen results still contain 142
`not_evaluated` and two failures. Reviewed decisions cover 621 criteria:
597 supported, 20 missing and four contradicted. A failed overall rubric can
reflect missing grounding or coverage rather than a wrong implementation.

| Final-slot outcome | Baseline | Codira-MCP |
| --- | ---: | ---: |
| Retrospective rubric/protected pass | 65 | 63 |
| Semantic rubric failure | 6 | 8 |
| Preserved deterministic failure | 1 | 1 |
| Total slots | 72 | 72 |

Of 72 pairs, 61 pass in both arms, five fail in both arms, four pass only in
baseline and two only in the assisted arm. All unsuccessful slots remain in
quality counts and all-attempt spending. The repeated trajectories do not
create 72 independent task types.

### Resource use at matched reviewed quality

| Measure, 61 pairs where both arms pass | Baseline | Codira-MCP |
| --- | ---: | ---: |
| Input + output tokens | 25,565,750 | 24,419,184 |
| Provider-reported final-slot charges | $0.798761260 | $0.776750615 |
| Summed agent execution seconds | 7,502.890574 | 7,151.346987 |

The pooled totals are 4.5% fewer tokens, 2.8% lower charges and 4.7% less
agent execution time with assistance. These are descriptive reductions in a
subset selected by both arms passing, not a general efficacy or efficiency
estimate. Its mean paired token difference is −18,796.2 and median +8,835.
Equally weighting the 23 tasks represented in that subset gives **+5,891.7
tokens**, with a task-resampled 95% interval of **−98,108.3 to +115,433.9**.
The task weighting reverses the pooled mean's direction; the interval spans
substantial saving and overhead. The 11 excluded pairs, including all three
cursor/freshness pairs, are retained in `aggregate-r3.json` and the all-slot
quality table. This is not a claim of matched success on the excluded tasks.

## Source-grounded task results

Each row contains three attempts per arm. Passes combine separate semantic
adjudication with the unchanged protected result, where applicable.

| Task | Family / split | Baseline passes | Assisted passes |
| --- | --- | ---: | ---: |
| panel-d1 | diagnosis / development | 3 | 3 |
| panel-d2 | diagnosis / holdout | 3 | 3 |
| panel-d3 | diagnosis / holdout | 3 | 3 |
| panel-e1 | evidence / development | 3 | 3 |
| panel-e2 | evidence / holdout | 3 | 3 |
| panel-e3 | evidence / holdout | 0 | 0 |
| panel-f1 | feature / development | 3 | 3 |
| panel-f2 | feature / holdout | 3 | 2 |
| panel-f3 | feature / holdout | 3 | 3 |
| panel-i1 | impact / development | 3 | 3 |
| panel-i2 | impact / holdout | 2 | 1 |
| panel-i3 | impact / holdout | 3 | 3 |
| panel-n1 | navigation / development | 3 | 2 |
| panel-n2 | navigation / development | 2 | 1 |
| panel-n3 | navigation / holdout | 3 | 3 |
| panel-p1 | patch / development | 3 | 3 |
| panel-p2 | patch / development | 3 | 3 |
| panel-p3 | patch / holdout | 2 | 3 |
| panel-t1 | tracing / development | 3 | 3 |
| panel-t2 | tracing / development | 2 | 3 |
| panel-t3 | tracing / holdout | 3 | 3 |
| panel-u1 | usage / development | 3 | 3 |
| panel-u2 | usage / development | 3 | 3 |
| panel-u3 | usage / holdout | 3 | 3 |

The 14 semantic failures are:

- **Cursor/freshness, six:** all omit profile/page-size binding and pre-reindex
  modified-source expansion rejection required by the rubric beyond the prompt.
  Four also edit the wrapper instead of the requested `transform`; the other
  two cover the requested post-reindex experiment. Grounding is supported by
  identifiable source/commands and reported observations, with historical
  execution not independently replayed in this review.
- **Shared executor impact, three:** two omit the actual MCP proxy connection
  adapter; one attributes `execute` to `QueryDaemonIpcServer` rather than the
  `_QueryRuntime` protocol. Static inventory is distinct from dynamic coverage.
- **Method selection, three:** the correct lower method is named without
  source grounding or reproducible checks required by the generic rubric.
- **Alias navigation, one:** omitted explanation of the required object-valued
  enum payload; a declaration citation alone does not supply the explanation.
- **Profile tracing, one:** incorrectly puts default `.codira/config.toml`
  below output-dir instead of repository root.

The two deterministic failures are the unchanged F2 capability-interface miss
and P3 empty patch. Neither used MCP. Other passing answers can contain minor
precision or formatting issues that do not fail a required criterion; passing
this rubric is not certification of every incidental sentence.

## Review disagreements and rubric alignment

Initial reviewers recorded 120 semantic passes and 22 failures. Before labels
were joined, cross-review inspected all 16 failed sibling receipts and 30
passing sibling receipts, plus six of that reviewer's own cursor/freshness
decisions. It upheld the 40 other sibling decisions and produced 12 separate
amendments:

1. Six ignore patches changed from failure to pass. Their frozen rubric permits
   support from protected behavior. The retained independent probe verifies
   matching, nonmatching and ignored paths for all six; the prompt does not
   require an additional agent-authored nonmatching regression. The initial
   missing-substance/causal decisions imposed that extra condition. Probe source
   inspection and hash-verified protected results supported the correction.
2. Six cursor/freshness grounding decisions changed from missing to supported.
   Requiring a complete experiment script exceeded the rubric's allowance for
   actual source ranges or reproducible checks. Identifiable source expressions,
   index commands and concrete observations suffice for grounding, while their
   historical verification limitation remains. Overall outcomes stay failed
   for the separate substance/coverage requirements.

After that first locked analysis, a further rubric-scope check corrected two
Sentinel coverage failures. The original reviewer reconsidered only the opaque
packets, frozen source and named protected probe, without the packet-to-arm
mapping. Both patches add member-serialization and Option assertions; the
independent probe checks full-container copy/deepcopy/pickle name/default
preservation. Two fresh scratch-copy executions of that exact probe passed
under repository Python 3.13.13; they are host corroboration, not a replay of
paid execution. The frozen prompt requires behavior preservation and regression
tests, without prescribing an agent-authored full-container pickle test. The
initial coverage decisions imposed that stronger test-form requirement.

These two additional appended amendments produce the final **128/14** semantic
split and **65/72 versus 63/72** composite. There are **14 amendments total**.
The first analysis/lock remain retained; `aggregate-r3.json` and
`review-lock-r3.json` bind the final set. The intermediate round-2 aggregation
missed the suffixed scope-review filenames and is explicitly superseded; it
does not supply final counts. Initial grades, amendments and all original
campaign records remain intact.

Amendments include prior review digests,
exact unchanged packet bindings, evidence and reasons. An independent 24-task
prompt/rubric scope audit records extra or ambiguous requirements, including
cursor/freshness and full-Option regression wording. No frozen rubric was
edited to obtain a favorable result. Those ambiguities limit pass-rate
interpretation and should be resolved prospectively before a new campaign.

## Scope and method

This is a retrospective review of the existing 144-slot representative
composite, not a new model execution. It preserves the 142 frozen
`not_evaluated` / `semantic_review_required` results and the two deterministic
failures. Reviewed quality is reported separately from operational success and
the original task-oracle state. Original attempts, answers, patches, provider
responses and rubrics are unchanged.

All 142 saved quality packets were checked against the submitted artifact and
the factory-bound frozen task/oracle fingerprints. Packets were assigned opaque
random IDs and grouped by task for consistent source review. Three separate
reviewer contexts received the complete answers, unchanged frozen rubrics,
exact prompts and copied frozen source. They did not receive arm/model labels,
usage, previous grades or the mapping to original attempts. Each reviewer read
every assigned answer and recorded one decision and source-grounded reason for
each criterion. Repository adjudication helpers enforce exact answer/rubric
digests, complete criterion coverage and verbatim supporting quotes; they do
not themselves prove that a semantic judgment is correct.

The initial reviews are write-once. An independent cross-review checks failed
decisions and a sample of passing answers before the labels are joined. Any
disagreement requires a separate traceable receipt; original reviewer decisions
are not overwritten. Review receipts are locked by digest before deriving
arm-aware measurements. The two protected patch failures stay failures in
every comparison, and the interrupted parent attempt remains outside final
slot counts but inside total execution spending.

## Input integrity and accounting

The input audit verified 145 retained records and event streams, 2,021 exact
provider-response digests and reported charges, 144 protected trace manifests,
212 protected command-output digests and 25,434 frozen source-file comparisons.
One backend session scratch-file path was excluded from six source comparisons. The
selected legacy composite's 180 record/event/answer digests were also rechecked.
Common model/effort, runtime image/profile/source, resource and treatment
controls and task/fixture fingerprints match between 020 and 027; continuation
harness and billing identities differ. Provider alias identity across the two
execution dates is not established by a shared model name.

| Cost scope | Baseline | Codira-MCP | Total |
| --- | ---: | ---: | ---: |
| Final 144 slots | $1.006187230 | $1.020210140 | $2.026397370 |
| Interrupted parent attempt | — | $0.006405485 | $0.006405485 |
| All task-execution attempts | $1.006187230 | $1.026615625 | $2.032802855 |

These are provider-reported response charges, not invoices. Readiness canaries
and index/environment preparation are separate. The earlier combined report's
assisted cost includes the interrupted attempt; final-slot efficiency comparisons
must use the first row. Its frozen grades and operational observations remain
valid. See the [execution report](agent-efficiency-luna-combined-campaign-results-2026-10-05.md)
for the original accounting and two patch failure diagnoses.

## Interpretation boundaries

Blinding hides external labels, not the content of the answer: some answers
mention Codira tools, commands or environment details. Those cues remain intact
and limit claims of perfect masking. Reviewers are separate agent contexts,
not independent human panels or independently trained graders. Each task's
repetitions use the same reviewer; reviewer differences can affect between-task
counts. Source review can establish code behavior and check cited facts, but
does not independently replay every historical indexed experiment or executable
example. Self-reported runs must not be presented as newly verified execution.

Frozen rubrics are applied as written, including requirements stricter than
the corresponding prompt. Such mismatches are reported explicitly rather than
retroactively repairing the rubric or converting an answer into a pass. A
failure of a rubric-only condition must not be described as failing an explicitly
requested task condition. Missing evidence is separate from a false claim.

Pass differences describe assignment to optional Codira-MCP assistance. Only
23 of 72 assisted attempts made any MCP call, and baseline also had ordinary
shell facilities. This does not estimate the effect of actually using MCP;
an adoption-conditioned subset would be selected after treatment. Token/cost
efficiency is compared at matched reviewed quality, with excluded pairs and
recovery spending retained separately. Bootstrap uncertainty resamples task
means, not the three repeated trajectories as independent problems. The fixed
24-task bank, six fixtures and small synthetic controls restrict generalization.

## Reproducibility and retained evidence

The private durable review identity is
`.artifacts/agent-efficiency/analysis/luna-semantic-review-20261007-r1/`:

- `prepare.py` verifies the final selection, task/oracle fingerprints and saved
  answer packets; creates new opaque packets and source copies; and retains
  provenance in `private-register.json`, unavailable to blinded reviewers.
- `audit.py` verifies immutable input digests, source parity, protected streams,
  common controls and provider-reported spending in `input-audit.json`.
- `blind/group-*/reviews/` retains exact digest/quote-bound reviewer receipts.
- `aggregate.py` validates every receipt, locks the complete review set and only
  then joins labels and computes reviewed paired summaries.
- `blind/cross-review-3.json` and `blind/rubric-scope-review-2.json` retain
  independent decision and requirement-alignment audits; `amendments/` under
   the relevant groups retains the initial 12 appended corrections.
- `blind/protected-p2-supplement.json` records the label-hidden protected-probe
  source and retained trace/output digests supplied during disagreement review.
- `blind/group-1/p1-scope-review-1.json` and its protected verification receipt
  retain the further two scope corrections and independent host probe checks.
- `aggregate-r3.py`, `review-lock-r3.json` and `aggregate-r3.json` retain final receipt hashes,
  reviewed outcomes, 72 pair deltas, task counts and bootstrap parameters.
  Earlier locks and aggregates are preserved as superseded analysis records.
- `all-pair-recheck.json` records the corrected 38/34 token-delta signs and
  a reproducible seed-53, sorted-task bootstrap for the earlier execution report.
- `verify.py` revalidates retained record, packet, review and copied-source
  digests, the report's 24 task rows and local document links without writes.
- `legacy-claim-review-1.json` checks the older reports, all 17 named-identity
  acceptances, completion exclusions and legacy protocol attribution against
  original evidence. Legacy specified-check success remains distinct from
  comprehensive semantic quality.

Run these scripts through the repository environment with `PYTHONPATH=.`.
Preparation, audit and aggregation create new output files exclusively; rerun
verification against the saved receipts rather than overwriting this identity.
Original evidence remains under `executions/luna020-20261004-r1/` and
`executions/luna027-20261005-r2/`. No new provider request or paid campaign is
needed to review these retained outputs.


## Independent verification and validation

Final independent receipts `legacy-corrections-review-1-final.json`,
`final-amended-claim-review-2.json` and `documentation-final-review-3.json`
verify legacy attribution, raw evidence, all final adjudications and amendments,
24 task rows, paired estimates, bootstrap intervals and local links. The
reproducible `final-amended-verify-2.py` independently recomputes final results;
`verify.py` checks retained digests and report consistency.

The repository gate passed with exit `0`: 1,394 tests passed, three skipped,
86% coverage and no blocking Semgrep findings. `validation-receipt.json`
records timing and the retained log digest; gate evidence is under
`.artifacts/validation/repo-gates/issue053-closeout-20261007-r1/`.
Final rubric-scope and report corrections occurred after the full code gate
and received focused integrity, table, link and noncode verification.
No original campaign record or provider response was changed.
