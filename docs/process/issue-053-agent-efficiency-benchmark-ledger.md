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

Status: complete. Commit: atomic Phase 1 commit on the implementation branch.
Evidence: versioned Draft 2020-12
schemas for fixtures, tasks, campaigns, usage, run results, and oracles are
generated by `scripts/generate_agent_efficiency_schemas.py` and checked with
`--check`. The strict loader rejects malformed JSON, incompatible versions,
moving revisions, unsafe paths, and contradictory budgets. It records canonical
fingerprints and rejects private material from public serialization. A
runner-neutral protocol and deterministic offline adapter preserve attempt
identity, provenance, failure class, and complete zero-usage accounting. On
2026-09-09, focused ruff and mypy checks passed and
`tests/test_agent_efficiency_phase0.py tests/test_agent_efficiency_contracts.py`
passed (35 tests). The full repository gate completed in a detached execution
host session on 2026-09-09: 1,018 passed, 1 skipped, and 87% total coverage.

Define fixture, task, campaign, per-run result, usage, and oracle schemas plus a
runner-neutral interface and offline adapter. Include fingerprints, provenance,
attempt identity, failure classes, accounting completeness, and budgets.

Gate: reject malformed inputs, moving revisions, incompatible versions, unsafe
paths, and contradictory budgets; public/private serialization tests pass.

## Phase 2 — Deterministic evaluation

Status: complete. Commit: atomic Phase 2 commit on the implementation branch.

Evidence to date: the staged implementation supplies all declared DSL
primitives, result normalization, protected command and patch evaluation, and
explicit protected custom-evaluator bindings. The focused oracle suite covers
reference success plus missing, malformed, false-positive, tampered,
symlink-escape, patch-target-escape, failing-test, evaluator-false,
declaration/binding, and malformed-composition cases. On 2026-09-09 its focused
checks passed: Ruff format and lint, mypy, and `pytest -q
tests/test_agent_efficiency_oracles.py` (5 tests). Codira was refreshed and
`codira audit --json` returned `no_matches`.

Independent review record (Grok Build through OpenRouter, 2026-09-09): the
initial review returned `NEEDS_FIXES` for patch traversal, shell-path bypasses,
unbound custom evaluator identities, command validation after mutation, two
missing negative cases, and overstatement in the methodology. The remediation
validates all unified-diff, rename, and copy targets before `git apply`; rejects
shell executable paths and inline-command flags; validates test commands before
copy/apply; binds the protected registry callable to the reviewed script path
and SHA-256; adds the identified negative cases; and corrects the runbook. A
confirmation review returned `NEEDS_FIXES` for rename/copy targets, malformed
boolean children being validated after side effects, class docstring templates,
and additional negatives. Those findings are resolved in the staged patch and
focused tests. Its suggestion to prohibit all interpreter commands was not
accepted: protected tests necessarily invoke an interpreter in the protected
fixture; shell and inline-code execution remain rejected, and the oracle
definition is grader-controlled. The final independent confirmation on
2026-09-09 returned `VERDICT: PASS` after reviewing the complete staged patch.
Its provider-reported cost was USD 0.0159166. The required final repository
validation follows this ledger update before the atomic Phase 2 commit.

Implement all DSL primitives, normalization, protected grading, and the custom
evaluator contract. Cover correct, missing, malformed, false-positive, and
tampered results. Include executable documentation examples and clean patch
application with independent tests.

Gate: independently reviewed oracles; reference successes pass and meaningful
negative/mutation cases fail. Record review findings and resolution.

## Phase 3 — Corpus admission and freeze

Status: complete. Commit: atomic Phase 3 commit on the implementation branch.

Evidence to date: on 2026-09-09, SOPS-scoped GitHub queries verified the
registered MIT/BSD-3-Clause/MIT license metadata and all three immutable
revisions. Disposable exact checkouts reproduced the Codira tree
`e50955c20b6911ed991c3761de8b97fba19fe986`, Click tree
`2955d48825c98fd7dcbc60eb41cf18a952a2c0a3`, and Picomatch tree
`5a3f30720f18f01cd58bd8b9f1b71caaef9f231d`, including license and setup-file
SHA-256 records. The Click sentinel probe failed at the registered parent
`420c8fb44eeadb537cae69d2fee3796e808558dd` and passed at the protected source
fix `f58ca3e81424a35626c8a475eb59ab95589008ce`. Public fixture records and all
six task/oracle records are staged in the implementation worktree. Remaining:
anti-leak export verification, reference-oracle execution, focused tests, and
the final gate.

