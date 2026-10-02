# Representative campaign preparation — 2026-10-02

## Scope and identities

Preparation covers 24 representative tasks, two arms and one repetition: 48
attempts per campaign. No model completion or campaign was launched during
preparation. Campaign 010 selects OpenRouter; campaign 011 is a separate native
Codex subscription alternative, not a fallback or an additional authorized run.
Both use `gpt-6-luna` at high reasoning, a 1,000,000-token session planning
ceiling, 32,000 output tokens and a 1,800-second attempt timeout.

The comparison measures optional MCP availability against shell access. Codira
CLI remains installed in both arms, and the freshness diagnostic explicitly
tests its protocol. Report diagnostic tasks separately from general task
efficacy; do not describe the panel as product present versus product absent.

## Image and fixtures

The admitted image is
`ghcr.io/marco0560/codira-agent-benchmark@sha256:6a1979bae149069c67058d66aad9abc73fefc86f68fce4f6fc868f8e51f7f4ab`.
Its core source fingerprint is
`0ee458cddf8a53415468429a58c03584c50983569c50ef8e0349526c9a5c5cee`;
its benchmark profile fingerprint is
`fa064e8d8a4d607aa67ddca2f9ab23dcc20df1494468c17bdec0b3770fe128d2`.
It contains qualified Python, TypeScript and Go analyzers, Node 22.22.0,
Go 1.24.4 and Codex 0.159.3 with its bundled sandbox executable.
Serving product source matches the inspected checkout; extra inactive host
analyzers do not replace required image analyzers.

The representative panel uses `codira-current-public`, frozen at committed
`c19490e`, for its five Codira tasks. The legacy fixture is unchanged. Panel-f1
keeps the agreed task: its seed removes the CLI result-limit option and fixes
forwarding at ten, while retaining the current core pagination implementation.
The protected probe checks bounds, default and actual CLI-to-core forwarding.
This corrects the previous fixture/task mismatch instead of relaxing the task.
A detached source checkout is retained under the preparation execution record
so committing the active branch cannot invalidate the fixture's pinned revision.

Runtime qualification checks installed MCP schemas, whole evidence items,
limit-one continuation, qualified method owners, source identity and analyzer
coverage. The TypeScript freshness replay exercises edit, stale expansion,
reindex, stale cursor rejection and fresh source expansion in the actual image.
Durable evidence is under
`.artifacts/agent-efficiency/environment-images/representative-20261002-r8/`.
Earlier image attempts and failed qualification evidence remain intact.

## Rubric and protected-check calibration

The [calibration report](agent-efficiency-panel-calibration-2026-10-01.md)
covers all 24 full rubrics and 72 source-curated answer probes. Eighteen correct
text exemplars cite inspected source or actual freshness observations; six
correct patch exemplars are applied and checked in the admitted image.
Incomplete and subtly wrong cases record the decisive missing or contradicted
requirement. Campaign semantic answers still require blinded adjudication;
these examples do not create an automatic semantic truth classifier.

All six patch tasks additionally receive correct, incomplete and subtly wrong
applied patches: 18 behavioral calibrations. Protected Python, Node and Go
checks now execute in the exact admitted offline image rather than inheriting
the host toolchain. Safe Git patch application remains on the host. Complete
command output and failure traces are retained, and timed-out grader containers
are removed. Graders receive no provider credentials.

## Provider controls and estimates

The [native provider contract](agent-efficiency-subscription-provider.md)
documents subscription authentication, accounting and evidence limitations.
Fake-credential qualification proves denied credential reads, allowed workspace
writes and blocked tool networking before actual login binding. Linux nested
namespace admission needs SETFCAP alone; other capabilities remain dropped,
with default seccomp and no-new-privileges. The actual isolated route admits
Plus, `gpt-6-luna` and high reasoning without starting a model turn.

Subscription quota buckets lack a model mapping. A full unrelated bucket does
not cause an early stop; admission stops when all advertised buckets are
exhausted, with the native provider deciding model eligibility during execution.
Native USD fields mean not applicable. Proxy request/output/retry caps cannot be
enforced on native transport; session tokens are checked after the turn.
Interrupted starts block automatic resume, while completed slots are preserved.

Authenticated OpenRouter admission verifies exact key-visible model, reasoning,
context, pricing and allowance without a completion. Its threshold price tier
begins at 272,000 tokens; the frozen ceilings are $0.25 input and $0.75 output
per million. Campaign 010 uses the approved $10 observed-spend pool, allowing
the final response to cross it. It makes no advance worst-case reservation.
A key limit above the campaign pool is headroom, not a rejection reason.

