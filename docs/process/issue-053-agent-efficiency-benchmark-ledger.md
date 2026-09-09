# Issue #53 — Agent Efficiency Benchmark Execution Ledger

## Authority and objective

Approved by the operator in the planning conversation on 2026-09-08, including
the amendments covering repetitions, analysis deliverables, a CLI follow-up,
ledger-based execution, memory isolation, and separate implementation and test
campaign branches.

Implement <https://github.com/marco0560/codira/issues/53>: reproducibly compare
ordinary agent repository work with the same work assisted by Codira MCP.
The primary measurement is provider-reported tokens to a successful outcome,
subject to deterministic task oracles. Positive savings are not a completion
requirement. Accurate negative or inconclusive findings are valid outcomes.

This ledger is the plan and execution record. Update it as work progresses;
do not create a parallel plan with independently maintained status.

## Approved decisions

| ID | Decision |
| --- | --- |
| R1 | Codex CLI first, behind a runner-neutral contract and offline test adapter. |
| T1 | MCP-only Codira assistance for the primary experiment. |
| C1 | Six tasks total across three public repositories, covering all six issue categories. |
| F1 | Agent proposes and verifies public repositories and immutable revisions. |
| E1 | Full public campaign and report required before closing #53. |
| Budget | Propose benchmark model and full-campaign limits after the pilot estimate. Pilot itself needs a bounded execution manifest before launch. |
| I1 | Container isolation, validated before measured execution. |
| B1 | Prepared index; indexing costs reported separately. |
| P1 | Private-fixture contract, ignored template, and synthetic privacy tests; no actual private fixture required. |
| W1 | One implementation agent, atomic phase commits, separate review checkpoints. |
| Memory | No Codex memory, previous session state, or cross-repetition learning accessible to benchmark agents. |
| Branches | Separate branches for implementing the suite and running the campaign. |
| Registry | Publish the reviewed benchmark image to GitHub Container Registry as `ghcr.io/marco0560/codira-agent-benchmark`; use only its immutable digest at execution time. |
| Auth | Use a runner-side OpenRouter provider proxy. The benchmark agent receives neither an OpenRouter credential nor a GitHub Packages credential. |

RepoIRBench is not a runtime dependency of this suite. Retrieval-only scores
do not replace end-to-end task success or token accounting.

## Branch and evidence policy

- Implementation branch: `feat/issue-053-agent-efficiency-benchmark`.
- Campaign branch: `experiment/issue-053-agent-efficiency-benchmark`.
- Create the campaign branch from the reviewed, validated implementation
  commit after Phases 0–5; record that full SHA below. Do not create it from
  an earlier incomplete implementation or select its base from a moving ref.
- Run the pilot and full campaign from the campaign branch. Use disposable
  fixture worktrees/containers, never either branch checkout as an agent's
  writable benchmark fixture.
- Freeze harness, Codira, task, fixture, runner, model, and configuration
  identities for each experiment. The Codira fixture revision and the Codira
  tool revision are distinct recorded identities.
- Fix harness defects on the implementation branch, validate and commit them,
  then carry them forward normally without rewriting campaign history. Changed
  experimental inputs require a new experiment identity; never silently combine
  results across revisions.
- Public sanitized reports and ledger updates belong on the campaign branch.
  Raw runs, indexes, private data, credentials, and generated runtime state
  stay ignored. Preserve evidence supporting failed and interrupted attempts.
- No automatic merge, publication, release, or issue closure is authorized by
  approval of this plan. Report completion readiness and remaining actions.

Implementation base at planning: `32603dcddd0325939fc3f3c1b36d7d90e4a038b0`.
Validated campaign base: pending.

## Fixture and task register

Repository visibility, GitHub license metadata, and revisions were checked
through SOPS-scoped GitHub CLI queries during planning. Runtime builds,
license notices at each revision, size inventories, and reference oracles must
still pass the implementation gates. A failed fixture admission requires a
recorded replacement proposal, not a silent substitution.