Completion evidence: a clean `git archive` export of Click contained its
admitted source while exposing neither `.git` metadata nor the protected
source-fix SHA. On 2026-09-09, all six registered reference artifacts passed
their Phase 2 deterministic oracles against disposable exact exports:
`architecture-001`, `documentation-001`, `impact-001`, `localize-001`,
`patch-001`, and `symbols-001`. The patch case used the actual protected diff
from the registered Click source fix and an independent sentinel probe. The
focused corpus/contract/oracle tests passed (11 tests). The final Codira audit
returned `no_matches`. The detached full repository gate completed on
2026-09-09 with 1,025 passed, 1 skipped, 87% total coverage, and exit code 0.

Verify license notices, exact trees, setup locks/image digests, language/size
inventory, six prompts, result contracts, and independently curated ground truth.
Establish parent-fail/source-fix-pass evidence for Click. Prevent source-fix
leakage through Git history, package copies, setup artifacts, or agent context.

Gate: all three fixtures reproduce and all six task oracles are validated.
Record any remaining setup dependencies before a measured run is allowed.

## Phase 4 — Paired harness and persistence

Status: complete. Commit: atomic Phase 4 commit on the implementation branch.
Evidence: the implementation branch now
has deterministic paired scheduling, immutable atomic result records, strict
resume/configuration-drift validation, provider-usage normalization, and a
network-disabled/read-only container JSONL adapter. Focused Phase 0/1/4 tests
(43 passed, 1 skipped), Ruff, and mypy passed on 2026-09-13. A credential-free Podman integration
test also passed against the reviewed digest-pinned Phase 0 image: a disposable
JSONL shim verified the real container adapter's mounts, no-network/read-only
constraints, output capture, and baseline result normalization. The shim is not
evidence of real Codex/MCP startup. After operator authorization on 2026-09-12,
a local-only Phase 4 image was built from the implementation checkout as
`localhost/codira-agent-efficiency-phase4@sha256:9f2c48be23e150c7d99807da87d9a504152acbecdf4e42a7951a84a518d5bf08`.
It pins Codex CLI 0.153.4 and the local Codira core version
`2.0.2.post1.dev49`; a credential-free network-disabled probe verified
`codex --version`, the `codira-mcp` entry point, and a direct MCP `initialize`
handshake. The build exposed and corrected Codira's missing runtime declaration
for `packaging`. The image is local only and unpublished. No comparative paid
campaign has started. On 2026-09-13, the repository gate completed cleanly
with 1,037 passed, 2 skipped, 87% total coverage, and exit code 0.
On 2026-09-13, the authorized local Phase 4 conformance turn used the
Unix-socket relay to reach the runner-side OpenRouter proxy while the Codex
container retained `--network=none`. It returned zero after 19.410 seconds,
used the required Codira MCP server, emitted ten JSONL events, and reported
complete usage (68,375 input, 56,215 cached input, 575 output, and 192
reasoning-output tokens). Codex 0.153.4 represented the requested artifact as
a completed `file_change` rather than `command_execution`; the evidence checker
now accepts that completed artifact event and revalidated the preserved stream
as successful. The runner-side proxy now binds a distinct immutable handler
configuration per server and exposes an owner-only Unix socket; the container
has no provider credential or direct network route. The independent Grok Build
review through the authorized OpenRouter route returned `VERDICT: PASS` on
2026-09-13 (provider-reported cost USD 0.0137676); its only note was the
expected compatible-UID requirement for the owner-only socket. This closes the
separate execution/accounting review requirement.

Implement isolated container runs, Codex JSONL adapter, MCP connection, randomized
pairing, cancellation, atomic checkpoints, resume, and usage normalization.
Record initial index preparation separately. Test incomplete streams, missing
usage, duplicate events, crashes between writes, retries, and configuration drift.

Gate: offline plus container integration tests demonstrate pairing, complete
accounting where supported, memory isolation, recovery, and evidence integrity.
Separate execution/accounting review completed.

## Phase 5 — Reporting and campaign readiness