The read-only authenticated catalog additionally reports base prompt/completion
prices of $0.10/$0.50 per million and threshold prompt/completion prices of
$0.20/$0.75. Cache-write pricing reaches $0.25; the frozen input ceiling therefore
covers that tier too. At preparation, the scoped key reported $11 remaining,
$0 daily usage and a daily reset. These are dated snapshots, not launch-time
allowance guarantees. Final native quota reported 77% used in the Codex bucket and
0% in the base-model bucket, without an authoritative model-to-bucket mapping.

The previous completed campaign and completion run totalled $4.40064275 for
60 retained attempts under their frozen price accounting, or $4.58804775 when
abandoned attempts are included. Scaling the retained total to 48 gives about
$3.52; lower base-tier pricing suggests less. A practical planning range is
roughly $1.5–$3.5, with uncertainty from the new task mix and token tiers. This
is an estimate, not an invoice prediction. The $10 pool remains comfortable.
Subscription usage cannot be converted into a comparable dollar estimate.

## Admission checklist and handoff

The [pre-pilot checklist](agent-efficiency-campaign-factory.md#pre-pilot-control-checklist)
and its representative/native extensions govern both identities. Controls
checked here include frozen source, image and environments; generated task and
oracle digests; rubric calibration; provider separation; interruption and quota
handling; evidence retention; unchanged common arm instructions; and distinct
factory, validation, preparation, preflight and execution stages.

Factory artifacts belong in
`.artifacts/agent-efficiency/campaigns/codira-efficacy-campaign-010/` and `011/`;
execution preparation belongs under the corresponding grouped execution roots.
Source bindings and managed credential locations remain in ignored local
receipts. Re-check model, price and allowance immediately before launch.

The first full repository gate exposed four new tests using Unix socket paths
longer than the operating system permits. Those tests now use short disposable
paths under the designated scratch directory; the focused checks pass. The
failed gate and its exit status remain under
`.artifacts/validation/repo-gates/campaign-preparation-20261002-r1/`.
Final gate and factory admission results are recorded below.

The second gate passed all 1,227 tests with three skips and 86% coverage, then
rejected missing NumPy docstring sections in new harness functions and tests.
Those sections are now complete; the focused Codira audit reports zero findings.
The second gate's complete failed record is preserved under the matching `r2/`
directory.

The [launch prompt](agent-efficiency-campaign-010-launch-prompt.md) authorizes
only the paying OpenRouter campaign in a new conversation. Preparation itself
does not authorize starting either campaign here.

## Final admission results

The full gate passed with exit 0: 1,227 tests passed, three skipped, 86% coverage,
zero blocking Semgrep findings and zero Codira audit findings. Its durable log
and exit record are in
`.artifacts/validation/repo-gates/campaign-preparation-20261002-r3/`;
the completed tmux session is retained. Ruff formatting, generated panel/schema
checks, rubric replay and the additional type check also passed.

Both fresh factory outputs passed `--check`, and the deterministic launcher
prepared both execution receipts with all six admitted fixture bindings:

| Campaign | Provider | Attempts | Manifest fingerprint |
| --- | --- | --- | --- |
| 010 | OpenRouter | 48 | `8d942341d236814203938ed61b9d8c92b1cb43dbb6a22ba9c9fcd40f67aada8f` |
| 011 | Native subscription | 48 | `6c92430b7bac4f329280113836639ed605264aa0afec3553524f5afa1d5cc5e1` |

Both bind harness fingerprint
`5d859fc1276fa3da1534196769ebc5bb6b034c667d96bbe1c60c0a432a8a7ba3`.
Prepared execution roots are
`.artifacts/agent-efficiency/executions/codira-efficacy-campaign-010-20261002/`
and the corresponding `011-20261002/` root. Their
`authenticated-preflight-r2.json` records passed manifest-bound provider
admission. The earlier preflight invocation selected only one task and was
rejected locally before contacting either provider; its empty output remains
preserved. The corrected invocation supplies all 24 task identities.

The OpenRouter receipt confirms a 1,050,000-token context, 128,000-token model
output ceiling, high reasoning support and $11 remaining. The native receipt
confirms Plus, the selected model and effort, actual container transport and
quota visibility after credential-denial qualification. Neither starts a
model turn. Public calibration summaries, manifests and this report were
checked for private paths and credential material; raw local evidence remains
ignored. Handoff documentation now points here and to the exact launch prompt.
