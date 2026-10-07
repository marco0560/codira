# Pilot 010 inconclusive report — 2026-09-23

## Decision

`codira-efficacy-pilot-010` completed all six scheduled executions and its
runner exited zero. It is operationally complete but scientifically
inconclusive: two baseline attempts passed their deterministic task oracles,
while the remaining four attempts ended at immutable safety controls. No task
has one successful baseline result and one successful Codira-MCP result, so
the run cannot support a treatment, token, cost, or success-rate comparison.

Do not retry Pilot 010 or alter its evidence. Any successor requires a fresh
factory-generated campaign identity, an updated bounded accounting decision,
and separate explicit authorization for further provider spend.

## Immutable evidence boundary

The factory input is
`benchmarks/agent-efficiency/campaign-specs/codira-efficacy-pilot-010.json`.
Its generated campaign fingerprint is
`36784f72fd525855e8c75a54d0e1e0d6379ea0bd418483b13669e0d87eeda473`.

Ignored, durable execution evidence is rooted at `/home/marco/ae/010`, not
`/tmp` or a user cache. It contains the launch receipt, authenticated preflight
record, terminal exit status, state document, six immutable attempt records,
three index-preparation receipts, JSONL streams, and exact response bodies.
Raw provider bodies remain outside Git; records retain only public-safe status,
digest, size, and artifact-name bindings.

The runtime was
`localhost/codira-phase6-fixtures@sha256:1ff8b585f11e4d18550b4be282e9bb499fd995062ee1e62cdd0ba3a16b9ed66b`.
The exact authenticated route was `deepseek/deepseek-v4.1-flash` at medium
reasoning. The manifest bounded each attempt to 12 logical Responses requests,
240,000 whole-session tokens, 32,000 output tokens, 900 seconds, and two
transport attempts per logical request.

## What completed

- The pilot process exited `0` and emitted six terminal records with no pending
  attempt identities.
- All three assisted index preparations were usable: `ready`, non-partial,
  zero failed files, and 454 indexed Codira files, 123 indexed Click files,
  and 67 indexed Picomatch files.
- All attempts completed within the 900-second timeout. Environment
  preparation also returned zero for every attempt.
- The proxy persisted 62 exact upstream response bodies, matching its 62
  forwarded upstream HTTP `200` requests. Three additional local synthetic
  `429` rejections enforced the logical-request ceiling and did not represent
  upstream provider throttling.

## Results

| Task | Baseline | Codira-MCP | Result |
| --- | --- | --- | --- |
| `symbols-001` | Success; oracle passed; 8 requests | `usage_cap_exceeded`; 9 requests | Incomplete pair |
| `patch-001` | `local_request_cap_exceeded`; 12 requests | `local_request_cap_exceeded`; 12 requests | Incomplete pair |
| `documentation-001` | Success; oracle passed; 9 requests | `local_request_cap_exceeded`; 12 requests | Incomplete pair |

The two successful records both have complete usage and passed operational and
task-oracle checks. The three local-request-cap records have intentionally
incomplete usage because the terminal event is a local rejection, not a
completed provider response. The assisted symbols record has complete usage
but failed the whole-session token admission check.

## Cause analysis

### Safety controls, not environment admission

The final run did not reproduce the earlier pre-provider defects. Pilot 007
stopped at unusable index admission, Pilot 008 at an overlong Unix-domain
socket path, and Pilot 009 at a workspace snapshot following dangling prepared
virtual-environment symlinks. Those identities remain immutable. The repairs
were committed before Pilot 010:

- `0004752` embeds the benchmark index profile in the fixture image;
- `5432479` excludes `.venv` from workspace-diff snapshots;
- Pilot 010 uses the short durable root `/home/marco/ae/010`, whose longest
  provider socket path is 90 bytes rather than the prior 144 bytes.

The full repository gate after the snapshot repair passed with 1,137 passed
and 3 skipped. Consequently, index construction, socket naming, fixture
environment preparation, snapshots, provider connectivity, and wall-clock
timeouts are not evidenced causes of Pilot 010's inconclusive result.

### Request ceiling was insufficient

Three attempts received twelve upstream HTTP `200` responses and then tried a
thirteenth logical continuation. The local proxy correctly rejected that next
request with `429`, which the runner classifies as
`local_request_cap_exceeded` rather than a provider rate limit.

The patch task reached this ceiling in both treatments. That symmetric failure
is evidence that the 12-request policy is too small for the observed task and
agent trajectory; it is not evidence that Codira-MCP caused the patch failure.
The assisted documentation arm also reached the same ceiling, whereas its
baseline counterpart completed in nine requests. That difference is compatible
with MCP exploration overhead, but one pair cannot establish a causal effect.

### Whole-session token ceiling was insufficient for assisted symbols

The assisted symbols execution completed normally at the process/provider
level but reported 133,910 input, 116,480 cached input, 1,406 output, and 253
reasoning-output tokens: 252,049 total. This exceeds the frozen 240,000
whole-session limit by 12,049 tokens, so the runner correctly recorded
`usage_cap_exceeded` and did not evaluate the task oracle.

The baseline symbols execution passed using 84,253 input, 68,096 cached input,
2,022 output, and 620 reasoning-output tokens. The contrast suggests that the
assisted trajectory may have accumulated more context or tool-use overhead,
but the incomplete assisted result cannot measure the size or cause of that
effect.

### Why the experiment has no comparative conclusion

Paired efficacy requires evaluable outcomes for both treatments of the same
task. Pilot 010 has two successful baseline observations and zero successful
assisted observations. Treating local cap enforcement or token-admission
rejection as a treatment loss would confound the controls with agent quality.
Similarly, the records do not provide complete normalized usage for the three
locally rejected attempts. The correct conclusion is therefore an operational
control finding, not a baseline-versus-Codira result.

## Evidence-backed successor constraints

A fresh authorized campaign must retain the same immutable-evidence and
no-retry rules. The minimum facts established by Pilot 010 are:

1. the logical request ceiling must be above 12, because three trajectories
   attempted a thirteenth continuation;
2. the whole-session token ceiling must exceed 252,049 for the observed
   assisted symbols trajectory;
3. any larger cap raises worst-case provider exposure, so the per-attempt,
   pilot, and daily-spend ceilings must be recalculated and explicitly
   approved; and
4. new measurements must use a new factory campaign identity and fresh durable
   execution root. Pilot 010 itself must remain unchanged.

These are lower bounds, not a proposed budget. Choosing practical request,
token, timeout, and spend limits requires an explicit follow-up decision.