Status: complete. Commit: atomic Phase 5 commit on the implementation branch.
Evidence: canonical report generation is
implemented with a versioned JSON document and Markdown derived only from that
JSON. It loads only validated immutable records, emits per-attempt summaries
with normalized usage, elapsed time, event counts, paired token differences,
median/p90 statistics, and explicit exclusions. Synthetic path- and token-like
failure data is redacted before public rendering. The dedicated report command
reconstructs the frozen campaign identity without executing an agent. Focused
reporting checks passed (6 tests), as did Ruff, mypy, and `codira audit` on
2026-09-13. Grok Build's independent OpenRouter review initially identified
Markdown omission of exclusions, unsafe assertions, missing evidence-metric
validation, incomplete-pair coverage, incomplete task examples, and defensive
top-level validation. Each finding was remediated; the fingerprinted final
confirmation returned `VERDICT: PASS` (provider-reported cost USD 0.0156366).
The full repository gate then completed with 1,043 passed, 2 skipped, 87% total
coverage, and exit code 0. The local campaign branch is created from this
validated Phase 5 commit only; no paid campaign execution is authorized.

Build reproducible JSON and Markdown reports with per-task success/failure,
paired token differences, median/p90, elapsed time, tool calls, and exclusions.
Retain traces needed to diagnose interaction friction. Exercise public redaction
using synthetic private data. Document prepare/run/resume/evaluate/report flows.

Gate: regenerate from stored records, reject incomparable inputs, pass focused
tests and `uv run python scripts/validate_repo.py`. Record reviewed implementation
SHA and create the campaign branch from that commit.

## Phase 6 — Bounded pilot and estimate

Status: complete. Commit: `2909726`; earlier steps `67c3f30` and `c3cd66a`.
Evidence: Phase 6 step 1 implements
`scripts/run_agent_efficiency_phase6_pilot.py`, a dry-run-only launcher. It
validates a public campaign-schema manifest, requires exactly three unique task
identities and one repetition, and emits the deterministic six-attempt schedule
without reading credentials, creating runtime state, or executing an agent.
`--execute` fails closed pending the separate pilot-manifest, budget, and
execution approval. Focused launcher tests, Ruff, mypy, and `codira audit`
passed on 2026-09-13. Independent Grok Build review returned `VERDICT: PASS`
on 2026-09-13 (OpenRouter-reported cost: USD 0.0077846); it identified no
required change. The full repository gate passed on 2026-09-13: 1,046 passed,
2 skipped, 87% coverage, and zero Semgrep findings.

Phase 6 step 2 adds the public, schema-validated
`benchmarks/agent-efficiency/phase6-pilot.json` approval manifest. It binds
the three selected public task identities to their three frozen fixture
fingerprints; fixes OpenRouter `openai/gpt-5.6-terra` at medium reasoning; and
records the approved USD 2 daily hard key limit, USD 1.80 pilot estimate,
12,000 output-token limit, 80,000 observed-total-token admission ceiling,
600-second attempt timeout, and existing container controls. The campaign
contract now validates task-to-fixture bindings. The provider proxy rejects
model/effort substitution and injects the approved OpenRouter output and price
ceilings. The launcher remains dry-run-only until live execution is separately
reviewed and gated. Focused tests, Ruff, mypy, `codira audit`, and the checked
in manifest dry run passed on 2026-09-13. Independent Grok Build review
returned `VERDICT: PASS` on 2026-09-13 (OpenRouter-reported cost: USD
0.0118504); it identified no required change. The full repository gate passed
on 2026-09-13: 1,050 passed, 2 skipped, 87% coverage, and zero Semgrep
findings. The operator confirmed that the dedicated
`codira-agent-efficiency-pilot` key has the required USD 2 daily cap.