| Fixture | Revision | License metadata |
| --- | --- | --- |
| `marco0560/codira` | `32603dcddd0325939fc3f3c1b36d7d90e4a038b0` | MIT |
| `pallets/click` | `420c8fb44eeadb537cae69d2fee3796e808558dd` | BSD-3-Clause |
| `micromatch/picomatch` | `570df2f8781bc92e5fece2c16d9ff990c4a8d1da` | MIT |

| Task ID | Category / fixture | Task and oracle direction |
| --- | --- | --- |
| `symbols-001` | Symbol discovery / Codira | Locate the MCP context endpoint and underlying context builder; check canonical path, qualified name, and kind. |
| `impact-001` | Impact analysis / Codira | Identify direct callers affected by changing the MCP adapter `_query` contract; check independently curated identities and paths. |
| `localize-001` | Bug localization / Click | Diagnose copying/pickling failures involving unset option defaults; check responsible implementation and structured causal facts. |
| `patch-001` | Patch preparation / Click | Repair duplication while preserving sentinel singleton identity; apply patch to a pristine checkout and run protected regression tests. |
| `architecture-001` | Architecture investigation / Picomatch | Describe entry point, matcher, parser, scanner, and direct relationships; check structured module/edge facts. |
| `documentation-001` | Documentation generation / Picomatch | Produce a short guide with matching, ignore, and case-handling examples; check facts, sections, and executable example behavior. |

Click source fix: `f58ca3e81424a35626c8a475eb59ab95589008ce`, whose parent is
the registered fixture revision. Verify regressions fail on the parent and
pass on the source fix. Protect the source fix and grading expectations from
benchmark agents. Localization and patch tasks use independent sessions; disclose
their shared underlying bug and do not claim they are independent bug samples.

## Measurement and isolation contract

1. Each task requires a category-specific `.benchmark/result.json`; a missing
   or invalid file is an oracle failure. A chat response is not a substitute.
2. Use identical source trees, setup, fixed prompt, model/effort, ordinary tools,
   and execution budgets within each pair. Record randomized order and seed.
   Codira MCP availability and its tool descriptions are the intended difference.
3. Create fresh agent state for every repetition. Disable memory and delegation;
   exclude host memories, previous sessions, personal skills, plugins, unrelated
   MCP servers, other runs, oracle inputs, and future solution commits.
4. Verify effective configuration and filesystem/network isolation with
   contamination probes before measurement. A new session or ephemeral flag
   alone is insufficient proof. Stop if isolation cannot be demonstrated.
5. Implementation agents may use project memories; benchmark agents may not.
   Normalize inherited/project agent instructions identically for both variants,
   record the exclusions, and retain identical declared task instructions.
6. Keep Codira runtime and prepared state behind the MCP service boundary.
   Ordinary task tools cannot read the index or invoke the installed retrieval
   runtime directly. Codira fixture source remains visible to both variants;
   test and document controls preventing an alternate retrieval execution path.
7. Require MCP startup in assisted runs; initialization failure is an
   infrastructure failure. Pin exposed tools, budgets, plugins, semantic mode,
   and any model artifacts before the campaign. No implicit model downloads.
8. Provision dependencies before measurement. Restrict task network access;
   allow only the runner's required provider connection through the validated
   execution design. Scope credentials to their intended processes, without
   exposing them to repository commands, traces, or model-visible output.
9. Prepare separate reproducible index state for each assisted run before its
   timer begins; report preparation cost separately. Record that retrieval is
   based on the initial fixture snapshot. Do not silently refresh after edits;
   use ordinary file tools for changed content and report stale-index effects.
10. Grading takes place outside the agent environment. Evaluate patches against
    pristine source and protected tests. Defend against modified tests, forged
    command results, symlink/path escapes, and oracle-data access.
11. Preserve provider usage and provenance. Verify overlapping/cumulative field
    semantics before summation; do not double-count cached input or reasoning.
    Unavailable fields are `null`. Incomplete usage is ineligible for token-saving
    comparisons, even if an artifact passes its oracle.
12. Tool-payload tokens are separate diagnostics with tokenizer/version and
    capture limitations. Never substitute them for total agent consumption.
13. Report all attempts and success rates. Compute paired savings only where
    both variants pass. Report successful-run distributions separately and
    disclose exclusions, missing accounting, and infrastructure failures.
