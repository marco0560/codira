# Agent-efficiency Pilot 016 post-mortem

Date: 2026-09-25
Campaign: `codira-efficacy-pilot-016`
Model: `minimax/minimax-m2.5`, medium reasoning
Result: execution completed, efficacy remains inconclusive.

## Executive finding

All six scheduled attempts reached a terminal record and the pilot launcher
exited successfully. This is a useful diagnostic run, but not evidence that
Codira MCP improves task completion. Only the documentation pair has both
arms complete with complete usage and passing task oracles. On that one pair,
both arms passed, while the Codira-MCP arm used 256,975 more reported tokens
(355,662 versus 98,687). One pair is far too small for a general efficacy
claim. The other two pairs are excluded for different reasons: the symbols
pair has an assisted oracle failure, and the patch pair has an assisted oracle
failure plus a baseline local request-cap failure.

The canonical public-safe report generated from the immutable records is in
ignored runtime state at `.artifacts/ae/016/report/report.md` and
`.artifacts/ae/016/report/report.json`. The six raw attempt records and exact
provider responses remain under `.artifacts/ae/016/x/state/`; they are
intentionally not tracked by Git.

## Attempt-by-attempt result

| Task | Arm | Operational | Task oracle | Requests | Interpretation |
| --- | --- | --- | ---: | ---: | --- |
| `patch-002` | Codira MCP | Pass | Fail | 16 | Environment and provider path completed; produced an answer that did not satisfy the frozen patch oracle. |
| `patch-002` | Baseline | Fail | Not evaluated | 25 upstream successes, then local rejection | The local 25-request ceiling stopped the next continuation. This was not an upstream provider 429; correctness cannot be inferred. |
| `symbols-001` | Codira MCP | Pass | Fail | 9 | Provider/MCP operation completed, but the answer did not satisfy the exact-symbol oracle. |
| `symbols-001` | Baseline | Pass | Pass | 21 | Successful unassisted control. |
| `documentation-001` | Codira MCP | Pass | Pass | 18 | Successful assisted result; 355,662 reported tokens. |
| `documentation-001` | Baseline | Pass | Pass | 9 | Successful control; 98,687 reported tokens. |

The canonical report counts 5 operational passes, 3 oracle passes, 2 oracle
failures, and 1 oracle not evaluated. It admits only the documentation pair
for a paired token comparison; the symbols pair is excluded for an
unsuccessful outcome and the patch pair for incomplete usage.

## Environment and tooling assessment

The Pilot 015 launch stopped before provider execution because its campaign
manifest put the fixture-image profile fingerprint in the Codira-profile
field. The profile mismatch was caught before a paid call; Pilot 015 remains
immutable and is not a task result. The factory/runtime checks were corrected,
and Pilot 016 used the Codira profile fingerprint
`fa488cb0c8bf6d591bd53a7140da8977e6d37e035427aa469d25578fdc47c854` with the
digest-pinned image
`localhost/codira-phase6-fixtures@sha256:9b016269b92bf10b88b33cc7288dc16c4b62f2579b954e33d5166bdb633c1c8b`.

All three assisted attempts recorded successful `uv` environment preparation
(exit status 0). Their attempts completed without an environment-preparation
failure, and all 98 upstream requests in the six attempts returned HTTP 200.
The baseline patch arm then received one additional **local** HTTP 429 after
using its 25 allowed logical requests. Thus the 25-call cap, not upstream
throttling, truncated that baseline attempt. The report separates operational
success from task-oracle correctness; MCP/provider success did not imply a
correct symbols or patch answer.

Five attempt records have complete normalized usage. The baseline patch
record is incomplete because it terminated at the local request cap, although
per-response metadata was retained for its 25 upstream responses. Across all
upstream response metadata the run contains 1,383,887 input tokens and 18,246
output tokens. The sum of per-response max-rate cost estimates is about
`$0.4371`; this is an estimate from response usage, not an invoice or an exact
postflight charge. No postflight key-balance snapshot was captured, so exact
billed spend should not be claimed.

## What this says about model and task quality

Pilot 016 does not justify a conclusion that MiniMax M2.5 is either unsuitable
or effective for Codira-assisted work. It completed the documentation task in
both arms, but that sole valid pair shows substantially higher token use with
Codira MCP and cannot support a stable comparison. On symbols, the baseline
passed while the assisted arm failed the frozen exact-answer oracle. On the
patch task, the assisted arm completed operationally but failed the behavioral
oracle; the baseline was censored by its cap. Those are real negative quality
signals, not environment failures, but this tiny, mixed set cannot separate
model capability, task/prompt effects, and Codira's contribution reliably.

The run also shows that raising the ceilings did not make every trajectory
productive: one baseline reached the cap, while assisted symbols and patch
attempts used fewer than 25 requests and still missed their oracles. More
requests alone are therefore not a sufficient remedy. Future work should
inspect the failed answer/patch against the frozen oracle, then use a fresh
campaign identity only if task wording or controls change. Do not relaunch
Pilot 016 or reinterpret its incomplete pair as a pass/fail comparison.

## Durable evidence and validation

- Versioned input: `benchmarks/agent-efficiency/campaign-specs/codira-efficacy-pilot-016.json`
- Generated manifest, plan, and launch receipt: `.artifacts/ae/016/factory/` and `.artifacts/ae/016/x/launch-receipt.json`
- Preflight: `.artifacts/ae/016/x/preflight.json` (passed before launch)
- Attempt records and exact provider responses: `.artifacts/ae/016/x/state/`
- Pilot exit: `.artifacts/ae/016/x/pilot.exit` (0)
- Full repository gate: `.artifacts/ae/016/validation-r11.log` and
  `.artifacts/ae/016/validation-r11.exit` (`1145 passed, 4 skipped`; exit 0)

These ignored artifacts preserve operational evidence locally. This tracked
post-mortem preserves the analysis without copying raw provider responses or
runtime state into Git.