Phase 6 step 3 implements the explicit, resumable paid-pilot runner in
`scripts/run_agent_efficiency_phase6_pilot.py`. It validates all frozen public
task and fixture bindings before reading the dedicated pilot credential;
requires explicit local source bindings; exports each agent-visible fixture at
its admitted Git revision; and makes a separate detached protected checkout for
grading. The patch task's protected Sentinel probe is a benchmark-owned,
SHA-256-verified asset derived from Click upstream commit
`f58ca3e81424a35626c8a475eb59ab95589008ce`; it is copied only into the grader
checkout. A fresh per-attempt Unix-socket proxy now enforces the fixed Terra
medium model, OpenRouter price caps, output cap, and one Responses request
before upstream forwarding. The runner preserves immutable `CampaignStore`
records, fails closed on unfinished attempt work and malformed controls, and
turns protected-oracle contract failures into terminal `oracle_failure`
records. The test-review SOPS registry now authorizes the narrowly scoped
`scripts/run_agent_efficiency_phase6_review.py` helper. Grok Build through
OpenRouter reviewed the implementation iteratively: two `NEEDS_FIXES` reviews
identified assertion, path-safety, failure-normalization, and coverage gaps;
all were remediated. The final confirmation returned `VERDICT: PASS` on
2026-09-14 (provider-reported USD 0.0535486; all three review calls totalled
USD 0.1240278). Focused checks reached 62 passed, 1 skipped; the final full
repository gate passed on 2026-09-14 with 1,058 passed, 2 skipped, 87% total
coverage, and zero Semgrep findings.

Pilot 001 was then launched from the immutable local state root. All six
attempts became `infrastructure_failure` records with return code 127 and an
empty JSONL transcript; every record reports zero Responses requests and zero
usage tokens. The originally selected base image,
`ghcr.io/marco0560/codira-agent-benchmark@sha256:3647440cc3b727288bde32e5d651781f4869064c15c64f553474ca25d0aa00eb`,
does not contain `codex`, as verified offline. Thus Pilot 001 made no provider
request and incurred no pilot-provider charge; it is not evidence about either
assistance mode. Its records and original manifest remain unchanged. The
corrective Pilot 002 has a new campaign identity and binds the verified Phase 4
runtime image
`localhost/codira-phase6-pilot@sha256:c261d4ef446e73ccaec07ba8b592b2e80b26a7035a83d1cc5c3541718e2e1d24`.
The runner now requires an exact manifest runtime image for paid execution and
rejects a command-line image mismatch before preparing inputs or reading the
credential. Pilot 002 was pending at this checkpoint.

Pilot 002 subsequently completed its six scheduled records, each with exactly
one forwarded Responses request, but all became `infrastructure_failure` with
`turn.failed` reporting the proxy's 429 request ceiling. The historical raw
records report no completed-turn usage, so no provider cost or benchmark result
is inferred from them. The one-request control is incompatible with Codex's
multi-request agent loop. Under operator authorization, Pilot 003 is a new
identity with the same frozen tasks, fixtures, model, image, USD 2 daily key
cap, USD 1.80 pilot estimate, and 600-second timeout; it permits at most eight
Responses requests of 1,500 output tokens each per attempt. That preserves a
12,000-token generated-output envelope while allowing bounded tool-loop
continuations. Pilot 003 was stopped after its first baseline record: the
agent completed with six Responses requests and complete usage evidence, but
the baseline configuration incorrectly exposed Codira MCP. The record is
non-comparable and no further Pilot 003 record was written. The runner now
creates a no-MCP baseline configuration, covered by a regression test. Pilot
004 is a new identity with the same controls and frozen public inputs, bound to
the corrected verified runtime image
`localhost/codira-phase6-pilot@sha256:9dc2d751d504430174ca9d03cf85cdce42b223128b5ac744587dbf2b63480dc5`.
Pilot 004 completed all six records with complete usage evidence, but every
attempt reported that the nested Codex workspace sandbox could not create or
inspect files inside the already-confined container. The outer Podman boundary
already enforces no network, read-only root, dropped capabilities,
no-new-privileges, and explicit writable mounts. The runner therefore invokes
the supported Codex `danger-full-access` inner mode only within that outer
boundary; a regression test locks the command vector. Pilot 005 is the new
identity for this runner-input change, with the same verified image and frozen
public inputs. It has not yet been executed.