14. Use five repetitions per public pair as required by #53: six tasks × two
    variants × five repetitions = 60 executions. Five provides more observations
    than three/four (36/48 executions), but does not establish statistical
    significance. Show individual paired observations; label p90 as unstable
    at this sample size. Additional repetitions need a predefined rule and budget,
    never continuation until favorable results appear.
15. Resume only validated completed records. Preserve unsuccessful attempts;
    do not retry task failures until success. Record infrastructure retry policy
    and every attempt. Replay/rescore reports without rerunning agents.

## Architecture and intended artifacts

- Entry point: `scripts/run_agent_efficiency_benchmark.py`.
- Modules: `scripts/agent_efficiency/` containing contracts, manifests, fixture
  preparation, oracles, runner adapters, containers, campaign state, usage, and
  reporting. Use focused modules rather than a monolithic script.
- Public assets: `benchmarks/agent-efficiency/` with schemas, fixtures, tasks,
  oracle support, container definitions, and sanitized reports.
- Tests: focused `tests/test_agent_efficiency_*.py` modules.
- User methodology/runbook: `docs/agent-efficiency-benchmark.md`.
- Runtime artifacts: ignored campaign storage, with immutable raw evidence,
  atomic result records, fingerprints, and resumable state.

Currently `.gitignore` ignores all `benchmarks/`. Introduce narrow exceptions
for approved public assets, preserving exclusions for private manifests, raw
traces, indexes, worktrees, and local state. Generate schema artifacts through
their generator. Reuse appropriate repository helpers without changing the
semantics of existing timing or retrieval-quality campaigns.

Oracle DSL: `contains_symbols`, `contains_paths`, `command_passes`,
`patch_applies_and_tests_pass`, `normalized_artifact`, `all_of`, and `any_of`.
Specify normalization and thresholds per task. The custom-evaluator escape
hatch requires a versioned local script, focused tests, manifest rationale,
deterministic result contract, no LLM calls, and no access to variant identity.
Report custom/exploratory cases distinctly. Do not claim general writing quality
from deterministic documentation checks or require exact prose/patch equality.

## Execution status vocabulary

`pending` → `in_progress` → `validated` → `complete`.
Use `blocked` only with an explicit unmet prerequisite and next action.
Every phase completion records evidence and an atomic commit. Never fill evidence
fields with planned or inferred test results.

## Phase 0 — Runner and isolation conformance

