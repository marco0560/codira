# Campaign 016 failure analysis — 2026-10-04

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/agent-efficiency/reports/campaign-016-failure-analysis-20261004-r1/report.md`
(SHA-256 `02c2d903926e723a869efdb0cac3cafba14496c5996dbb770564cd7eab422b4b`).

The explicit artifact/input paths were checked in this checkout. Availability
does not establish that old measurements apply to the current version.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/agent-efficiency/executions/glm016-20261004-r1/state/records/panel-i1-r03-codira-mcp.json` | available |


Campaign 016 stopped on its first assisted attempt because the local proxy
rejected request 46 after admitting the frozen 45 logical requests. The model
never wrote `BENCHMARK_ANSWER.md`. Its trajectory indicates poor control of
investigation scope and completion, with an independently confirmed offline
test-dependency problem adding a detour. This is an operationally censored
attempt, not a scored task failure or evidence of Codira efficacy.

## Evidence boundary and measured outcome

Campaign: `codira-efficacy-campaign-016`; execution: `glm016-20261004-r1`;
attempt: `panel-i1-r03-codira-mcp`; model: `z-ai/glm-5.3-flash`, frozen `max`
reasoning. There is one recorded failed attempt, 143 pending attempts, and
zero completed pairs. The process exited 2 and remains stopped. Analysis made
no provider requests and changed no original evidence or repository source.

The recorded age and exact-image registry-prefix exceptions are separate
operator-authorized launch exceptions. They did not change the model task,
logical request guard, tool result schema or fixture source. All preserved
upstream responses name the selected model. No trace supports treating either
exception as the cause of the observed continuation-limit failure.

All 45 upstream responses were HTTP 200 with `response.completed` status,
complete provider usage and verified body digests. The last observation is a
local HTTP 429, `response_request_limit_exceeded`, with no upstream response.
The native message “exceeded retry limit” is therefore misleading if read as
provider throttling. The three-transport-attempt allowance was not exhausted:
there is one upstream response per admitted logical request, with no observed
transport retry. There is no timeout, MCP approval denial or Bubblewrap error
in this attempt.

Start marker to result record: 886.396 seconds (14m46s), approximately
09:23:44–09:38:30 UTC, or 11:23:44–11:38:30 Europe/Rome. Index preparation
took 583.953 seconds, environment preparation 28.521 seconds, fixture export
1.073 seconds, container execution 263.644 seconds, and grading 0.082 seconds.
The index succeeded: 514 files, zero failed files and 7,626 embeddings
recomputed. Its eight coverage issues were reported, not terminal indexing
failures. This preparation overhead is separate from model execution and did
not consume logical model requests.

## Failure trajectory

The task asks for a change-impact assessment of `MCPAdapter._query`: direct
callers, warm connection executor, bypass operations, relevant tests and
dynamic uncertainty. It explicitly asks the model to write the answer file
and stop. It does not require modifying source or making every relevant test
pass before reporting.

1. The model made two invalid `symbol` calls with an empty cursor. It
   recovered; the subsequent lookup and evidence expansion succeeded.
2. MCP returned the complete eleven direct callers in response request 4.
   Across the attempt, 13 MCP calls produced eleven successes and two schema
   failures, with zero denied calls. The model also received definition and
   impact evidence without truncation on the inspected calls.
3. The model continued with broad source and test searches, including seven
   shell read commands targeting overlapping adapter ranges. It executed
   35 shell commands before its selected pytest invocation. There were 51
   completed shell commands overall: 48 succeeded and three failed. Their
   captured outputs totaled 801,202 characters; this is recorded tool output,
   not a claim that every character was sent untruncated to the model.
4. Request 30 ran three selected tests. The zero-file guard test passed;
   two warm-routing tests failed while trying to provision the default
   `sentence-transformers/all-MiniLM-L6-v2` model. The network-isolated
   container could not resolve Hugging Face. This is not evidence that their
   routing assertions failed. The test invocation took 23.05 seconds.
5. Fifteen shell commands followed that pytest result, predominantly more
   configuration, cache, source and fixture-state investigation. The other
   two failed commands searched nonexistent files, including an unavailable
   oracle path; neither is a product execution failure.
6. Near the end, the model stated that it had the call map and bypass set,
   but still performed more checks. Request 45 requested another shell
   inspection. Request 46 was refused locally. No answer file or final
   deliverable was captured.

The input grew from 11,058 tokens on the first completion to 114,961 on the
last. Request wire size grew from 48,378 to 513,246 bytes. Repeated continuation
over a growing history explains the high cumulative input usage even though
output was relatively small.

## Contributing causes and confidence

**Model task control: directly observed behavior, probable contributor.**
The model explored far beyond the initial complete caller result, reread
overlapping evidence, and deferred the deliverable. Most shell commands
occurred before the dependency failure, so that failure cannot explain all
the over-exploration. This supports an inadequacy in task scoping,
prioritization and stopping on this attempt. It does not establish general
model inadequacy, incorrect understanding of the caller map, or inability to
complete with different controls. No finished answer exists to grade its
technical synthesis, and there is no matched baseline or alternate model.