Pilot 005 likewise completed six immutable `infrastructure_failure` records:
each exhausted its eight-request ceiling before a terminal turn. One baseline
trace had already written the required result artifact before needing its ninth
continuation, proving the remaining fault is the request bound rather than the
outer sandbox. Under operator authorization, Pilot 006 is the replacement
identity. It permits 12 Responses requests at 1,000 output tokens each, keeping
the same 12,000-token generated-output envelope while allowing the observed
agent loop to complete. The dedicated key now has a USD 4 daily cap; the
operator reported USD 2.9496 remaining before Pilot 006. Pilot 006 was stopped
after two records when its transcript revealed that the runner image lacked
`uv`; the baseline had written the required artifact before its verification
command failed. Those records are invalid and no benchmark cost or outcome is
inferred from their incomplete terminal usage. Pilot 011 is a fresh identity
bound to `localhost/codira-phase6-pilot@sha256:c63266df197bcccdba2020be8e38327a240ae88a85d8ebca463a946a06a09d34`.
Its image provides `uv`, uses its preinstalled Python 3.13 without sync or
managed-Python downloads, and was verified to run the observed `uv run python`
command under the production no-network/read-only controls. It preserves the
authorized 12-request, 1,000-output-token, USD 4 daily, and USD 1.80 pilot
ceilings. Pilot 011 was stopped after its first pair: the baseline exhausted
12 requests without a terminal turn after its recorded verification command
found `jq` unavailable, while the assisted attempt reached a terminal
deterministic-oracle failure after 11 requests. The pair is invalid and is not
used as a comparison. Pilot 013 is a fresh identity bound to
`localhost/codira-phase6-pilot@sha256:e7ded5da0e93f4d5372963165d545b779afe717879cca938125067d82099194e`.
Its image includes `git`, `jq`, and `ripgrep` in addition to Codira, Codira
MCP, Codex, and uv. A disposable-fixture preflight verified every command
observed in the Pilot 011 transcripts, including the `uv run`, Git, jq,
Codira CLI, and Codira MCP compound paths, under the production no-network and
read-only controls. Pilot 013 retains the same authorized ceilings.
Pilot 013 was stopped after its first pair when complete terminal usage showed
that the USD 0.30 per-attempt estimate was too low: the baseline recorded
232,080 input and 1,830 output tokens, and the assisted attempt 210,749 input
and 1,837 output tokens. At the manifest's conservative maximum prompt and
completion rates, those two attempts can total up to USD 0.97. Both are
deterministic-oracle failures, not runner failures, and their pair is retained
as immutable evidence but not used to draw comparative conclusions. No further
attempt is authorized until the estimate and available key budget are revised
explicitly. The operator raised the pilot key's daily cap to USD 6. Pilot 014
is the resulting fresh identity, with the same frozen inputs and verified image
but a USD 0.50 per-attempt estimate and USD 3.00 pilot ceiling.
Pilot 014 then confirmed a separate fixture-contract defect: its synthetic
archive export had no Git worktree, so a normal `git diff --check` verification
failed and the assisted attempt exhausted its 12-request ceiling. The exporter
now initializes an empty, history-free, remote-free Git repository after
extracting the frozen tree; its contract test verifies no source commit is
exposed while normal Git verification works. The operator raised the daily cap
to USD 10. Pilot 015 is the new identity for that fixture change, allowing 24
requests of 500 output tokens each (the same 12,000 output-token envelope),
with conservative USD 1.00 per-attempt and USD 6.00 pilot ceilings.
Pilot 015 showed that even 24 requests cannot compensate for the agent's
post-artifact verification loop. With operator approval, all three pilot tasks
now instruct the agent to stop immediately after writing the required artifact.
Their fingerprints changed; the oracles and frozen fixtures did not. Pilot 016
is the fresh identity for that treatment change, retaining Pilot 015's resource
and USD 10 daily controls.

Pilot 016 identified that an assisted documentation execution could complete
without invoking MCP, so its record was retained as invalid evidence. The
runner now binds a versioned treatment instruction from each paid manifest and
requires one Codira MCP call only for the assisted variant. Pilot 017 exposed a
timeout-cleanup defect: the outer Podman client was cancelled but the container
could survive. Each attempt now supplies a host-visible CID file and, after a
timeout, force-removes only the validated CID. Pilot 018 is the fresh identity
for those runner inputs. Its six immutable records all have complete usage and
its deterministic report has zero exclusions. Every attempt nevertheless
failed its deterministic oracle; the paired Codira MCP token increases were
64,658 (symbols), 146,978 (documentation), and 144,781 (patch). The pilot
therefore provides no provider-token evidence for a successful outcome and
does not support a 60-run campaign. On 2026-09-14 the operator explicitly
approved closure as an inconclusive, non-advancing Phase 6 result. This is an
explicit waiver of this phase's normal full-campaign-manifest/budget gate;
Phase 7 remains pending and no full campaign is authorized.

### Restart checkpoint and lessons learned

Restart from implementation commit `2909726`. Phase 6 is closed as
inconclusive; Phase 7 is not authorized. Before any renewed benchmark work,
redesign and validate the task/oracle methodology so that a successful outcome
is measurable.

