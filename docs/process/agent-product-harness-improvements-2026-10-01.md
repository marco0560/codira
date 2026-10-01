# Agent product and harness improvements — 2026-10-01

## Scope and rationale

This implements C1–C5 and H1–H3 from
[the internal assessment](issue-053-internal-product-assessment.md).
The historical paid records remain immutable. These changes qualify retrieval
and harness behavior offline; they do not establish a paid efficiency gain.
No new paid campaign was launched in this session.

## Implemented changes

| Control | Implementation | Validation surface |
| --- | --- | --- |
| C1: causal retrieval | Behavioral intent takes priority over incidental test words. Repository-independent source anchors supplement identifier retrieval; generic prose no longer becomes an invented symbol name. Source signals carry their provenance. | Product regression tests; saved Sentinel query panel and offline evaluator. |
| C2: canonical declarations | Indexed alias and re-export chains retain case and ambiguity. Python constants include their owner, including enum members; TypeScript named imports/re-exports use analyzer metadata. Exact lookup returns canonical identities and static alias edges. | Python analyzer, exact query and product tests. |
| C3: evidence expansion | Generation-bound symbol identities expand to complete verified definitions, adjacent Python decorators without core parsing, and bounded static relationships with locations. Changed source or stale identities are rejected. | Whole-definition, stale-generation and owner regressions. |
| C4: compact contracts | Model tools use bounded item counts and opaque cursors. Context discovery snippets are labeled; evidence expansion returns whole definitions. Diagnostics are opt-in. Actual published MCP schemas enforce bounds, enums and unknown-argument rejection; CLI capabilities expose accepted parameter values. | MCP schemas, pagination, CLI and capability tests. |
| C5: honest scores and coverage | Rank scores are labeled heuristic, not probabilities. Results distinguish static coverage and unresolved relationships. Capabilities include installed core and analyzer source identities; context cursors bind serving source and effective configuration. | Coverage, identity, schema and cursor tests. |
| H1: installed product admission | Before credential access, the pinned serving image must pass indexed MCP probes and match host core/analyzer source and benchmark profile hashes. Legacy schemas, stale receipts and mismatched images are rejected. Full qualification stdout/stderr is retained. | Runtime receipt regressions and actual stdio MCP admission integration test. |
| H2: quality and traceability | Rubrics cover correctness, causality, completeness, evidence and usability. Semantic decisions remain pending until blinded, quote-bound adjudication. Original grades and exact answer/rubric digests remain intact. Protected checks precede semantic review. Supported fenced examples can be replayed in an isolated offline container, retaining complete streams. | Good, incomplete, subtly wrong and equivalent-answer calibration cases; digest, quote and immutable-write tests. |
| H3: representative panel and measurements | Separate frozen 24-task bank across eight families, six fixtures and 12/12 development/holdout split. Factory validates balanced admission without changing the legacy six-task campaign. Optional MCP uses the same common prompt as baseline; required MCP is a distinct ablation. Instrumentation records request/tool bytes, preparation/ execution/grading timing, cache tokens, costs of failures and task-level paired bootstrap summaries. | Panel generator, snapshot admission, factory schedule, instrumentation and reporting tests. |

## Operator procedure

1. Run the existing pre-pilot checklist, including installed-image admission.
2. Regenerate/check schemas through `scripts/generate_agent_efficiency_schemas.py`
   and panel assets through `scripts/generate_agent_efficiency_panel.py --check`.
   Protected-probe digests are checked against their versioned provenance.
3. Choose `representative-campaign`, `panel_id: representative-v1`, all 24
   task IDs and one to five repetitions. Pin current source/profile and rebuilt
   image identities. The old `full-campaign` remains six tasks and 60 attempts.
4. Separate `mcp-optional-v3` efficacy from `mcp-required-v3` ablation. Keep the
   common instruction identical. Use a fresh factory-generated identity.
5. Review semantic packets without arm/model labels. Record a decision, reason
   and verbatim evidence for every criterion, bound to the supplied digests.
   `scripts/adjudicate_agent_efficiency_quality.py` writes a new adjudication;
   it never replaces a frozen attempt. A pending semantic review is not success.
6. Keep qualification, provider, protected-test and example-replay evidence.
   Review example outputs against the requested behavior: nonzero exit alone
   does not prove a deliberately failing example is incorrect.

## Limits and interpretation

- The synthetic Python, TypeScript and Go fixtures are deliberately small and
  dependency-free. They are reproducible controls, not representative production
  repositories; scale and ecosystem coverage remain future work.
