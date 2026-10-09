# Optional LLM retrieval grading

The known-target benchmark needs no manual grading. This optional script adds
an independent assessment of relevance using one OpenRouter judge. It reads a
completed comparison and leaves its measurements and known-target scores intact.
It runs no agents, tools, containers or campaign matrix.

For each query, it deduplicates the union of the models' top ten results,
extracts bounded snippets from the frozen source, and makes one completion.
The judge sees the query and shuffled snippets, without embedding model names,
rank positions or expected targets. Scores are 2 (directly useful), 1 (related),
0 (irrelevant), or -1 (insufficient evidence). Snippets are treated as data,
including any instructions they contain.

These are LLM judgments, not verified ground truth. The report includes
precision lower bounds, direct-hit rates and pooled nDCG at 1, 5 and 10, with
repository and intent breakdowns. The pool is non-exhaustive, so these scores
cannot establish global recall. Unknown judgments score zero in lower-bound
metrics; missing queries remain in the planned denominator. No model is promoted.

## Prepare after the comparison finishes

Run from the Codira repository with its `uv` environment. Preparation refuses
an active comparison or an index with missing searchable bindings. It verifies
saved retrieval evidence and source files before freezing the grading inputs.
The original binding-loss run is unsuitable; use the corrected completed run.

Replace `PROVIDER/MODEL` and `BUDGET_USD` with your selected judge and budget.
Use a fresh output directory for every change to inputs or controls.

```bash
uv run python -m scripts.grade_retrieval_quality prepare \
--run .artifacts/benchmarks/retrieval-quality/runs/known-target-full-20261008-v2 \
--output .artifacts/benchmarks/retrieval-quality/grades/known-target-20261008-v1 \
--judge-model PROVIDER/MODEL \
--budget-usd BUDGET_USD
```

Preparation defaults to cases from the three public, manifest-pinned
repositories (75 cases in the full dataset). Add `--include-private` to
explicitly include the remaining private-repository snippets in requests to
OpenRouter. Add `--case-limit 5` for a small pilot, using its own output directory.
No credentials or provider calls are involved in preparation.

## Authenticate and run

The scoped secret environment is
`~/.config/personal-secrets/secrets/openrouter_codira_tests.env`.
Authenticated preflight uses `/models/user` to check the exact judge's
structured-output support, token limits and prices. It freezes the contract
and rejects a conservative full-run reservation above the declared budget.
Reservations use the highest published conditional price tier. An omitted
fixed request fee is represented as zero, with a zero request-price routing
ceiling. Preflight makes no paid completion; model compatibility and judgment quality
still need an actual pilot.

```bash
sops exec-env ~/.config/personal-secrets/secrets/openrouter_codira_tests.env 'uv run python -m scripts.grade_retrieval_quality preflight --output .artifacts/benchmarks/retrieval-quality/grades/known-target-20261008-v1'
```

After reviewing the prepared controls and preflight, launch paid grading:

```bash
sops exec-env ~/.config/personal-secrets/secrets/openrouter_codira_tests.env 'uv run python -m scripts.grade_retrieval_quality run --output .artifacts/benchmarks/retrieval-quality/grades/known-target-20261008-v1'
```

The script shows progress and checkpoints each query. Empty result pools need
no paid completion. It rechecks the authenticated contract before execution,
sets routing price ceilings and preserves mandatory reasoning behavior.
Reservations use a conservative byte-based input estimate and the selected
output-token ceiling; they are admission estimates, not a provider billing cap.
Observed usage and cost are validated after each response, and a reservation
violation stops execution.

## Resume and rescore

Add `--resume` to the paid command to reuse completed, validated checkpoints.
An interrupted or failed paid attempt blocks automatic retry because its
billing or outcome may be uncertain. Inspect that attempt's retained evidence
before deciding how to recover; do not delete it to force a retry. Changes to
judge, prices, controls or grading code require a fresh prepared identity.

### Explicit recovery after an invalid judgment

Use `recover` to finish a run without paying again for validated queries. It
verifies the source's saved requests, raw responses, scores and accounting,
then copies completed checkpoints into a fresh identity. Failed responses are
preserved separately and their observed costs carry forward into the same
original budget and final report. The source directory remains unchanged.
Ambiguous attempts without terminal response/accounting evidence are refused.

```bash
uv run python -m scripts.grade_retrieval_quality recover \
--source .artifacts/benchmarks/retrieval-quality/grades/haiku-20261009-v4-full100 \
--output .artifacts/benchmarks/retrieval-quality/grades/haiku-20261009-v5-recovery
```

Authenticate the new identity with `preflight`, then execute it with `run
--resume` to reuse the copied checkpoints. Preflight reserves only pending
requests plus all recorded spending, including failed attempts; it requires
the same model and price contract. The failed query receives one fresh request
when you launch the continuation. Recovery does not relax the explanation
requirement, fabricate reasons or silently retry a paid request. Another
invalid response stops execution again; prepare another explicit recovery
identity to retain progress and costs.

