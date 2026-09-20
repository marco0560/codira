# Pilot 003 patch/diff failure analysis — 2026-09-20

## Decision

Pilot 003 does not distinguish Codira efficacy from model/driver efficacy. The
assisted patch attempt received an empty Codira index that the runner admitted
as successful, while both the baseline and assisted agents also spent their
bounded continuations on exploration and unavailable setup instead of making a
patch. The result is therefore a mixed harness-and-agent failure, not evidence
that Codira cannot help with patch preparation.

Do not retry or rewrite Pilot 003. A new campaign identity is required after
the controls in this document pass offline admission.

## Evidence boundary

The immutable campaign is `codira-efficacy-pilot-003`. Its launch receipt
binds the state root to `/tmp/codira-ae-b792640cb0689df8`; the persisted report
records both patch attempts as `local_request_cap_exceeded`, with no task
oracle evaluation. Neither workspace contains a material diff.

The provider proxy retained status and aggregate observations, but Pilot 003
predates exact raw-response persistence. Consequently this analysis can prove
the tool calls, commands, MCP results, workspace state, index metadata, and
terminal classifications recorded by the runner. It cannot reconstruct
unrecorded provider reasoning or claim a complete token/cost comparison.

## What happened

### Fixture and index defect

The agent-visible Click fixture was history-free, as intended, but its
synthetic Git index was empty:

- `git rev-parse --verify HEAD` failed, which correctly hid history;
- `git ls-files --cached` returned zero paths, which was not intended;
- Codira indexing returned exit status zero in 1.18 seconds;
- persisted MCP `index_status` then reported `indexed_file_count: "0"`,
  generation `ready`, `partial: false`, and coverage `complete`;
- `context_for_task` returned `no_matches` against that empty index.

The indexer did not fail because parallel work was rejected by the sandbox.
There is no recorded index error: the preparation subprocess returned zero and
had an empty stderr digest. The demonstrated cause is earlier and simpler:
`git archive` was followed by `git init`, but not `git add --all`. The scanner
therefore saw no Git-indexed paths and legitimately built a zero-file index.
Codira and the runner then incorrectly treated that state as usable.

The original hypothesis was thus directionally useful—Codira was unavailable
before the agent could benefit—but its proposed parallel/sandbox mechanism is
not supported by the evidence.

### Assisted trajectory

The model did ask one important right question: it called `index_status`. The
answer clearly exposed `indexed_file_count: "0"`. Three driver/tooling defects
then compounded that signal:

1. `index_status` labeled the empty index as indexed with complete coverage.
2. `context_for_task` converted the empty index into an ordinary `no_matches`
   result instead of rejecting it.
3. The treatment prompt required only one MCP call; it did not tell the model
   to stop when the index was unusable.

The model also made avoidable mistakes. It ignored the zero-file count, called
paginated MCP tools with `cursor: ""` three times, and continued broad shell
searches. It eventually found the sentinel implementation and tests, but did
not edit the workspace before the ten-continuation limit.

This means the model asked a correct diagnostic question and got a misleading
overall Codira contract: one field revealed the defect while the surrounding
status and query semantics said the index was healthy. The later empty-cursor
calls and failure to prioritize a minimal patch belong to the model/driver
trajectory.

### Baseline trajectory

The baseline had no Codira dependency and failed in the same terminal way. It
located `src/click/_utils.py` and `tests/test_utils/test_sentinel.py`, inspected
sentinel use, and attempted a small Python probe. It then spent scarce
continuations on Git history that the fixture intentionally lacks, unavailable
pytest discovery, `uv sync` despite disabled network, and cache/package
searches. It never edited the workspace.

This independent failure rules out “Codira alone caused the missing patch.”
The patch prompt and driver policy did not make the shortest successful path
explicit: inspect the focused code/test, reproduce with installed standard
Python where possible, edit, run the protected/focused probe, and stop.

## Responsibility assessment

