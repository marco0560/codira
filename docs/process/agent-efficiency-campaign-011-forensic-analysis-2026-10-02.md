# Campaign 011 forensic analysis and preparation requirements — 2026-10-02

This audit supersedes the efficacy and correctness interpretation in the
[initial results report](agent-efficiency-campaign-011-results-2026-10-02.md).
It reads the frozen records, complete event streams, protected traces, source
fixtures and runner implementation. No model turn was started and no original
campaign record was changed. Additional offline checks are explicitly
retrospective, rather than replacements for frozen results.

## Results and comparison

All 48 scheduled attempts finished and have immutable records and complete
usage. The final runner status is `complete`; this describes schedule completion,
not correctness. The runner recorded 44 operational passes, four post-turn token
classification failures, ten grading failures and 34 answers requiring semantic
review. None of the four operational failures was a provider quota rejection.

| Measurement | Baseline, 24 attempts | MCP-configured, 24 attempts |
| --- | ---: | ---: |
| Operational passes | 21 | 23 |
| Post-turn token-ceiling failures | 3 | 1 |
| Frozen grading failures | 5 | 5 |
| Frozen semantic review pending | 16 | 18 |
| Input + output tokens | 10,873,076 | 8,419,785 |
| Cached input tokens, already included above | 9,806,848 | 7,547,648 |
| Uncached input tokens | 952,569 | 763,189 |
| Native container execution, summed seconds | 3,033.00 | 3,070.16 |
| Index preparation, summed seconds | 0 | 3,207.31 |
| Export + environment + grading, summed seconds | 258.89 | 295.42 |
| All measured attempt phases, summed seconds | 3,291.89 | 6,572.89 |
| Attempted / successful MCP calls | 0 / 0 | 15 / 0 |

The MCP-configured arm used 2,453,291 fewer reported tokens, a 22.56% reduction.
Uncached input fell 19.88%. Its native turns took 1.23% longer; adding recorded
preparation and grading phases makes its measured attempt duration about twice
baseline. These sums exclude inter-attempt admission, checkpoints and operator
recovery, and are not campaign wall time. Cached tokens are repeated model input,
not additional uncached tokens or a dollar/quota conversion.

**There is no successful MCP exposure in this campaign.** All 15 calls, across
seven assisted attempts (E1, E2, E3, F1, I1, I2, T2), failed with
`MCP tool call requires approval, but approval policy is never`. The remaining
17 assisted attempts made no MCP call. Both arms had Codira CLI access by design;
some assisted attempts fell back to it or source inspection. Consequently these
numbers compare the realized configurations, including failed tool access and
preindexing, and cannot establish an MCP treatment benefit.

The all-pair mean token difference is -102,220, median -2,619, with the existing
task-bootstrap 95% interval [-333,970, 60,081]. The interval crosses zero. E3 alone
accounts for 2,223,086 tokens, 90.62% of the aggregate reduction. Removing that
pair as a sensitivity check leaves a 230,205-token reduction (2.89% of the
remaining baseline total). This exclusion is diagnostic, not a new primary
analysis. One repetition per task cannot resolve model variability. The earlier
16-pair subset excluded grader failures as well as cap classifications and must
not be described as a correctness-matched efficacy comparison.

Start snapshots showed the Codex quota bucket at 79–82% used, with no exhaustion
flag. They are dated observations, not an attributable campaign quota debit:
provider windows and other account activity are not controlled here. Recorded
usage totals 19,292,861 tokens. Subscription dollar accounting is not applicable.

## Failure diagnosis

### MCP permissions: the treatment was advertised but unusable

The preserved assisted configuration registers the Codira MCP server, requires
startup, trusts `/workspace`, and sets `approval_policy="never"`. Native tool
execution nevertheless asks for approval for every observed MCP call and rejects
it. Server registration, discovery, direct MCP qualification and index readiness
did not prove that the native agent could execute the tool under its actual
permissions profile. The event streams prove the dispatch failure; this audit
does not assert an untested configuration key will repair it.

The qualifier must exercise the actual native client's tool authorization and
successful dispatch with the campaign configuration. Test the exact permission
setting offline through the native protocol when possible. If that does not
exercise model-triggered dispatch, a separately identified, explicitly authorized
minimal canary is needed; a no-turn account/model preflight cannot substitute.
Do not solve this by exposing credentials or disabling the task sandbox.

Optional tool use permits an agent to choose source inspection. It must not
permit an unavailable configured tool to pass treatment qualification. A systemic
authorization failure should stop new attempts before consuming the full panel.

### Eight oracle-contract failures: a composite grader defect