Status: complete. Commit: atomic Phase 0 commit on the implementation branch.
Evidence: the secret-free Phase 0
verifier and its focused tests are implemented on the implementation branch.
On 2026-09-08, `ruff format`, `ruff check`, `mypy`, and the focused test module
passed (22 tests). The verifier now rejects inherited credentials/state,
unexpected MCP use in the baseline, missing cancellation evidence, and missing
or unblocked mandatory escape probes. It also produces credential-free,
network-disabled, read-only container commands and public/protected sentinel
fixtures for deterministic containment probes. The reviewed Phase 0 image
Containerfile pins a linux/amd64 Python 3.13 base digest, and its local Podman
build succeeded on 2026-09-08 as
`localhost/codira-agent-efficiency-phase0:review` (image ID
`f8ede51cd8ff11b74d8e0c569cb10cab5cd813ae75befcaf56428363a2b23cd5`). On
2026-09-08 the reviewed image was published to
`ghcr.io/marco0560/codira-agent-benchmark:phase0-review-20260908`; its recorded
immutable manifest is
`ghcr.io/marco0560/codira-agent-benchmark@sha256:3647440cc3b727288bde32e5d651781f4869064c15c64f553474ca25d0aa00eb`.
The package is currently private, so a trusted runner must authenticate before
pulling it; the benchmark agent still receives no GitHub credential. A
network-disabled, read-only container probe confirmed Python 3.13.15, Git
2.47.3, and no Docker socket. The runner-side loopback OpenRouter Responses API
proxy and generated clean custom-provider Codex configuration are implemented
and unit-tested. On 2026-09-08 the proxy was converted from an OpenAI-specific
endpoint to the documented OpenRouter custom-provider contract: Codex sends
Responses requests only to a loopback `/v1` endpoint with a proxy token, and
the proxy forwards only the allowlisted paths to OpenRouter `/api/v1` using the
runner-side `OPENROUTER_API_KEY`. Neither process has forwarded a provider
request. The focused suite passed again (22 tests), together with `ruff` format
and lint checks and `mypy`. The initial host preflight
correctly failed closed because `codex`, Docker, and the digest-pinned image
were unavailable. On 2026-09-08 the operator installed Podman 5.8.2 and Codex
CLI 0.153.4, then ran the helper with Podman. It advanced through executable and
version validation and failed only because the deliberately nonexistent,
digest-shaped placeholder image was not locally available. No live agent turn,
JSONL probe, container isolation probe, or cancellation test has been run.
The existing SOPS-scoped OpenRouter credential was registered as an intended
consumer of the runner-side proxy and its presence was verified without
rendering it. The dedicated `codira-tests-key` has a provider-enforced USD 0.25
daily limit. The approved bounded probe manifest is
`benchmarks/agent-efficiency/phase0-live-probe.toml`: one conformance-only
attempt using `openai/gpt-5.6-terra` at medium effort, a 600-second timeout,
and a 12,000 maximum-output-token cap. It is excluded from paired savings
analysis. The live-probe launcher is implemented with a dry-run default
and an explicit paid-execution gate; it starts a loopback proxy, creates fresh
Codex state, and removes `OPENROUTER_API_KEY` from the Codex child environment.
Focused launcher, proxy, configuration, fixture, and manifest tests passed (26
tests), together with `ruff` and `mypy`. The fixture/MCP launcher dry run passed
on the host using the explicit Codex and `codira-mcp` executable paths. No paid
request completed. The first approved launch on 2026-09-09 was an
infrastructure failure: it produced no JSONL because the intentionally
non-Git disposable fixture lacked Codex's `--skip-git-repo-check` flag. The
runner now supplies that flag; the failed attempt is retained at
`/tmp/codira-phase0-live-events.jsonl` and is ineligible for comparison. One
corrected infrastructure retry reached the provider but was rejected before
generation: Codex requested its default 65,536 output-token allowance, which
exceeded the dedicated USD 0.25 daily key limit. Its JSONL evidence is retained
at `/tmp/codira-phase0-live-events-retry1.jsonl` and is ineligible for
comparison. The proxy now caps every Responses request at the manifest's 12,000
output-token ceiling; focused checks passed again (28 tests). The explicitly
approved second retry completed its required artifact and MCP work, but is
ineligible under the manifest because its provider-reported observed total was
69,577 tokens, exceeding the 12,000-token ceiling. The launcher now enforces
that admission ceiling after JSONL capture. The operator approved an 80,000
observed-total-token ceiling on 2026-09-09. The manifest retains the separate
12,000 maximum-output-token proxy cap so the provider request stays within the
USD 0.25 daily key limit. The revised-manifest retry completed successfully on
2026-09-09: it used Codira MCP, wrote the required `{"status":"ok"}` artifact,
and emitted complete usage evidence (69,065 input, 56,815 cached input, 578
output, and 104 reasoning-output tokens). Its observed total of 69,747 is
within the revised 80,000 ceiling. Evidence is retained at
`/tmp/codira-phase0-live-events-retry3.jsonl`; it remains conformance-only and
is excluded from comparative analysis. The non-billed escape probes passed for
all five mandatory cases; their credential-free evidence is
`/tmp/codira-phase0-escape-probes.json`. The first live cancellation attempt
reached `turn.started` and stopped after the runner's SIGINT, but Codex exited
gracefully with code 0 while the checker accepted only signal-style exits. The
checker now accepts that code only when the runner records the signal delivery;
focused checks passed again (31 tests). The approved corrected cancellation
retry completed on 2026-09-09: the runner delivered SIGINT, Codex exited with
code 1 in 0.045 seconds, and the JSONL stream contains `thread.started` and
`turn.started` with no terminal event. The credential-free diagnostic sidecar
is `/tmp/codira-phase0-cancel-events-retry3.jsonl.diagnostic.json`, and the
event evidence is `/tmp/codira-phase0-cancel-events-retry3.jsonl`. The runner
therefore records the cancellation as conformant. The sole unmet Phase 0
prerequisite is deciding whether the reviewed GHCR package remains
runner-authenticated/private or is intentionally made public. On 2026-09-09,
the operator approved retaining runner-authenticated/private visibility. Phase
0 conformance prerequisites are therefore complete; package pull credentials
remain solely with the trusted runner, never with the benchmark agent. The safe
bootstrap/preflight entry point is
`scripts/prepare_agent_efficiency_phase0_host.sh`; it performs host-changing
installation/image-pull actions only on explicit request and never receives
direct API-key environment variables.