- The bank includes direct interface/error-handling controls. Report them
  separately when interpreting general task efficacy. Baseline ordinary tools
  can include installed CLI commands; inspect trajectories before attributing
  a difference exclusively to MCP availability.
- Decorator expansion uses adjacent source boundaries, without parsing target
  Python in core; unusual separated decorator layouts need source inspection.
- Static edges and test-path heuristics do not prove dynamic dispatch or executed
  test coverage. Semantic relevance and useful evidence require answer review;
  first-reference instrumentation is an anchor-based proxy.
- Embedding/document pagination is over the ranked candidate pool (up to 100),
  not an exhaustive corpus scan. Whole discovery items may contain labeled
  snippets; request symbol evidence for a complete verified definition.
- Supported fenced examples may require setup beyond the answer. Replay is
  evidence for adjudication, not an unconditional pass/fail oracle.
- Primitive quality calibration is tested. Each new task rubric still needs
  task-specific known-good/incomplete/wrong calibration before paid admission.
- A rebuilt container image has not been qualified in this session. The live
  stdio check verifies the installed checkout; paid admission independently
  verifies the exact container and rejects stale serving products.

## Validation evidence

Focused product/MCP/panel tests: 25 passed, one skipped. Explicit live stdio MCP
admission: one passed. Final repository-gate results are recorded below. Durable raw validation evidence remains ignored under
`.artifacts/validation/repo-gates/`.

## Offline Sentinel retrieval observation

The verified Click fixture was exported into a disposable workspace; no old
index or attempt was modified. Default ten-item responses (without explanation):

| Query | Split | First reference rank | Reference recall | Payload bytes |
| --- | --- | ---: | ---: | ---: |
| saved-1 | development | 1 | 1.0 | 9581 |
| saved-2 | development | 1 | 1.0 | 9444 |
| saved-3 | development | 1 | 0.5 | 9624 |
| saved-4 | development | 1 | 1.0 | 9455 |
| saved-5 | development | 1 | 1.0 | 9045 |
| paraphrase-1 | holdout | 1 | 1.0 | 9129 |
| negative-1 | holdout | None | None | 8381 |
| ambiguous-1 | holdout | None | None | 7573 |

Sentinel ranks first for all five saved queries and the paraphrase. The unrelated
configuration query has no forbidden Sentinel hit. Precision is against a
deliberately narrow class/test reference set, not all useful context. The
ambiguous-name query is exploratory, without a reference oracle; owner
ambiguity is instead covered by the synthetic product regression. These
measurements are not a controlled old/new paid efficacy comparison.

Additional validation: 29 capability/reporting/panel tests passed; 62 legacy
campaign/context/MCP tests passed with one skip. Python fixture: two unittest
cases passed. TypeScript and Go fixture baseline suites passed.

## Adjudication record format

A review JSON contains `reviewer`, `answer_sha256`, `rubric_sha256` and
`decisions`. Each decision supplies the rubric criterion `id`, a `status`
(`supported`, `missing` or `contradicted`), a concrete `reason`, and `evidence`
quoted verbatim from the answer. Supported criteria require a nonempty quote;
a missing criterion may use an empty quote. Cover every criterion exactly once.
Derive the answer digest from its exact UTF-8 bytes and the rubric digest with
`canonical_fingerprint`; do not normalize the reviewed artifact. Run the
adjudication script with `--packet`, `--review` and a fresh ignored `--output`.
The receipt preserves the automatic grade and reviewer-record fingerprint.

The first full gate exposed five integration failures, subsequently corrected.
The second passed all 1,215 tests but stopped at the docstring audit. Missing
fixture/probe documentation and newly added parameters/raises were completed;
protected digests and synthetic inventories were regenerated. An independent
post-fix audit has zero findings. These failed gate records are retained.

## Final repository gate

`uv run python scripts/validate_repo.py` completed with exit **0** in tmux
session `agent-product-harness-gate-20261001-r3`: **1,215 tests passed, three
skipped, 86% aggregate coverage**. Ruff, formatting, core/package typing,
non-code hooks, repository Semgrep rules, suppression policy and Codira audit
all passed. The live stdio admission integration test also passed separately.

Durable evidence: `.artifacts/validation/repo-gates/agent-product-harness-20261001-r3/`
contains `validation.log`, `validation.exit` and the launch script. Completed
tmux sessions and earlier failed gate records are retained. Generated panel and
schema checks pass. Staged documentation/JSON were scanned for private host
paths and credential prefixes; raw runtime/provider evidence remains ignored.
