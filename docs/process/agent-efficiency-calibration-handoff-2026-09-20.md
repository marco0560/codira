# Agent-efficiency calibration closeout — 2026-09-20

Historical closeout, reduced during the approved 2026-10-07 cleanup. The old
“Next work” and financial snapshots are not current execution instructions.
Fresh work follows [the campaign procedure](campaign-creation-instructions-2026-10-03.md)
and [factory controls](agent-efficiency-campaign-factory.md).

## Calibration and pilot chronology

| Identity | Observation and consequence |
| --- | --- |
| Calibration 006/007 | Upstream 429 motivated retention of terminal parsing/failure evidence. |
| Calibration 008 | Three upstream HTTP 200 responses followed by a local 429 exposed conflation of logical continuations and transport retries. These now have separate budgets. |
| Calibration 009 | Five upstream HTTP 200 responses followed by a local request-cap rejection; the task needed more continuations. |
| Calibration 010 | Seven continuations, all HTTP 200, complete usage: 97,345 input, 71,680 cached input and 801 output tokens. Operationally passed; the frozen oracle failed on `McpAdapter` versus `MCPAdapter`. The record is unchanged. |
| Pilot 003 | Documentation pair passed; both patch arms exhausted ten continuations without a diff. Baseline symbols failed capitalization. Missing exact raw response bodies excludes the run as a complete efficacy result. See [patch investigation](agent-efficiency-pilot-003-patch-failure-analysis-2026-09-20.md). |
| Pilot 006 | Partial Click index: 78/79 Python files, one `unicodeescape` decoder failure on literal Windows-path docstrings. Admission rejected the partial index before provider setup for that attempt. Ten upstream HTTP 200 calls followed by a local cap rejection were not provider throttling. |
| Pilot 015/016 | 015 failed profile-fingerprint admission without provider contact; 016 completed six scheduled attempts, but only the documentation pair passed completely. Assisted documentation used 256,975 more tokens. See [postmortem](agent-efficiency-pilot-016-postmortem-2026-09-25.md) and [forensic review](agent-efficiency-pilot-016-forensic-review.md). |
| 2026-10-01 | Implemented C1–C5 product/MCP and H1–H3 harness changes without a paid campaign. See [implementation report](agent-product-harness-improvements-2026-10-01.md). |
| 2026-10-02 | Prepared the admitted image, representative panel calibration and separate OpenRouter/native routes. See [preparation report](agent-efficiency-campaign-preparation-2026-10-02.md). |

Operational calibration and task-oracle correctness remain separate axes.
Successful transport, a completed session or a minor calibration typo does not
establish successful paired task efficiency. Failed identities are never
rewritten or automatically retried.

## Retained controls and evidence

The historical whole-session pilot revision approved 240,000 tokens, twelve
logical continuations, two transport attempts, $0.18 per attempt, $1.08 for six
attempts and a $6 daily limit. These values are historical approved controls,
not defaults for future work. Original approvals, fingerprints, commands,
financial observations and gate checkpoints remain in the full Git record.

Calibration 010 factory input is
`benchmarks/agent-efficiency/campaign-specs/codira-efficacy-calibration-010.json`;
its factory directory and execution receipt remain under
`.artifacts/agent-efficiency/campaigns/codira-efficacy-calibration-010/` and
`.artifacts/agent-efficiency/executions/codira-efficacy-calibration-010-execution/`.
Its original record/workspace pointer was `/tmp/codira-ae-69b793e7265833ae/`;
that historical pointer does not guarantee current availability.
Pilot 006 evidence pointers were
`.artifacts/agent-efficiency/executions/codira-efficacy-pilot-006-execution/` and
`/tmp/codira-ae-ac494e2b429a2c64/`. Pilot 016 evidence remains under
`.artifacts/agent-efficiency/attempts/016/`.

The [retention review](artifact-retention-review-2026-09-27.md) records approved
removal of nineteen attempt-local caches while preserving prepared image caches
and raw campaign evidence. The [preparation history](agent-efficiency-preparation-history-2026-10-07.md)
consolidates subsequent superseded handoffs. None of this cleanup changes
campaign specs, generated identities or raw evidence.

## Full historical handoff

```bash
git show f7d27c8b66777a5d0ec0b5bd231e4ddedb36ec42:docs/process/agent-efficiency-calibration-handoff-2026-09-20.md
```