All six patch tasks declare `result_format="workspace-diff"`. In
`scripts/agent_efficiency/oracles.py`, `_result_artifact` verifies the patch exists
and returns `None` for that format. Their complete oracle is an `all_of` combining
protected patch behavior with `quality_rubric`. `_quality_check` requires text,
so it raises `ContractError: quality_rubric requires a rubric object and text
artifact`. Composite evaluation eagerly evaluates every child; that exception
also masks a preceding behavioral failure and discards accumulated public
subcheck results.

A credential-free direct reproduction of the real artifact loader and quality
branch produced that exact exception. Frozen traces show:

| Task | Baseline protected command | MCP-configured protected command | Frozen terminal classification |
| --- | --- | --- | --- |
| F2: optional plugin capabilities | exit 0 | exit 0 | oracle_contract, both |
| F3: suffix forwarding | exit 0 | exit 1 | oracle_contract, both |
| P1: sentinel pickling | exit 0 | exit 0 | oracle_contract, both |
| P3: zero means unlimited | exit 0 | exit 0 | oracle_contract, both |

Every patch in this table passed `git apply --check` and application. Seven
passed their protected behavioral command. Those are bounded behavioral results,
not full correctness passes; semantic coverage was never evaluated successfully.
Calling all eight incorrect patches in the initial report was wrong.

F3 assisted has a genuine behavioral defect in addition to the grader bug:
`transform` returns immediately when `enabled === false`, before appending the
suffix. The protected probe observed `abc` where `abcend` was required. Added
agent tests checked default/lowercase suffix behavior but missed the disabled
implementation path. The public wrapper still has its seeded false-defaulting
behavior, which further hides this path in public-only examples.

The 18 patch calibrations did not exercise the complete oracle: the calibration
helper selects `definition['all_of'][0]` and evaluates only patch behavior. The
72 rubric probes separately adjudicate curated text. Neither qualification
crossed the real workspace-diff/composite-quality boundary. Successful component
calibrations therefore did not establish campaign grading qualification.

### P2: capture rejected installed dependency symlinks

Both P2 attempts finished and wrote their own patch, but the runner failed before
protected grading. `capture_workspace_patch` traverses the workspace, excludes
Python environments/caches and runner metadata, but does not exclude
`node_modules`. It rejects symlinks anywhere in its included tree.

Each preserved agent tree has 23 symlinks under `node_modules/.bin`. The
pre-turn snapshot contains no symlinks because `shutil.copytree` dereferences them
by default. Capture thus compares incompatible representations of prepared
dependencies and rejects a normal offline environment. Direct read-only capture
replays reproduced `workspace patch capture rejects symlinks` in both arms.
The transcript does not show an agent dependency-install command causing this;
the dependencies were prepared by the runner.

This is a capture defect, not evidence that the ignore repair was wrong.
Calibration generated patches through Git instead of campaign snapshot capture,
so it could not detect this boundary failure. Capture should operate on the
admitted source/test inventory and explicit allowed additions, ignore prepared
dependencies consistently, and retain precise failure class/stage in evidence.
Source-path escapes, unexpected source symlinks and binary changes should still
be rejected; a blanket acceptance of symlinks would weaken the wrong control.

### Four token-ceiling classifications: complete turns, not interruptions

| Attempt | Reported total | Commands / nonzero exits | First file-change event | Native duration |
| --- | ---: | ---: | ---: | ---: |
| F1 baseline | 1,717,792 | 30 / 5 | 42 | 302.69 s |
| F1 assisted | 1,074,856 | 26 / 7 | 42 | 241.96 s |
| I2 baseline | 1,138,788 | 47 / 6 | 80 | 279.61 s |
| E3 baseline | 2,921,387 | 52 / 12 | 88 | 441.53 s |

All four reached native return code 0, recorded full usage and produced their
requested output artifact. The native route checks the token ceiling after the
turn. It neither interrupted these turns at one million tokens nor graded their
outputs afterward. The ceiling therefore currently acts as a terminal
classification/checkpoint rule, not an effective live runaway stop.

F1 produced code and regression tests in both arms. The assisted attempt also
encountered two denied MCP calls, denied uv-cache/global configuration paths,
a read-only Git index and a missing output directory, and worked around them.
The baseline patch changed more files, including core paging-related code and
tests, despite the fixture retaining core paging; assess that scope against the
protected task rather than presuming the larger trajectory was necessary.
I2 did broad contract/caller/test inspection and wrote a substantial assessment;
initial Codira commands hit denied configuration and unavailable ONNX artifacts.
These are progressing trajectories, not evidence of simple endless loops.