- Pin Codex CLI, container runtime/image, authentication mode, and effective
  configuration. Verify JSONL events, usage completeness, cancellation,
  tool-output capture, and required MCP startup.
- Establish clean configuration/state, protected credentials, restricted network,
  hidden graders, memory isolation, and baseline tool exclusion.
- Test contamination and deliberate escape attempts with deterministic fixtures.
- Record limits that can actually be enforced; usage reported only at completion
  cannot by itself implement a hard mid-run token ceiling.

Gate: runner capabilities and isolation demonstrated; unsupported capabilities
fail closed or require a recorded decision. The operator's execution shell has
Podman 5.8.2 and Codex CLI 0.153.4; this agent's sandbox has a separate PATH.
The normal live probe, all five non-billed escape probes, and the corrected
live cancellation probe provide the required execution-host evidence.

## Phase 1 — Versioned contracts

Status: pending. Commit: pending. Evidence: pending.

Define fixture, task, campaign, per-run result, usage, and oracle schemas plus a
runner-neutral interface and offline adapter. Include fingerprints, provenance,
attempt identity, failure classes, accounting completeness, and budgets.

Gate: reject malformed inputs, moving revisions, incompatible versions, unsafe
paths, and contradictory budgets; public/private serialization tests pass.

## Phase 2 — Deterministic evaluation

Status: pending. Commit: pending. Evidence: pending.

Implement all DSL primitives, normalization, protected grading, and the custom
evaluator contract. Cover correct, missing, malformed, false-positive, and
tampered results. Include executable documentation examples and clean patch
application with independent tests.

Gate: independently reviewed oracles; reference successes pass and meaningful
negative/mutation cases fail. Record review findings and resolution.

## Phase 3 — Corpus admission and freeze

Status: pending. Commit: pending. Evidence: pending.

Verify license notices, exact trees, setup locks/image digests, language/size
inventory, six prompts, result contracts, and independently curated ground truth.
Establish parent-fail/source-fix-pass evidence for Click. Prevent source-fix
leakage through Git history, package copies, setup artifacts, or agent context.

Gate: all three fixtures reproduce and all six task oracles are validated.
Record any remaining setup dependencies before a measured run is allowed.

## Phase 4 — Paired harness and persistence

Status: pending. Commit: pending. Evidence: pending.

Implement isolated container runs, Codex JSONL adapter, MCP connection, randomized
pairing, cancellation, atomic checkpoints, resume, and usage normalization.
Record initial index preparation separately. Test incomplete streams, missing
usage, duplicate events, crashes between writes, retries, and configuration drift.

Gate: offline plus container integration tests demonstrate pairing, complete
accounting where supported, memory isolation, recovery, and evidence integrity.
Separate execution/accounting review completed.

## Phase 5 — Reporting and campaign readiness

Status: pending. Commit: pending. Evidence: pending.

Build reproducible JSON and Markdown reports with per-task success/failure,
paired token differences, median/p90, elapsed time, tool calls, and exclusions.
Retain traces needed to diagnose interaction friction. Exercise public redaction
using synthetic private data. Document prepare/run/resume/evaluate/report flows.

Gate: regenerate from stored records, reject incomparable inputs, pass focused
tests and `uv run python scripts/validate_repo.py`. Record reviewed implementation
SHA and create the campaign branch from that commit.

## Phase 6 — Bounded pilot and estimate

Status: pending. Commit: pending. Evidence: pending.