| Component | Finding | Contribution |
| --- | --- | --- |
| Fixture exporter | Created an empty synthetic Git index | Primary cause of zero-file Codira index |
| Pilot runner | Checked only process exit status | Admitted unusable assisted setup |
| Codira MCP | Called zero-file state indexed/complete and returned `no_matches` | Converted infrastructure failure into plausible negative evidence |
| MCP cursor boundary | Rejected empty string rather than treating it as omission | Wasted assisted calls, but did not cause the empty index |
| Treatment prompt | Required a call but supplied no health/stop policy | Failed to guide recovery from bad index state |
| Model/driver | Ignored zero count, repeated invalid cursor form, over-explored, attempted unavailable setup, and never edited | Material cause in both arms |
| Ten-continuation cap | Stopped both unproductive trajectories | Correctly bounded spend; it exposed rather than created the behavior |

The fairest conclusion is mixed responsibility. For the assisted arm, Codira's
input and health contracts failed before useful retrieval, so that attempt
cannot measure Codira efficacy. For both arms, the model/driver asked too many
low-value questions and did not transition from diagnosis to a patch.

## Capitalization finding and model controls

Pilot 003 contains no patch whose capitalization can be audited. The separate
baseline symbol answer wrote `McpAdapter`; the exact repository identifier and
oracle require `MCPAdapter`. The assisted symbol answer used the correct case.
This is a model answer-copying error, not evidence of index corruption.

The current OpenRouter request surface documents sampling controls such as
`temperature` and `top_p`, reasoning effort, structured output, and provider
routing. Its supported-parameter enumeration has no capitalization or
case-preservation switch. Context7's current OpenRouter documentation likewise
lists no such parameter. Therefore capitalization must be controlled through
instructions and deterministic verification, not an invented model option.

Relevant current documentation:

- [OpenRouter Responses request](https://openrouter.ai/docs/api/api-reference/responses/create-responses)
  documents reasoning, sampling, tools, and text controls.
- [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
  recommends `require_parameters: true` when relying on requested features.
- [OpenRouter model fallbacks](https://openrouter.ai/docs/guides/routing/model-fallbacks)
  explains why fallback behavior can change the responding route.
- [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model)
  treats reasoning effort and explicit agent instructions as quality controls,
  not spelling guarantees.

Pilot 005 therefore uses medium reasoning effort, forbids provider fallback,
requires support for requested parameters, and gives both arms the same
case-sensitive identifier and patch-completion directive. These controls can
reduce errors; the exact-name oracle remains the guarantee.

## Implemented controls for the next cycle

1. Fixture export stages the immutable archive with `git add --all` while
   retaining no `HEAD` and no remote. Ordinary `git diff` can now represent
   edits against the staged baseline.
2. Offline admission runs inside the hardened, networkless image against that
   exact staged/no-history representation.
3. The runner records and validates staged-path count, indexed-path count,
   generation state, partial flag, and failed-file count before starting the
   provider boundary. Zero or implausible counts stop the attempt without a
   paid completion.
4. MCP `index_status` marks zero-file indexes unusable and incomplete; query
   tools reject them instead of returning ordinary empty results.
5. An omitted or empty MCP cursor means the first page. The next request must
   use only a returned continuation cursor.
6. Exact provider response bodies are durably written to an ignored,
   per-attempt directory before semantic validation, with digest and byte-count
   bindings in public-safe evidence.
7. OpenRouter routing uses `allow_fallbacks: false` and
   `require_parameters: true` so requested reasoning controls cannot be
   silently dropped by route selection.
8. The next immutable campaign uses a new identity and medium reasoning. A
   common directive tells both arms to preserve exact identifier case, verify
   spellings, avoid unavailable installs/network, treat the fixture as staged
   and history-free, edit before broad exploration, and run a focused check.
   The assisted-only directive additionally requires a usable non-empty index,
   narrow Codira retrieval first, omission of empty cursors, and immediate stop
   on index infrastructure failure.
9. The ten-continuation and 240,000 whole-session-token ceilings remain
   unchanged. Increasing them would mask the failed workflow rather than fix
   it.

## Readiness criterion

A new paid test cycle is ready only when all three frozen fixtures pass the
hardened offline admission, focused tests pass, the full repository gate passes
in its durable tmux session, and a fresh factory campaign plus prepare receipt
exist. Authenticated preflight and paid launch remain separate explicit stages.

Pilot 004 was generated and prepared against the first corrected image, then
the full repository gate found a cursor type-narrowing error. Its immutable
artifacts remain preserved and are superseded without paid execution. Pilot
005 binds the rebuilt, gate-candidate image and is the only launch candidate.