E3 baseline spent many commands repairing its execution environment: denied
user configuration, absent repository config, unavailable default embedding
plugin, unconfigured ONNX model, then inconsistent query/index configuration.
It eventually used disabled embeddings with placeholder model paths, performed
index/cursor experiments and wrote an answer. Its very high cumulative input is
substantially confounded by runner/environment recovery. Raising the ceiling
would relabel the completed turn but would not repair that cause.

Nonzero command counts also include expected argparse rejection tests, stale
cursor rejection, failed search matches, and `git diff --no-index` returning 1
when differences exist. They are not all infrastructure or model errors.

The operator's intended policy is a generous runaway safeguard. A future native
runner should separate soft usage warning/classification from live cancellation,
retain available output grading as a separate axis, and use wall time plus
observed lack of progress to stop actual runaway behavior. Any new thresholds or
stop semantics require a fresh qualified campaign; 011 remains frozen.

### Semantic review: the earlier 32/34 pass rate is unsupported

The original review packets used opaque IDs, but the preserved adjudication
script sets every criterion to `supported` except grounding for two hard-coded
packet IDs. It uses generic reasons and heuristically selected answer quotes.
The receipt validator checks digests, decisions and quote membership; it cannot
verify that a quoted claim is true. This is not a defensible source-grounded
semantic adjudication, even though the receipt format is valid.

Source and event spot checks expose concrete missed problems:

- I1 baseline says the warm-proxy parity test includes `symbol_evidence`.
  The frozen test's call map omits it. I1 assisted correctly identifies that gap.
- E3 assisted was asked to edit `transform`; its preserved `impl.ts` remains
  unchanged while it fixes `wrapper.ts` and adds a disabled-format regression.
  Cursor-generation observations are useful, but they do not cover the requested
  implementation edit. The answer was incorrectly accepted for full coverage.
- N3 assisted changes `wrapper.ts` to pass options unchanged during a navigation
  task and describes the resulting behavior. It identifies the alias chain, but
  part of the answer concerns its modified fixture rather than the frozen
  behavior. The earlier review did not identify this deviation.
- Both N2 answers lack the source-location/reproducible-check grounding required
  by the rubric; the original review did notice this narrower issue.

These checks are an unblinded forensic audit, not replacement blinded scores.
Withdraw the aggregate 32/34 semantic pass claim. Preserve its packets and
receipts for audit, and rerate all applicable outputs using frozen source,
execution observations, explicit criterion reasons and treatment-blind review.
No final task-success percentage or correctness-matched efficacy estimate is
supported until that work is completed.

## Conversation and runner-preparation failures

The recurring errors cross different execution boundaries and require different
checks. Treating all of them as container problems leads to ineffective fixes.

| Failure | Boundary and cause | Required prevention |
| --- | --- | --- |
| Podman mkdir/sticky-bit error | Host rootless Podman cannot write `/run/user/1000/libpod` from the outer agent sandbox; before any task container/model turn | Qualify Podman from the actual authorized host execution context once; route runtime operations there consistently |
| tmux socket operation denied | Outer sandbox cannot access the host tmux server | Validate tmux access in the same host context as launch and full gate |
| Frozen source mismatch | Prepared image uses `0ee458`; active checkout serves newer `d4ec49`; session did not receive the frozen source binding | Pin interpreter/product artifact and verify imports in generated tmux child before authenticated execution |
| Python `types` import crash | Manual PYTHONPATH pointed to the `codira` package directory, shadowing stdlib `types.py` | Bind an isolated package environment/archive parent through a receipt; test `import types` and source fingerprint in child; avoid tmux-global environment mutation |
| Relative fixture binding / wrong client path | Manually re-entered already prepared paths | Resolve/check paths once, load exact bindings from immutable local receipt; verify client digest, not just version |
| Native HOME denied | Tools inherit HOME under credential-denied `/codex-state`, causing bash startup, Git config, uv and Codira config errors | Separate client credential state from writable tool home/config/cache; exercise real tool commands under actual sandbox |
| CLI profile / model / index mismatch | Fallback CLI doesn't consistently receive the qualified profile, model assets and index/output-root conventions | Bake wrapper/profile/assets and use the same qualified CLI contract in both arms |
| MCP approval denial | Server exposed but native agent dispatch not qualified | Verify successful native MCP execution; count denied/successful calls, not merely attempted calls |
| Patch capture / composite grade | Calibrations bypassed campaign boundaries | Replay full export→prepare→snapshot→edits→capture→complete oracle→record/report path for every task family |
| Weak semantic adjudication | Quote-valid receipts accepted unsupported assertions | Source-grounded reviews; quote/digest validity is only evidence integrity |

