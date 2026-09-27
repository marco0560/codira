# Agent-efficiency Pilot 016 forensic review

Date: 2026-09-26
Scope: Pilot 016 evidence, accumulated project churn, and the benchmark methods
published by jCodeMunch MCP and CodeGraph.

## Finding

Pilot 016 is operationally complete and scientifically inconclusive. It does
not show that Codira MCP improves successful software work. The six attempts
produced only one fully comparable pair: both `documentation-001` arms passed,
and the Codira-MCP arm reported 355,662 tokens against 98,687 for baseline.
That single pair is a negative observation, not a stable estimate. The symbols
pair has an assisted oracle failure; the patch pair has an assisted oracle
failure and a baseline cut off by the local continuation cap. Keep the reported
operational and task-oracle outcomes separate, as the post-mortem does.

The main diagnosis is a measurement-design and task-validity problem, with
some execution constraints contributing. The evidence does not support
blaming MiniMax M2.5 alone, nor does it support simply buying a stronger model
or raising every cap. In the assisted symbols and patch attempts, the model
used fewer than 25 logical requests and still missed the frozen oracle. More
budget would not by itself repair those failures. Conversely, the baseline
patch attempt was censored by the 25-request local ceiling and cannot be called
a task failure.

## What the pilot establishes

- All six attempts reached terminal records; the launcher exited 0.
- All 98 upstream requests returned HTTP 200. The extra HTTP 429 in the
  baseline patch arm was generated locally after its 25-request allowance,
  not by provider throttling.
- Oracle outcomes: three passes, two failures, one not evaluated. Only the
  documentation pair has complete usage and passing oracles on both sides.
- On that pair, Codira MCP consumed about 3.6 times the reported tokens. This
  is a valid paired observation; the sample is too small to generalize.
- The exact billed spend is unknown: no postflight key-balance snapshot was
  captured. The approximate $0.4371 response-usage estimate is not an invoice.
- Pilot 015 was stopped before paid execution by a profile-fingerprint
  mismatch. It is a factory/preflight defect, not a model or task result.

The symbols failure is an answer-quality signal because the baseline passed
and the assisted arm did not. It does not isolate whether the cause was model,
prompt, retrieval, or oracle wording. The patch failure is also a real failure
against the frozen task contract, but the cause remains unresolved. The task
asks to preserve `click.Option(...).default` through copy, deepcopy, and
pickle; the protected probe reportedly exercises copying the full `Option`
object. Inspect the saved diff, prompt, and probe together before deciding
whether the task was under-specified or the implementation was wrong. Do not
rewrite the existing record to resolve that ambiguity.

## Churn assessment

The branch contains 48 commits and changes 144 tracked files versus
`origin/main` (+26,724 / -8 lines). That is a large implementation and process
footprint relative to the evidence currently available: one eligible paired
observation. The churn includes valuable infrastructure—immutable campaign
identities, provider-response preservation, distinct continuation and
transport limits, fixture isolation, and separate operational/oracle
reporting—but repeated calibrations and pilots have not yet yielded a
multi-task efficacy result.

This gap is not solved by discarding the infrastructure or by expanding it.
Pause new paid runs while the existing failure evidence is reconciled and the
measurement target is narrowed. Keep historic attempts immutable. Any changed
task, prompt, model, runtime, or budget gets a new factory-generated identity.

## How the two named products support their claims

These are useful protocol references, but their figures are not directly
comparable to Pilot 016: they measure different workloads, tools, and outcomes.