Proposed pilot: three independent pairs (six executions), covering discovery,
patch preparation, and documentation across all three fixtures. Pilot results
are separate from the final campaign.

Before launch, present a bounded pilot manifest for operator approval: candidate
benchmark model/effort, auth mode, run and wall-time limits, resource controls,
and spending/accounting limits that can actually be enforced. No blanket paid
execution is implied by approval of this ledger.

After the pilot, propose the full-campaign model, token/spend and wall-time
limits, retry allowance, and estimate with explicit uncertainty. Fix defects
through the implementation branch and assign a new experiment identity when
inputs change. Do not fabricate provider usage or silently substitute a model.

Gate: pilot evidence reviewed and full-campaign manifest/budget approved.

## Phase 7 — Full campaign and evidence validation

Status: pending. Commit: pending. Evidence: pending.

Execute the approved 60-run matrix on the campaign branch with frozen identities
and resumable records. Preserve failures and interrupted attempts. Generate
public sanitized reports and validate their provenance and exclusions.

Gate: every scheduled execution is accounted for, valid results reproducible,
review findings resolved, repository gate passes, and evidence commits recorded.
Phase 7 does not close the issue: Phase 8 is required.

## Phase 8 — Findings and product direction

Status: pending. Commit: pending. Evidence: pending.

Deliver both documents regardless of whether results favor Codira:

1. `docs/process/issue-053-audience-findings.md`: methodology, tested scenarios,
   results, limitations, and reproducible examples. When supported by evidence,
   include communication-ready claims for potential users, each traceable to
   a report/table. Negative or inconclusive outcomes must remain accurately stated.
2. `docs/process/issue-053-internal-product-assessment.md`: review successful
   and failed traces for confusing outputs, poor tool discovery, unnecessary
   calls, missing capabilities, stale-index friction, latency, and other rough
   spots. Distinguish product, agent, fixture, and harness causes. Rank proposed
   improvements by evidence, expected benefit, and verification method.

The internal assessment is not automatically public: use public-safe aggregate
evidence in tracked documentation; keep sensitive trace details in ignored
local evidence. Publication and creation of follow-up issues are separate actions.

Gate: claims independently reviewed against raw evidence and sample limitations;
both documents complete; follow-up recommendations and unresolved limitations
recorded. Report #53 ready for closure only after this phase and all required
validation are complete.

## Follow-up experiment — CLI assistance

Not part of the initial 60-run matrix. Propose a separate three-variant experiment:
ordinary tools, ordinary tools plus MCP, and ordinary tools plus Codira CLI.
Use the same model, tasks, revisions, budgets, fresh sessions, and randomized
order. If conditions changed, rerun all three variants together rather than
comparing incompatible historical results.

Evaluate practical improvement in success, tokens, and operational cost
separately from statistical significance. Favorable MCP results may motivate
the experiment; mixed results may also justify it when traces implicate interface
friction. Define the hypothesis, repetitions, budget, and decision criteria
before launching. Separate approval required for that campaign.

## Implementation model recommendation

Use GPT-5.6 Terra at medium reasoning for bounded implementation phases, with
GPT-6 Astra for independent contract/oracle, accounting, and final-evidence
reviews or unresolved methodological defects. This is a practical recommendation,
not a measured project-specific optimum. The benchmark model is a separate
experimental choice and must remain fixed within a comparison.

Official sources consulted during planning:

- <https://developers.openai.com/api/docs/models>
- <https://developers.openai.com/api/docs/models/gpt-5.6-terra>
- <https://learn.chatgpt.com/docs/non-interactive-mode>

## Decision and execution record

| Entry | State / evidence |
| --- | --- |
| Plan approval | Operator approved decisions and amendments in conversation, 2026-09-08. |
| Persistence | This ledger records the approved scope; implementation phases remain pending. |
| Implementation branch | `feat/issue-053-agent-efficiency-benchmark` |
| Campaign branch | Deferred until validated Phase 5 implementation SHA exists. |
| Pilot permission | Pending bounded execution manifest and resource approval. |
| Full campaign permission | Pending pilot estimate and resource approval. |
| Independent reviews | Pending phase-specific evidence. |
| Publication / merge / issue closure | Not performed by plan persistence. |