The first five are pre-turn failures: they cost operator time, but their traces
do not establish model/quota consumption. Tool-home, CLI and MCP failures occur
inside model trajectories and cause additional commands and cumulative input.
The initial full gate did not prevent these because the end-to-end boundaries
were not covered. Repeating the entire gate after merely recording its success
adds delay without testing a new failure condition.

## Refinement of the preparation checklist

The factory already separates specification, generation, qualification,
preflight and paid launch. Retain those stages and strengthen their contracts.
The desired outcome is one deterministic assembly pass over qualified components,
with failures reported before model execution. It cannot promise zero mistakes;
it can eliminate hand-entered launch state and require proof at each boundary.
These are requirements for the next runner revision, not a claim that those
features are implemented today.

Use a versioned reusable runtime recipe for Podman isolation, native credentials
and tunnel, tool home/cache, offline ecosystems, CLI/MCP bindings, source snapshot
capture, protected grading and evidence/checkpoint handling. Resolve new campaign
inputs through the factory: exact product checkout/package, tasks/fixtures/tests,
model/effort/provider, repetitions/seed and guardrails. A model change should not
rebuild a qualified dependency image unless runtime requirements change.

The intake should summarize all resolved parameters and their provenance. Ask
only for genuinely missing experiment choices: route/account, model/effort,
task selection/repetitions, stop policy or material environment changes. Derive
fixture paths, image/client/source digests, schedule, execution root and commands
from admitted artifacts. Campaign 011 already specified its material inputs;
asking the operator to repeat them would not prevent these failures.

Require the following evidence before generating a new campaign:

1. **Host boundary:** runtime and tmux probes pass in the actual launch context;
   scratch path/socket lengths and required writable host runtime directories are
   checked. Preserve the execution-context requirement; do not retry a known
   forbidden sandbox operation as though it might succeed.
2. **Component identities:** isolated host product interpreter/package and image
   product match; source/profile/client/harness/task/fixture/oracle digests are
   pinned. Smoke-test imports and stdlib resolution in the generated child.
   Qualification receipts include commands/configuration actually exercised.
3. **Tool contract:** credential-read and network denial still pass; writable
   tool home/cache and exact ordinary shell, Git, uv, CLI and test commands pass.
   Prove usable native MCP dispatch separately from tool listing or direct MCP.
   A tool-choice protocol must distinguish non-use from denial/unavailability.
4. **Task pipeline:** replay correct, incomplete and wrong cases through campaign
   export, environment preparation, snapshot/capture, complete composite oracle,
   serialization and report. Include npm symlinks, new tests, read-only synthetic
   Git, text versus diff rubric inputs, and partial failure trace preservation.
   Component-only calibration cannot satisfy this gate.
5. **Ready receipt:** persist a resolved local binding receipt and generated launch
   environment; no manually reconstructed path list or tmux-global PYTHONPATH.
   Reject stale receipts when any binding/configuration/harness identity changes.
   Existing campaign artifacts remain immutable.
6. **Repository and authenticated gates:** run one full gate for the coherent
   revision with durable log/exit status, then repeat account/model/effort/quota
   admission through the exact isolated route. Subscription receipts use quota
   units; request/output planning values must not imply enforcement.
7. **Execution and closure:** launch only through the official launcher with
   campaign authorization. Retain complete events, diagnostics and distinct
   scheduled/model-terminal/usage/behavior/semantic statuses. Monitor systemic
   tool/grade failures and progress; investigate unmatched starts before resume.
   Stop-policy semantics are frozen campaign inputs. Keep completed sessions and
   durable terminal evidence; do not confuse exit 0 checkpoint with completion.

Correctness of the future assembly process should be demonstrated by these
replays rather than another long checklist completed manually. Keep one
parameter record, one generator, one qualification receipt and one launcher.
Changed component recipes invalidate dependent qualification; changed experiment
inputs produce a fresh campaign identity without rebuilding unrelated pieces.

## Evidence and validation

Original evidence remains under
`.artifacts/agent-efficiency/executions/codira-efficacy-campaign-011-20261002/`.
The additional `forensic-review-20261002/audit.json` records all 48 record/event
digests, arm totals, protected-stage statuses, native MCP failures and direct
contract/capture reproductions. The former disposable adjudication script was
copied there as audit evidence. Raw private paths and outputs stay ignored.
Retrospective protected patch checks are under the separate
`forensic-review-20261002/retrospective-patches/` identity and are discussed in
its addendum below. They cannot retroactively change admission or attempt status.