The first full run completed 85/100 queries and stopped when one of the next
query's 12 scores had an empty explanation. Its observed cost, including that
failed attempt, was USD 0.1703898. Recovery reuses the 85 complete judgments and
requests the remaining 15 queries, retaining the same 100-query denominator.

Offline reporting requires no credentials or completions:

```bash
uv run python -m scripts.grade_retrieval_quality rescore \
--output .artifacts/benchmarks/retrieval-quality/grades/known-target-20261008-v1
```

Expected outputs are `grading-summary.json` and `grading-summary.md`, plus
frozen `manifest.json`, `jobs/`, and authenticated `preflight.json`.
Each `attempts/<case-id>/` retains the credential-free request, state and exact
`response.body`, saved before parsing. Replays verify evidence digests.
Costs from failed responses remain in the report; missing accounting is
reported explicitly. Keep these generated inputs and provider evidence in
ignored `.artifacts/` directories, outside Git.

Automated transport fixtures verify preparation, accounting, retention and
resume mechanics. They do not establish a real judge's semantic accuracy.

## A completion with a missing explanation

A normal provider completion can still violate the grading contract. Haiku's
structured-output grammar does not enforce string-length constraints. The
request expresses nonempty explanations in descriptions and instructions. Exact
candidate coverage is enforced structurally: `grades` is an object with every
blinded candidate ID listed as a required property, and no additional properties.
Local validation also checks coverage, scores, duplicate JSON keys and reasons.
See [Claude's schema limitations](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

If a candidate explanation is blank, the query remains ungraded. The terminal
and attempt state identify that reason; the exact response and its billed cost
are retained. No automatic retry is made and no explanation is invented.
A corrected prompt or harness requires a fresh grading identity, not `--resume`
of the failed identity. Offline rescore verifies the original saved request
instead of rebuilding it with the current prompt.

The first `haiku-20261008-v1` attempt returned all 14 scores but one empty
explanation. It cost USD 0.0015463 and graded no query; the other 99 queries
were never requested. Keep that evidence intact. A subsequent attempt must
use a new directory rather than resuming it.

The second `haiku-20261009-v2` run completed five queries, then returned only
one of the sixth query's 14 judgments with a blank explanation. Its total
observed cost was USD 0.0109169. Prompt instructions alone did not establish
complete pool coverage. Keep both failed runs intact.

New preparations use `retrieval-llm-grading-v2` and the candidate-keyed schema.
Old array-based judgments remain supported for offline rescore. Test the new
wire format with a six-case pilot, including both previously failing queries:

```bash
uv run python -m scripts.grade_retrieval_quality prepare \
--run .artifacts/benchmarks/retrieval-quality/runs/known-target-full-20261008-v2 \
--output .artifacts/benchmarks/retrieval-quality/grades/haiku-20261009-v3-pilot6 \
--judge-model anthropic/claude-haiku-5.5 \
--budget-usd 3 \
--include-private \
--case-limit 6
```

Use the same preflight and run subcommands with that output directory. A
passed authenticated preflight is still not a paid wire-format test or a
qualification of semantic grading accuracy. After inspecting the pilot,
prepare the full run in another fresh directory.

## Completed 100-case evaluation — 2026-10-09

`haiku-20261009-v5-recovery` completed all 100 queries, reusing 85 validated
queries from `haiku-20261009-v4-full100` and requesting the remaining 15.
Offline rescore verified the retained evidence. Observed total cost was
USD 0.2003547, including the failed full-run attempt. There were no unknown
costs and four candidate judgments marked insufficient evidence.

| Metric | BGE small | Jina code |
| --- | ---: | ---: |
| LLM precision lower bound at 1 | 0.8700 | 0.8500 |
| LLM precision lower bound at 5 | 0.6920 | 0.6520 |
| LLM precision lower bound at 10 | 0.5810 | 0.5240 |
| LLM pooled nDCG at 10 | 0.7707 | 0.7040 |
| Known-target Hit at 1 | 0.5800 | 0.5500 |
| Known-target Recall at 5 | 0.7700 | 0.7500 |
| Known-target MRR at 10 | 0.6622 | 0.6350 |

The separate corrected comparison `known-target-full-20261008-v2` completed
with no failed queries or empty rankings for either model. Jina's median
embedding-query latency was 1.92 times BGE's, and its total indexing time was
1,634 seconds versus 586 seconds. Neither the known-target comparison nor the
optional LLM judgments demonstrate a quality advantage that justifies replacing
BGE for this workload. These results support retaining the current model;
they do not establish universal superiority, exhaustive relevance or agent
task success. Full raw reports remain in their ignored run and grade directories
under `.artifacts/benchmarks/retrieval-quality/`.