1. Preserve immutable records before cleanup, then enumerate benchmark tmux
   sessions and runtime processes. Stop only the exact stale session or
   CID-bound container; remove stale tmux sessions and disposable `/tmp`
   state only after its records have been retained.
2. Before a paid run, derive the executable inventory from prior transcripts
   and verify every direct and compound command in the hardened runtime. This
   includes Codex, Codira, Codira MCP, uv, Git, jq, ripgrep, and the observed
   workflow commands—not merely that the image builds.
3. Examine every terminal record and the deterministic paired report before
   changing limits or launching a replacement: confirm usage completeness,
   response count, MCP evidence, oracle result, exclusions, and the concrete
   cause of any failure. Do not raise request, token, timeout, or spend limits
   to mask a missing program, containment defect, post-artifact loop, or
   invalid task. Any changed task, runtime, runner, or control requires a new
   experiment identity.
4. Treat complete provider usage as an admission requirement for a comparative
   pair. A timeout, incomplete usage, malformed transcript, absent MCP event,
   or baseline MCP exposure is retained as evidence but is not a result from
   which a token comparison or cost conclusion may be drawn.
5. Keep each paid manifest bound to canonical task and fixture fingerprints,
   the digest-pinned image, and the exact treatment protocol. Validate all of
   those bindings before reading the provider credential; a raw file hash is
   not interchangeable with the contract's canonical JSON fingerprint.
6. Budget from observed usage, not only the nominal output cap. Reconcile the
   remaining daily-key balance before a replacement run, keep a conservative
   per-attempt and whole-pilot ceiling, and prevent concurrent or orphaned
   attempts from consuming the same budget.
7. Preserve fixture privacy without breaking ordinary agent workflows: an
   exported fixture may be a history-free, remote-free Git worktree so that
   `git diff --check` works, while source commits, remotes, and protected
   oracle assets remain unavailable to the agent.
8. A public report is useful only if it is durable and reproducible. Retain
   immutable raw records outside Git as required, but commit or otherwise
   preserve a public-safe report reference and its configuration fingerprint
   rather than relying on a transient `/tmp` path for a future restart.

### Paid reviewer evaluation guardrails (2026-09-16)

The first DeepSeek/Grok evaluator attempt reached the provider-request stage
without a durable per-attempt record and then ended after the request timeout
with no raw response. Its provider-side completion and billing status are
therefore unknown. It is not evaluator evidence and must not be retried or
used to support a model-selection conclusion.

1. Before any paid request, atomically persist an attempt state containing the
   immutable diff hash, exact model ID, repetition, output and timeout
   controls, budget identity, and artifact root. Mark it complete only after a
   verified full response and provider usage have been durably recorded.
2. An existing `in_progress` or `failed` attempt state blocks automatic retry
   and resume. Resolve the provider-side accounting uncertainty and obtain a
   new experiment identity and approval before a replacement request.
3. Run a credential-free contract and cost preflight before invoking SOPS.
   It must verify the exact model IDs, no-fallback routing, output-limit
   support, and worst-case published pricing using frozen prompt sizes and the
   output cap. The 2026-09-16 preflight estimated USD 0.9633854 for 24
   requests; that estimate is not evidence of a completed trial.
4. Admit a review only when the returned model exactly matches the request,
   the finish reason is `stop`, the verdict has the required format, and usage
   is complete. Keep raw response bodies outside Git; retain only safe
   summaries, timing, model/provider identity, usage, and response hashes in
   reproducibility records.
5. Supervise long provider calls with durable, monitorable state rather than
   relying on a foreground tool timeout. If a process ends without a completed
   state, treat the preceding request as unknown; do not issue a duplicate.
6. Scope the OpenRouter test credential solely to the secret-registry-approved
   helper command. A new executable command requires registry review and an
   explicit authorization; do not broaden the SOPS command as a workaround.

### Reviewer evaluation `r2` terminal record (2026-09-16)

The explicitly authorized `phase6-deepseek-v4-1-flash-r2-20260916` run passed
its credential-free contract preflight and then verified a USD 3.00 scoped-key
limit with USD 2.8660008 remaining against its USD 1.6071094 conservative
estimate. It atomically persisted its first attempt state before contacting the
provider. The first `x-ai/grok-build-0.1` request then failed the local
response-admission boundary; no raw response, complete usage, or admitted
review record exists. The state is terminal `failed` with zero completed
attempts. Treat it as non-comparative evidence with unknown provider-side
billing; do not resume or retry `r2`.