## Retrospective behavioral addendum

All 12 preserved patch artifacts were checked without credentials or model
turns in the exact frozen image. Eleven passed the frozen protected behavioral
branch: both F1, F2, P1, P2 and P3 attempts, plus F3 baseline. F3 assisted again
failed the disabled-conversion suffix assertion. Both over-ceiling F1 attempts
therefore have positive retrospective behavioral evidence, and both P2 repairs
pass when evaluated without the defective runner capture. These checks bypass
the broken semantic branch and use the preserved model patch for P2; they do
not prove successful runner capture or full semantic correctness.

## Complete task-by-task audit

B/M usage is input plus output. Operations are frozen; retrospective patch
behavior and text spot checks are separate. Unverified review means a final
semantic correctness decision remains outstanding.

| Task | B tokens | M tokens | M − B | Frozen operations B / M | Forensic correctness evidence |
| --- | ---: | ---: | ---: | --- | --- |
| panel-d1 | 218,973 | 222,652 | +3,679 | pass / pass | Text review unverified |
| panel-d2 | 285,880 | 165,715 | -120,165 | pass / pass | Text review unverified |
| panel-d3 | 85,976 | 107,361 | +21,385 | pass / pass | Text review unverified |
| panel-e1 | 473,544 | 378,078 | -95,466 | pass / pass | Text review unverified |
| panel-e2 | 146,501 | 313,047 | +166,546 | pass / pass | Text review unverified |
| panel-e3 | 2,921,387 | 698,301 | -2,223,086 | post-turn cap / pass | Text review unverified; assisted edits wrapper instead of transform |
| panel-f1 | 1,717,792 | 1,074,856 | -642,936 | post-turn cap / post-turn cap | Retrospective protected behavior pass / pass; full semantic grade unavailable |
| panel-f2 | 198,629 | 207,567 | +8,938 | pass / pass | Retrospective protected behavior pass / pass; full semantic grade unavailable |
| panel-f3 | 102,751 | 142,922 | +40,171 | pass / pass | Retrospective protected behavior pass / fail (disabled suffix); full semantic grade unavailable |
| panel-i1 | 350,675 | 966,468 | +615,793 | pass / pass | Text review unverified; baseline parity-test claim contradicted |
| panel-i2 | 1,138,788 | 972,000 | -166,788 | post-turn cap / pass | Text review unverified |
| panel-i3 | 130,489 | 218,937 | +88,448 | pass / pass | Text review unverified |
| panel-n1 | 130,788 | 157,170 | +26,382 | pass / pass | Text review unverified |
| panel-n2 | 133,798 | 122,752 | -11,046 | pass / pass | Text review unverified; grounding deficient in both |
| panel-n3 | 133,365 | 108,879 | -24,486 | pass / pass | Text review unverified; assisted alters fixture during navigation |
| panel-p1 | 680,511 | 408,916 | -271,595 | pass / pass | Retrospective protected behavior pass / pass; full semantic grade unavailable |
| panel-p2 | 164,426 | 297,133 | +132,707 | pass / pass | Retrospective protected behavior pass / pass; full semantic grade unavailable |
| panel-p3 | 165,680 | 177,634 | +11,954 | pass / pass | Retrospective protected behavior pass / pass; full semantic grade unavailable |
| panel-t1 | 175,180 | 143,326 | -31,854 | pass / pass | Text review unverified |
| panel-t2 | 745,914 | 482,613 | -263,301 | pass / pass | Text review unverified |
| panel-t3 | 138,387 | 354,752 | +216,365 | pass / pass | Text review unverified |
| panel-u1 | 232,769 | 223,852 | -8,917 | pass / pass | Text review unverified |
| panel-u2 | 199,914 | 162,170 | -37,744 | pass / pass | Text review unverified |
| panel-u3 | 200,959 | 312,684 | +111,725 | pass / pass | Text review unverified |

## Repository validation and retention

`uv run python scripts/validate_repo.py` passed with exit 0: 1,227 tests passed,
three skipped, 86% coverage, and zero local Semgrep findings. The durable log
and exit file are under
`.artifacts/validation/repo-gates/campaign011-forensic-20261002/`.
The tmux session `campaign011-forensic-gate-20261002` is retained with
`remain-on-exit`; its completed pane reports `dead=1`, `status=0`.
Local documentation links and `git diff --check` also passed. All 96 original
record/event digests recorded by this audit still match after retrospective
checks. Changes are documentation only; runner repairs and a new campaign have
not been implemented or launched. This paragraph records validation and does
not require rerunning the completed gate.