| Product and published study | Tasks used | Execution and accounting | What the result establishes | Main limitation |
| --- | --- | --- | --- | --- |
| [jCodeMunch synthetic benchmark](https://github.com/jgravelle/jcodemunch-mcp/blob/main/benchmarks/METHODOLOGY.md) | Fifteen retrieval queries: five intents (`router route handler`, `middleware`, `error exception`, `request response`, `context bind`) across pinned Express, FastAPI, and Gin snapshots. The treatment searches the top five symbols and fetches the top three. | Same corpus and file reader; compares the tool with read-all and a grep-top-three baseline. Counts serialized response JSON with `tiktoken` `cl100k_base`; AI summaries disabled. Harness, task list, pinned commits, and reproduction instructions are published. | Retrieval payload size under that fixed query and retrieval procedure. The README reports 28.3x fewer tokens than grep-top-three. | The methodology explicitly excludes answer quality, latency, and task completion. The read-all figure is a ceiling; grep-top-three is the more relevant baseline. Published counts include disclosed ±1-token runtime metadata jitter. |
| [jCodeMunch naming-audit A/B](https://github.com/jgravelle/jcodemunch-mcp/blob/main/benchmarks/ab-test-naming-audit-2026-03-18.md) | Fifty fresh sessions on one Vue/Vite/Vuetify/Firebase codebase, 25 per arm. Each scans for misleading, ambiguous, or inconsistent names and applies fixes; findings use a three-subagent consensus step. | Claude Sonnet 4.6, native Grep/Glob/Read versus jCodeMunch outline/symbol/importer/search tools, alternating variants, 600-second timeout. Reports success, timeouts, mean cost, output tokens, cache creation, and duration. | A limited end-to-end comparison: 20/25 versus 18/25 successful iterations; mean cost $0.738 versus $0.783. The claimed 15–25% tool-layer saving comes from a small post-hoc subset with zero findings, while blended cost fell 5.7%. | One repository and one task family; 25 runs per arm; alternation is reported but a randomized assignment or paired analysis is not. The isolated 15–25% estimate uses very small buckets and is not the headline end-to-end effect. |
| [CodeGraph architecture-question benchmark](https://github.com/colbymchenry/codegraph) | Seven architecture questions, one each for VS Code, Excalidraw, Django, Tokio, OkHttp, Gin, and Alamofire. | Claude Code headless with Claude Opus 4.8; CodeGraph MCP versus empty MCP while Read/Grep/Bash remain available. Four runs per arm per repo; median reported. Counts provider cost, all tokens per assistant turn including cache input/output, wall time, and every tool call including subagents. Repo snapshots are shallow clones indexed with the measured build. A sanitized PATH and PreToolUse hook block CLI access in both arms; all 28 control attempts were blocked. | Agent effort to answer those seven fixed architecture questions. README reports 88% fewer tool calls, 53% faster, 62% fewer tokens, and 44% lower cost. | The README describes the task as answering an architecture question but does not state a correctness rubric or report answer-quality scores. Four repetitions per arm provide a small sample. A separate context-occupancy note says the dense retrieval response leaves more context resident, an effect not captured by processed-token totals. |

The strongest design lessons for Codira are:

1. State what the benchmark measures. Retrieval payload efficiency and
   end-to-end successful task efficiency are different claims. The former can
   explain mechanism; it cannot substitute for the latter.
2. Use tasks with explicit, independently checked success conditions. A task
   should resemble ordinary exploration or implementation, but its oracle must
   match the wording and expected artifact exactly. Report completion rate
   alongside resource use.
3. Define the baseline as the actual competent workflow available to the
   agent, including ordinary search and file-reading tools. Ensure the
   treatment cannot leak into the control through a CLI or another path.
4. Freeze and report the model, tools, repository revisions, prompt, index,
   budgets, repetitions, order, timeout policy, token fields, cost source, and
   exclusions. Preserve each run so the summary can be recalculated.
5. Report distributions and per-pair outcomes, not just a favorable mean.
   Separate cost-to-success from costs of failed, censored, or incomplete
   runs; do not count a local cap rejection as provider throttling.

## Recommended next steps

1. **Forensic reconciliation, no paid calls:** inspect the saved Pilot 016
   symbols and patch answers/diffs against their exact task files and protected
   probes. Establish whether the task text, oracle, or attempt output explains
   each miss. Retain “unresolved” where the evidence cannot decide.
2. **Small benchmark-design revision:** retain the existing task/oracle
   discipline, but add a few focused architecture and code-navigation tasks
   inspired by the question style in CodeGraph, with deterministic fact
   oracles. Keep patch tasks in a distinct task stratum. Do not convert
   retrieval-token microbenchmarks into the primary outcome.
3. **Choose a representative model for the question being asked:** first
   repair task clarity and run the same model in both arms. A stronger model
   may be a later robustness check, not the first intervention. If results
   differ by model, report the interaction; do not select the winning model
   after seeing results.
4. **Bound the next run around observed trajectories:** choose a cap that
   admits a complete task with a modest reserve, after inspecting turn and
   usage traces. Keep the same cap within each pair. Treat cap exhaustion as a
   censored/unsuccessful execution with its own cause, not evidence about
   correctness. Do not raise caps across both arms without a stated hypothesis.
5. **Predefine a small go/no-go pilot:** use a few task families and paired
   repetitions, report every outcome and token/cost measure, and set the
   decision rule before execution. Continue to a larger campaign only if the
   task success rate is acceptable and the resource result is interpretable.
6. **Use a separate model robustness check only after the protocol passes.**
   Model comparison is not the primary question; Codira's effect within a
   fixed model is.

The project ledger already calls for paired repetitions, deterministic
oracles, full outcome reporting, and provider-reported token accounting. The
immediate change should be to validate that protocol against reconciled task
failures and competitor-style navigation questions—not to add another layer of
runner machinery.

## Evidence and remaining gap

Codira evidence: [Pilot 016 post-mortem](agent-efficiency-pilot-016-postmortem-2026-09-25.md),
[calibration handoff](agent-efficiency-calibration-handoff-2026-09-20.md), and
[Issue #53 execution ledger](issue-053-agent-efficiency-benchmark-ledger.md).
Raw records and provider responses remain in ignored
`.artifacts/agent-efficiency/attempts/016/`
state; this review does not duplicate them into Git.

The supplied ChatGPT conversation at
<https://chatgpt.com/c/6a6f07e5-c4b0-83ed-85ae-a20542eaf5ad> was not readable in
this environment (the page returned an internal error). Its contents have
therefore not been incorporated. If that evaluation contains task definitions,
run commands, or measurements not present in the public repositories, add an
export or paste those relevant parts before treating this review as complete.