### Reviewer evaluation `r3` terminal record (2026-09-17)

The explicitly authorized `phase6-deepseek-v4-1-flash-r3-20260917` run used
the provider-metadata correction, atomically recorded its first attempt, and
then failed closed before admitting a review, raw response, or usage record. A
subsequent non-billing scoped-key metadata check reported the same USD 3.00
limit, USD 3.00 remaining, and USD 0.00 daily usage as the pre-request check.
`r3` therefore has zero observed provider usage and is not comparative
evidence. Its terminal state blocks resume; a replacement requires a new
identity and explicit authorization. Future terminal state stores a safe HTTP
status for transport failures, never the provider error body.

### Reviewer evaluation `r4` diagnostic terminal record (2026-09-17)

After a fresh passing repository gate, the authorized distinct
`phase6-deepseek-v4-1-flash-r4-diagnostic-20260917` identity atomically
recorded one attempt for the first frozen known-defect case and
`x-ai/grok-build-0.1`. That single request terminated with safe failure
category `HTTP 400`; no raw response, usage record, or admitted review exists.
The permitted non-billing scoped-key metadata check afterwards still reported
a USD 3.00 limit, USD 3.00 remaining, and USD 0.00 daily usage. `r4` therefore
has zero observed provider usage, is terminal, and cannot be resumed. It is not
a DeepSeek request and cannot support a replacement conclusion. No retry or
additional diagnostic may occur without a new identity and approval.

The follow-up authenticated `/models/user` check isolated the cause without a
completion request: this scoped key makes `x-ai/grok-build-0.1` available but
marks its reasoning as mandatory. The new evaluator had added
`reasoning.enabled: false`, unlike the successful Phase 6 helper, so that
incompatible request field explains `r4`'s HTTP 400. The repair omits an
explicit reasoning setting (preserving each key-visible model default) and
requires the authenticated catalog before every future completion. Public
`/models` remains useful for price and aggregate capabilities, but cannot prove
key-specific admission.

### Reviewer evaluation `r5` comparative-trial authorization (2026-09-17)

The operator authorized the fresh
`phase6-deepseek-v4-1-flash-r5-20260917` comparative trial after the reasoning
contract repair. It must use the frozen six-case corpus, two exact models, two
repetitions, 24-request maximum, USD 2.00 conservative ceiling, authenticated
model admission, and a new ignored artifact root. Run a current public contract
and cost preflight plus a fresh repository gate before SOPS. Stop at the first
unverified or incomplete result; no retry or resume is implied.

### Reviewer evaluation `r5` terminal record (2026-09-17)

The fresh preflight and repository gate passed, then the first Grok control
request (`baseline-mcp-defect`, repeat 1) stopped with `independent review
verdict is malformed`. It recorded zero completed attempts and therefore has no
comparative, coverage, cost, or replacement evidence. The pre-existing helper
did not retain a response body when its verdict parser rejected it, so this
record cannot distinguish a prose prefix, Markdown wrapper, or another response
layout. The response-evidence omission is logged as a runner defect, not a
model-quality result. The repaired helper atomically persists every received
provider body in the ignored per-attempt artifact before validation, with only
the artifact path and SHA-256 in terminal state. A future paid request must use
a new experiment identity and separate explicit authorization.

The active successor control is
[`phase6-paid-review-gold-standard-protocol.md`](phase6-paid-review-gold-standard-protocol.md).
It separates offline qualification, live-route calibration, and paired
evaluation; no stage authorizes the next one implicitly.

### Reviewer evaluation `r6` terminal record (2026-09-18)

The r6 strict-schema calibration admitted both exact models, but did not
represent the long frozen diff. The paired run completed two Grok attempts and
then stopped on DeepSeek's first attempt: its response had `finish_reason`
`length` and null content after consuming the output allowance in reasoning.
The preserved artifact establishes an incomplete result, not a schema failure.
It also showed Grok reporting completion usage above the requested cap, so the
runner now rejects over-cap provider usage and classifies length termination
before content parsing. Future calibration must use the representative frozen
diff and exact paired controls. `r6` has no comparative conclusion.

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