**Offline test configuration: confirmed environmental gap.** The prepared
workspace config selects the image-baked ONNX BGE model. The failing tests
create separate `tmp_path` repositories through `_indexed_repository`, which
calls `index_repo(root)` without preparing equivalent local model settings.
Their isolated HOME lacks the default sentence-transformer model. The
container's `CODIRA_CONFIG_FILE` is handled by CLI path resolution; the
direct-library configuration loader does not make that variable a universal
configuration override for temporary test repositories. Thus main-workspace
CLI/MCP qualification did not prove those temporary-repository tests were
offline-ready. Host full-gate success did not reproduce this isolated cache
and HOME boundary.

**Request limit: confirmed immediate trigger, adequacy unresolved.** The
45-request guard operated as configured. Raising it might have allowed a
report, but the trace cannot establish how many more requests were needed or
whether the model would stop investigating. It would also allow more cost
and context growth. A larger cap alone is not a diagnosis or proof of efficacy.

## Accounting and budget semantics

Reconstructed directly from the 45 hash-verified provider responses:

| Measurement | Value |
| --- | ---: |
| Input tokens | 3,426,504 |
| Cached input tokens, included above | 3,197,888 |
| Output tokens | 8,826 |
| Reasoning output tokens, included above | 4,090 |
| Total provider tokens | 3,435,330 |
| Sum of provider-reported response costs | $0.1250259408 |
| Campaign settlement at frozen price ceilings | $0.55353624 |

The provider-reported cost is not an invoice. The ledger conservatively prices
all input at $0.16/million and output at $0.60/million, without a cache discount.
The exact ledger amount reconciles with the immutable settlement. Preparation
canary cost is separate and is not included in these main-attempt figures.

The result record's zero usage and `usage_complete: false` reflect absent
native terminal usage after `turn.failed`. They are not a measurement of zero
paid tokens. `normalize_execution` skips completed-turn normalization when
a terminal failure exists. Provider usage remains recoverable and complete
in the raw responses, including cache and reasoning detail. Reporting should
make this distinction explicit rather than presenting zero usage for the
failed attempt. Historical result records were not rewritten.

The full-campaign `shared-pool` path deliberately disables the proxy's
per-attempt session-token and dollar caps. Consequently, 2,500,000 tokens and
$1.75 per attempt are planning figures here, not hard per-attempt stops. The
3,435,330 observed tokens do not contradict that implemented policy. The
observed USD pool, response output, logical requests and timeout are the
execution controls. Earlier conversational references to the main token
figure as an enforced guard were inaccurate.

There is one start and one matching settlement, with validated record and
evidence fingerprints. No unfinished paid start was found. The campaign stops
after the operational failure by design; `run_full_campaign` does not treat
this as a scored task failure and move automatically to another slot. Its
automatic-resume guard rejects a prior terminal execution failure.

## Recommended next steps

Do not spend on an unchanged restart or merely increase the request count.
First qualify the relevant fixture tests under the actual image, network
isolation, HOME and temporary-repository configuration. Decide whether to bake
the expected default model or supply a qualified offline configuration at the
appropriate scope; do not weaken network isolation to conceal the gap.

Improve failed-turn reporting to expose reconstructed provider usage and
provider-reported cost with provenance while keeping native completion usage
distinct. Retain the conservative pool ledger and original immutable records.
Resolve the documented planning-versus-hard-cap semantics before describing
the main token figure as a spending guard.

If the experiment's next question is model adequacy, use a small matched
comparison of the same task, image, assistance, prompt, reasoning and request
controls after correcting the environmental gap. Compare deliverable
completion, correctness, evidence-gathering behavior and cost. Change the
model alone in that comparison; separately test any request-cap or instruction
change. One failed assisted attempt cannot support an overall model ranking
or a Codira-versus-baseline efficiency claim.

Any changed runtime, harness, model, task or frozen controls require a fresh
factory identity and preparation under the repository workflow. No inference
retry, automatic continuation or source change was performed by this analysis.

## Verification and evidence pointers

`facts.json` in this directory is the machine-readable reconciliation. All 45
exact received bodies matched recorded SHA-256 digests and sizes; completed
provider usage matched proxy observations; settlement cost, result fingerprint
and evidence fingerprint matched; all starts were settled; the answer file
was absent. No additional tests or full gate were needed for this read-only
analysis.

Original evidence remains under:

- `.artifacts/agent-efficiency/executions/glm016-20261004-r1/state/records/panel-i1-r03-codira-mcp.json`
- The corresponding `state/attempt-work/.../events.jsonl`, `provider-responses/`
  and `runtime-traces/` directories.
- `state/budget/`, `logs/resume-001.log`, `resume-001.exit`, and the recorded
  `operator-launch-exceptions.json` in that execution root.

Relevant code contracts: `scripts/agent_efficiency/provider_proxy.py`
(logical admission and usage), `scripts/agent_efficiency/runner.py`
(`normalize_execution` and container environment),
`scripts/run_agent_efficiency_phase6_pilot.py` (`_attempt_budget_limits` and
failure classification), `scripts/agent_efficiency/full_campaign.py`
(settlement and stopping), `tests/test_mcp_server.py`,
`src/codira/config.py`, `src/codira/path_resolution.py`, and
`docs/process/agent-efficiency-campaign-factory.md`.
