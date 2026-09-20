# Agent-efficiency calibration handoff — 2026-09-20

## Objective

The experiment is to determine whether Codira is a useful token-saving device
in realistic work. It is not a model leaderboard. Future users select their
own model, so the protocol must remain model-agnostic.

## Objectives

### General objective

Establish, with reproducible paired evidence, whether adding Codira changes
the tokens, cost, elapsed time, and successful-task rate required for real
software-engineering work. The result must be meaningful across user-selected
models: Codira is the treatment; model ranking is not the outcome.

### Immediate objective

Turn the successful operational calibration into the first valid, bounded
paired pilot. Before spending on it, make the accounting definition match the
actual semantics of whole-session token ceilings and continuation/retry caps;
then compare the same frozen tasks with and without Codira MCP under identical
model, image, prompt, and oracle conditions.

## Read first

1. `AGENTS.md` — immutable campaign, tmux-gate, preflight, and paid-run rules.
2. `docs/process/issue-053-agent-efficiency-benchmark-ledger.md` — historical
   Phase 6 evidence and decisions.
3. `docs/process/agent-efficiency-campaign-factory.md` — factory artifacts and
   approval-gated execution workflow.
4. `docs/process/deepseek-v4-1-flash-reviewer-evaluation-plan.md` — earlier
   reviewer work; do not confuse it with the Codira-efficiency experiment.
5. `docs/process/agent-efficiency-pilot-003-patch-failure-analysis-2026-09-20.md`
   — causal analysis and Pilot 004 admission criteria.
6. `scripts/run_agent_efficiency_phase6_pilot.py` — controls, accounting,
   attempt execution, evidence persistence.
7. `scripts/agent_efficiency/provider_proxy.py` — credential boundary,
   continuation limiter, upstream retry and sanitized response evidence.
8. `scripts/launch_agent_efficiency_calibration.py` and
   `scripts/run_agent_efficiency_phase6_calibration.py` — factory-backed,
   immutable single-calibration execution.

## Protocol and safety rules

- Generate every paid campaign with
  `scripts/generate_agent_efficiency_campaign.py`; never hand-write a manifest
  or reuse an execution root.
- Prepare, authenticated-preflight, then launch through the calibration
  executor. The paid command runs inside tmux and writes a durable log and exit
  file.
- Preserve every old campaign, response log, record, and failure. Never retry
  a failed campaign identity.
- After a failure, inspect complete event, proxy, response, usage, and oracle
  evidence before another run.
- Run the full repository gate in tmux for code changes. The latest relevant
  gate is `.artifacts/agent-efficiency/gates/dual-budget-final-20260920.*`:
  `1118 passed, 3 skipped`.
- Do not expose OpenRouter credentials. Use only the scoped SOPS environment
  named in `scripts/launch_agent_efficiency_calibration.py`.

## Completed executor repair

`calibration-008` showed that `max_response_requests_per_attempt` is a logical
Codex-continuation cap, not a provider transport-retry cap. It made three
successful upstream HTTP 200 calls and then the local proxy returned 429.

The implementation now separates the dimensions:

- `max_response_requests_per_attempt`: logical model continuations;
- optional `max_transport_attempts_per_response` (default `1` for existing
  historical manifests): bounded upstream attempts for one continuation;
- provider proxy retries only upstream 429 and 503 responses, honors
  `Retry-After`, and records sanitized status/source/retry metadata;
- local cap rejections are `local_request_cap_exceeded`, never
  `provider_rate_limited`;
- accounting reserves continuation count multiplied by transport attempts.

Relevant changed files:

- `scripts/agent_efficiency/provider_proxy.py`
- `scripts/run_agent_efficiency_phase6_pilot.py`
- `scripts/agent_efficiency/campaign_factory.py`
- `scripts/generate_agent_efficiency_schemas.py`
- `benchmarks/agent-efficiency/schemas/campaign*.schema.json`
- `tests/test_agent_efficiency_phase0.py`

## Calibration evidence

All calibration specs are factory inputs in
`benchmarks/agent-efficiency/campaign-specs/`; their generated artifacts and
execution evidence are under `.artifacts/agent-efficiency/`.

| Identity | Result | Meaning |
| --- | --- | --- |
| calibration-006/007 | upstream 429 | parser repair: preserve terminal failure evidence |
| calibration-008 | three HTTP 200 then local 429 | request cap was incorrectly used as retry cap |
| calibration-009 | five HTTP 200 then local 429 | task needs more than five continuations |
| calibration-010 | seven HTTP 200; completed | runner, MCP, image, transport, and cap work |

`calibration-010` exact artifacts:

