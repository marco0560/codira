# Agent-efficiency Pilot 025 comparison — 2026-09-29

## Summary

Pilot 025 completed with exit code 0. All six attempts passed operational
calibration and the task oracle. It used OpenRouter with
`openai/gpt-6-luna` at high reasoning, the `mcp-required-v2` treatment, and a
1,000,000-token whole-session cap.

Pilot 023 was the preceding completed pilot. Pilot 024 has a launch receipt but
no pilot exit record, so it did not produce a completed run. Pilot 023 and 025
used the same model, provider, reasoning effort, request and token limits,
timeout, runtime profile, and fixture fingerprints. The fingerprints for
`documentation-001` and `context-page-001` are also unchanged. The
`patch-002` task fingerprint changed, and its grader asset handling was fixed.

The task-oracle pass count rose from four of six in Pilot 023 to six of six in
Pilot 025. The two Pilot 023 failures were both patch attempts: the patches
applied, but the protected grader command could not find `patch_002_probe.py`
in its fixture directory. Operational calibration passed for those attempts.
This was a grader execution defect, so those results do not establish whether
the candidate patches were correct. Pilot 025 records the protected asset's
digest and both protected checks pass.

This makes the overall result better, but it does not show a model improvement
on an unchanged patch task. Pilot 025 also strengthened that task: it requires
round-tripping the whole `click.Option(['--name'])` instance through
`copy.copy`, `copy.deepcopy`, and pickle, then checking both its name and
`UNSET` default. The oracle now requires both implementation and test paths and
restricts patches to those paths. The patch results are therefore not a strict
like-for-like quality comparison.

## Pilot 025: baseline versus Codira MCP

| Task | Baseline | Codira MCP | Reading |
| --- | --- | --- | --- |
| `documentation-001` | Pass; 8 requests; 52.8 s; 187k input / 3.8k output tokens; estimated ceiling cost $0.050; 14 shell commands | Pass; 10 requests; 76.5 s; 234k input / 5.2k output tokens; $0.062; 13 shell commands and 6 MCP calls | Both meet the oracle's three required heading checks. The baseline guide adds an example for matching multiple patterns; the MCP guide shows multiple ignore patterns. The oracle does not grade depth or factual completeness. |
| `context-page-001` | Pass; 9 requests; 87.4 s; 211k input / 6.1k output tokens; $0.057; 18 shell commands | Pass; 10 requests; 74.5 s; 244k input / 4.6k output tokens; $0.065; 8 shell commands and 6 MCP calls | Both identify the required method and test. MCP reduced shell commands by 56% and elapsed time by 15%, while using 16% more input tokens. The baseline note also mentions the method's MCP registration. |
| `patch-002` | Pass; 15 requests; 130.4 s; 372k input / 12.6k output tokens; $0.102; 21 shell commands | Pass; 24 requests; 196.8 s; 633k input / 15.3k output tokens; $0.170; 23 shell commands and 2 MCP calls | Both patches apply, change the required implementation and test files, and pass the protected probe. The MCP trajectory explicitly runs the focused pytest command successfully. Its patch uses a broader `Any` return annotation than the baseline patch's `type[Sentinel]`. MCP used 70% more input tokens and took 51% longer. |

Estimated costs use the campaign's configured maximum per-token rates. They
are ceilings, not confirmed provider invoices.

Across the three independent attempts per arm, baseline used 32 response
requests and MCP used 44. Summed attempt time was 270.6 seconds for baseline
and 347.8 seconds for MCP; estimated ceiling cost was $0.209 and $0.297,
respectively. MCP issued fewer shell commands overall (44 versus 53), but its
14 MCP calls brought total recorded tool actions to 58 versus 53 for baseline.
This is not a general efficiency win: the context task improved on shell
activity and time, while documentation and patch attempts took longer and
cost more in the MCP arm.

No configured cap appears to have bound. The largest attempt used 648,626
input-plus-output tokens, below the 1,000,000-token session cap; the largest
request count was 24 of 30; and the longest attempt took 196.8 seconds against
an 1,800-second timeout. The token budget does not explain the success
difference: the same 1,000,000-token cap was already in place for Pilot 023.

## Pilot 023 versus Pilot 025

All values below are baseline → Codira MCP. Both arms passed the task oracle
for the unchanged documentation and context tasks in both pilots.

| Task | Pilot 023 | Pilot 025 | Interpretation |
| --- | --- | --- | --- |
| `documentation-001` | 15 → 12 requests; $0.095 → $0.077; both pass | 8 → 10 requests; $0.050 → $0.062; both pass | The relative request and cost advantage reversed. The task fingerprint is unchanged, so this pair shows substantial run-to-run trajectory variation. |
| `context-page-001` | 16 → 10 requests; $0.078 → $0.058; 107.0 → 82.8 s; both pass | 9 → 10 requests; $0.057 → $0.065; 87.4 → 74.5 s; both pass | MCP used fewer requests and cost less in P023. In P025 it used one more request and more tokens, but still finished faster and used fewer shell commands. |
| `patch-002` | 10 → 11 requests; $0.057 → $0.056; both protected checks failed because the grader script was missing | 15 → 24 requests; $0.102 → $0.170; both protected checks pass | Not a like-for-like comparison: P025 changed the prompt and path oracle, and repaired protected-asset admission. P023's patch correctness was not evaluated by its protected check. |

Across all attempts, estimated ceiling cost was about $0.422 in P023 and
$0.506 in P025. Within P023, the MCP arm cost less than baseline ($0.191
versus $0.231); within P025, it cost more ($0.297 versus $0.209). The sign
change, together with the unchanged tasks' differing trajectories, is not
enough evidence for a stable MCP treatment effect. Each task had only one pair
per pilot.

## Conclusions and next steps

- The P023 patch failure was caused by a missing grader asset, not an
  operational/provider failure. The saved stderr reports that the protected
  Python command could not open `patch_002_probe.py`. Pilot 025 admitted the
  protected script by digest and retained its identity in each patch record.
- The 6/6 task-oracle result in P025 is a real end-to-end pass for the updated
  campaign. It should not be described as proof that the model improved over
  P023 on the same patch task.
- Codira MCP helped most clearly on `context-page-001` in P025, where shell
  exploration and elapsed time fell. The two pilots disagree on relative
  request and cost efficiency for unchanged tasks, so more paired repetitions
  are needed before claiming a general benefit.
- Keep the 1,000,000-token cap for the next comparison; P025 did not approach
  it. Improve discrimination with repeated pairs and stronger content-quality
  grading, and preserve explicit checks for required workflow steps such as
  running the focused test.

## Evidence

- Pilot 023 campaign manifest (`.artifacts/agent-efficiency/campaigns/codira-efficacy-pilot-023/campaign.json`)
- Pilot 025 campaign manifest (`.artifacts/agent-efficiency/campaigns/codira-efficacy-pilot-025/campaign.json`)
- Pilot 023 baseline patch record (`.artifacts/agent-efficiency/executions/p023/state/records/patch-002-r01-baseline.json`) and MCP patch record (`.artifacts/agent-efficiency/executions/p023/state/records/patch-002-r01-codira-mcp.json`)
- Pilot 023 baseline protected-command stderr (`.artifacts/agent-efficiency/executions/p023/state/attempt-work/patch-002-r01-baseline/oracle-trace/command-003.stderr.bin`)
- Pilot 023 MCP protected-command stderr (`.artifacts/agent-efficiency/executions/p023/state/attempt-work/patch-002-r01-codira-mcp/oracle-trace/command-003.stderr.bin`)
- Pilot 025 baseline patch record (`.artifacts/agent-efficiency/executions/p025/state/records/patch-002-r01-baseline.json`) and MCP patch record (`.artifacts/agent-efficiency/executions/p025/state/records/patch-002-r01-codira-mcp.json`)
- [Pilot 025 protected-asset provenance](https://github.com/marco0560/codira/blob/main/benchmarks/agent-efficiency/protected/patch-002/provenance.json)