- factory input: `benchmarks/agent-efficiency/campaign-specs/codira-efficacy-calibration-010.json`
- generated campaign: `.artifacts/agent-efficiency/codira-efficacy-calibration-010/`
- execution receipt/log/preflight: `.artifacts/agent-efficiency/codira-efficacy-calibration-010-execution/`
- record: `/tmp/codira-ae-69b793e7265833ae/records/symbols-001-calibration-codira-mcp.json`
- event stream and written answer:
  `/tmp/codira-ae-69b793e7265833ae/attempt-work/symbols-001-calibration-codira-mcp/`

It used seven continuations, had complete usage
(`input_tokens=97345`, `cached_input_tokens=71680`, `output_tokens=801`), and
all seven upstream responses were HTTP 200. It did not use a transport retry.

## Calibration oracle distinction

`symbols-001` requires:

- `codira.mcp.adapter.MCPAdapter.context_for_task`
- `src/codira/mcp/adapter.py`

The agent wrote the correct endpoint and path, used MCP, and completed normally,
but wrote `McpAdapter` instead of case-sensitive `MCPAdapter`. Therefore the
immutable record remains `oracle_failure`, while it is an operational
calibration pass. Do not rewrite that record.

For future protocol reporting, maintain two axes:

1. operational calibration: execution, provider, MCP, evidence, and cap;
2. task oracle: task-answer correctness.

The calibration typo must not be used to judge Codira’s token-saving value.
Task correctness remains necessary for paired real-world measurements, but
minor answer-quality signals must not invalidate operational calibration.

## Next work

1. **Implemented in the working tree:** calibration attempts persist separate
   `operational_calibration` and `task_oracle` outcomes, reports render both,
   and historical immutable records are reported through a labeled legacy
   projection without rewriting them.
2. Design the actual paired pilot around the experiment objective: same frozen
   task, model, image, token ceiling, prompt, and deterministic oracle with and
   without Codira MCP. Measure paired token use, cost, completion, and tool use.
3. **Approved for implementation:** `max_total_tokens` is a whole-session cap
   for the fresh pilot. Use 240,000 tokens, ten logical continuations, two
   transport attempts per continuation, USD 0.18 per attempt, USD 1.08 for six
   attempts, and the existing USD 6.00 daily key limit. The token and spend
   ceilings include the operator-approved 20% increase; continuation and retry
   caps do not multiply a whole-session token reservation.
4. Only then generate a fresh factory pilot manifest, run offline validation,
   authenticated preflight, and obtain explicit paid authorization.
5. Launch the authorized paired pilot only through
   `scripts/launch_agent_efficiency_pilot.py`; its prepare stage persists the
   factory, schedule, fixture, runtime, state, log, and exit-path identities,
   and its launch stage revalidates that receipt before starting tmux.

## Pilot 003 terminal evidence

The six authorized attempts completed under the fresh factory identity. The
documentation pair passed both operational and task-oracle checks. Both patch
attempts exhausted the ten-continuation cap before producing a workspace diff,
so neither has a patch to compare or a capitalization defect in changed code.
The baseline symbol answer failed only because it wrote `McpAdapter` instead of
the case-sensitive `MCPAdapter`; the Codira-MCP symbol answer used the correct
capitalization and passed.

The postflight key snapshot measured a USD 0.015987972 daily-usage increase.
Pilot 003 remains excluded as a complete efficacy result: the proxy retained
sanitized response status metadata and completed-turn usage, but did not retain
the exact raw provider bodies required by the repository contract. No attempt
is retried or rewritten. The proxy now creates a fresh ignored per-attempt
response directory, durably persists each exact upstream body plus status and
headers before forwarding it to Codex, and binds the public-safe observation to
the artifact with a SHA-256 digest and byte count.

The patch failure was not a demonstrated parallel-indexing sandbox rejection.
The exported fixture had no staged paths, so indexing returned success with
zero indexed files. The runner and MCP health contract admitted that state,
and the assisted model ignored the explicit zero count. The baseline also
failed without Codira after spending its bounded trajectory on history and
unavailable dependency setup. The linked analysis assigns the mixed
harness/model responsibility and records every implemented control.

Pilot 005 uses a fresh image and campaign identity, medium reasoning, strict
provider-parameter routing, identical case-sensitive patch directives in both
arms, and an assisted-only index health/empty-cursor directive. Its request and
whole-session token ceilings are unchanged.

## Current financial context

At calibration-010 preflight the key had `$5.992518944` remaining and
`$0.007481056` used that day. This is historical evidence; re-check with the
authenticated preflight before any paid call.
