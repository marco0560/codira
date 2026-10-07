# Issue 53 internal product assessment and improvement proposals

Updated: 2026-10-07. Scope: legacy Campaign 006 / Completion 009 and newer
representative Campaign 020 / Completion 027. Independent claim review is complete. The sections dated 2026-09-30 preserve the original assessment;
references to the then-current source/admission are historical, not descriptions
of today's implementation.
No paid experiment, new fixture admission, product change, or issue closure
is authorized by this document.

## Latest evidence and product direction — 2026-10-07

The [representative semantic closeout](agent-efficiency-luna-semantic-review-2026-10-07.md)
reviews 142 saved answers and preserves two protected patch failures in a
144-slot, 72-pair composite. Final reviewed passes are 65/72 baseline and 63/72
assisted; the task-level quality-difference interval spans zero. Resource
totals are modestly lower for the assisted arm in the 61 pairs where both pass,
but the equally weighted task token estimate reverses that direction and has
wide uncertainty. Neither result supports a broad quality or efficiency win.

The two patch failures are concrete task misses: an incorrect plugin capability
contract and an empty Go patch after failure to recover from an unavailable
editing command. They occurred in different tasks and opposite arms; neither
attempt used MCP, so they do not diagnose retrieval effectiveness. Semantic
failures additionally include incomplete requested edits/impact inventory,
wrong configuration-path or IPC-method attribution, omitted payload explanation and ungrounded
method-selection answers. The all-required grading rule distinguishes absence
of supporting evidence from substantive falsity.

C1–C5 and H1–H3 below are dated recommendations, subsequently implemented and
qualified offline in the [2026-10-01 implementation record](agent-product-harness-improvements-2026-10-01.md).
The newer runtime qualification exercised bounded paging, wrong-query/stale
cursor rejection, owner/whole-source evidence and coverage. Those receipts
qualify installed behavior; they do not prove semantic task efficacy. Campaign
011's denied calls and withdrawn semantic claims cannot supply that proof.
Campaign 016's absent deliverable and zero complete pairs likewise do not
establish model adequacy or comparative efficiency.

The immediate interpretation priorities are:

1. Align prompts, frozen requirements and protected behavior. Six ignore
   patches pass all independent protected matching/nonmatching/ignored checks;
   cross-review corrected their initial rejection for not adding an extra
   agent-authored nonmatching test. Cursor/freshness rubrics add conditions
   beyond the prompt, so their six failures cannot all be attributed to missing
   explicitly requested work. Two Sentinel test-coverage failures were also
   corrected: protected full-Option checks pass and the prompt does not prescribe
   an agent-authored full-container round-trip test. Preserve all original
   reviews and 14 appended amendments.
2. Check interface inventories, configuration paths, complete-object regression
   coverage and grounding against source. An operational terminal state or
   identifier presence cannot substitute for that review.
3. Investigate optional-treatment adoption before claiming tool causality:
   only 23 of 72 assisted attempts called MCP. An adoption-conditioned comparison
   is selected after treatment and would not isolate the effect of retrieval.
4. Compare resource use at matched reviewed quality, report task-balanced
   uncertainty, and separate recovery cost, preparation and provider charges.

Any further measurement should answer a specified unresolved question under
fresh controls, not simply rerun a completed schedule. This report authorizes
no follow-up experiment, external publication or new product implementation.

## Historical assessment — 2026-09-30

The campaign exposed useful retrieval, excessive retrieval overhead, weak
grading, and a serious deployed-runtime mismatch. Its five Sentinel diagnosis
pairs show a repeatable cost penalty with little additional answer quality.
The available evidence does not justify changing the benchmark model first.
Qualifying the actual runtime and improving retrieval precision are better
supported interventions.

The [audience findings](issue-053-audience-findings.md) persist the preceding
60-result quantitative analysis, including all 30 paired measurements. This
assessment adds forensic causes, substantive output review, a broader task
definition, and exactly five product and three harness recommendations.

## 1. What the campaign actually deployed

The campaign and supplement pin the same runtime digest,
`sha256:3d21c3c2bd82f00ccdc4a4f0b1d22bca38155ed1f00377b5e9ab6b7d9ac8b37c`.
An offline, read-only inspection of that cached image found:

| Property | Frozen runtime | Current checkout |
| --- | --- | --- |
| Installed package | Codira `2.0.2.post1.dev49` | Source inspected in this checkout |
| Context parameters | `query`, `output_budget` | `query`, `cursor`, `limit`, `search_profile` |
| Context result | `result.context` containing parallel matches/evidence and expansions | `result.items` containing aligned evidence |
| Context continuation | No context cursor | Query/profile/generation-bound item cursor |
| Whole-item paging | Not the current implementation | Implemented in `MCPAdapter.context_for_task` |

The image adapter hash is
`23dd8f3761e3b400b652c5c62075532e8b60040e5f3d50af948e5cb51d269fc3`;
the server hash is
`230ac72031f221a81ae80053d6242ff78d95b354503a37dcb3dfb45098dc58d5`.
The full public-safe receipt is retained in
`.artifacts/analysis/c006-c009-forensic-20260930/runtime-inspection.json`.

The 60 selected transcripts contain 33 context calls: 32 successful legacy
`result.context` responses and one tool error for an out-of-range character
budget. None exercised the new `result.items` continuation. Of the calls,
26 context responses, ten index-status responses, all eight capabilities
responses, and one documentation-search response were marked truncated.
That flag reports a budget overrun; it does not itself establish which useful
evidence reached the model or how many provider tokens it cost.

The five assisted context-page tasks found the new implementation and test in
the public Codira source fixture. They did not exercise the current protocol:
their installed tool returned the old bundle, even though the inspected source
had item pagination. In Sentinel repetition 4 the model submitted `limit=1`
alongside the legacy character budget and still received ten top matches,
with an empty page object. Other context-page queries asked for one-item pages
in prose, then used the legacy tool. Successful answers concealed this mismatch.

The existing [runtime admission](https://github.com/marco0560/codira/blob/main/scripts/agent_efficiency/runtime_admission.py)
calls `context_for_task` with `output_budget=512` and requires
`result.context.status == "ok"`. It neither verifies current item pagination
nor qualifies the current signature. Its check is aligned with the older
image. Host tests of newer source cannot establish image qualification.

Consequently, the initial aggregate numbers describe the deployed older MCP
treatment. They cannot support a conclusion about the current pagination
fixes. This is a correction to the interpretation, not a change to raw results.

## 2. Why Sentinel localization cost more

All ten diagnoses identify the same real pickle mechanism. All five assisted
attempts cost more and took longer than their paired baselines.

| Repetition | Baseline tokens | Assisted tokens | Baseline / assisted provider requests | Baseline / assisted MCP calls | Baseline / assisted shell commands | Assisted time increase |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 210,131 | 277,585 | 10 / 13 | 0 / 4 | 16 / 7 | 23.12 s |
| 2 | 212,084 | 384,260 | 9 / 16 | 0 / 3 | 17 / 12 | 43.14 s |
| 3 | 185,528 | 309,883 | 9 / 13 | 0 / 6 | 13 / 12 | 32.51 s |
| 4 | 175,184 | 300,925 | 9 / 13 | 0 / 6 | 10 / 10 | 32.55 s |
| 5 | 157,840 | 255,851 | 8 / 11 | 0 / 4 | 15 / 13 | 35.65 s |
| Total | 940,767 | 1,528,504 | 45 / 66 | 0 / 23 | 71 / 54 | 166.96 s |

The aggregate assisted penalty is 62.5% in tokens, 62.0% in ceiling-priced
cost, and 56.7% in agent elapsed time. Input tokens rose from 919,416 to
1,496,265. The request count rose 46.7%, and mean input per response rose
from 20,431 to 22,671 tokens, about 11.0%. These directly measured factors
explain the accumulated input increase: more continuations with larger
conversation context. They do not assign each extra token to a particular
tool message.

### Retrieval did not find the root cause on its first pass

Every initial assisted context bundle omitted both `Sentinel` and
`test_unset_sentinel`, including its expansion content. It instead returned
ten matches dominated by option, prompt, typing, or formatting material.
Examples at the top were
`test_option_custom_class_can_override_type_cast_value_and_never_sees_unset`,
the typing confirmation-option module, and `command_path` or `format_commands`.
Several received `confidence=1.0`, despite not explaining copying or pickling.
Broad option vocabulary outweighing the serialization symptom is a plausible
explanation for this misranking, not an isolated causal measurement. The traces
directly establish the omitted root-cause matches and retrieval detour.

Each attempt therefore continued into another retrieval path and shell reads.
The five initial context results emitted 12,849–14,272 characters in their
text content; each index-status result emitted 7,585 characters. All ten were
marked truncated. Raw character size is a diagnostic, not a tokenizer or
invoice measurement. Duplicated structured/text representations in the saved
MCP response are not counted twice in those character figures.

Embedding search sometimes found the sentinel test, but did not supply the
class as a strong implementation result. Repetition 2's source-restricted
embedding query returned no matches; repetition 5 returned unrelated prompt
and typing tests without the sentinel test. Three exact `symbol("UNSET")`
calls returned no symbol, whereas `symbol("Sentinel")` found the class.
An empty exact result for an alias or enum-related constant should not force
the user to guess the owning class.

### The query and procedure also broadened the work

The diagnosis task asked for the responsible symbol and source path. Every
assisted initial query additionally asked for a regression test, which was
not a required output for this task. The shared assisted instruction included
special context-page guidance; the first Sentinel trace explicitly reasoned
about identifying both implementation and regression testing before shell
inspection. This is evidence of task-specific guidance leaking into another
task's model trajectory.

Reclassifying these saved query strings with the 2026-09-30 deterministic
classifier yields `test` for all five augmented queries; the original short
diagnosis request yields `configuration` because it mentions option defaults.
This was a diagnostic of the inspected source, not proof of the serving
classifier's exact internal state. That classifier checked test vocabulary before
behavior and checks option vocabulary before general behavior. It therefore
warranted mixed-intent and symptom-query qualification. The subsequent
implementation prioritizes behavioral intent; these historical classifications
must not be described as current-source results.

### Saved shell work did not offset the extra turns

The assisted attempts executed 17 fewer shell commands, but made 21 more
provider response requests. There were 15 nonzero-exit shell commands in each
arm. Intentional failing pickle reproductions and diff commands contribute to
those counts, so they must not be labeled 15 model mistakes.

The first provider input was 10,247 tokens in every baseline attempt and
11,956 in every assisted attempt: a consistent 1,709-token starting overhead
from the treatment's tools and instructions. Subsequent larger responses and
extra tool continuations increased accumulated input. Several traces also
spent effort locating unavailable patch utilities or writing an answer through
malformed patches; both arms show this behavior. It is not exclusively a
Codira failure.

The assisted answers all add the existing sentinel test location. That is
useful extra traceability, but not an additional diagnosis or a required
deliverable. Both arms correctly explain that copying preserves identity and
unpickling fails. The quality gain is small compared with the consistent
resource penalty. The evidence supports a combination of deployed retrieval
misranking, verbose protocol overhead, extra guidance-driven exploration,
and model trajectory choices. It does not support a precise percentage
allocation among those causes or a counterfactual saving from any proposed fix.

## 3. Output quality beyond identifiers

### Review method and limits

I read every selected result artifact: 30 diagnosis/context/impact notes,
ten architecture notes, ten guides, and ten patch diffs. I checked their
substantive claims against the relevant frozen source and regression tests,
and inspected all ten Sentinel diagnosis trajectories. Task-level standards
were factual correctness, requested coverage, source traceability, and
practical usability. These are manual assessments; the reviewer knew the
arm identities. They are not blinded numerical quality scores or rewritten
oracle grades.

The output and transcript digests are recorded in `metrics.json` in the
derived analysis directory. In addition, all 31 JavaScript example blocks
were executed independently against the protected frozen Picomatch source.
All 73 displayed true/false outcomes passed. Blocks receive Picomatch in
scope when relying on the guide's earlier import. This checks the intended
examples, not whether concatenating every block into a single script works.
Execution used host Node `v26.3.0`; it corroborates examples but is not a
replay in the campaign's prepared runtime.

| Task | Substantive review of both arms | Differences the old oracle could not measure |
| --- | --- | --- |
| Sentinel diagnosis | 5/5 per arm explain identity-based enum values and failed unpickling; copying succeeds. No substantive diagnosis error found. | All five assisted notes add the test location; some baseline notes are shorter. No substantial correctness improvement. |
| Context identification | 5/5 per arm identify the method and test requested. The notes that describe cursor and ownership behavior agree with the source. | The answers are correct about the source fixture, but they do not establish that the runtime used pagination. Protocol execution was not graded. |
| MCP impact | 5/5 per arm describe shared direct/warm dispatch correctly. | Four baseline notes enumerate the concrete adapter caller inventory; no assisted note enumerates the complete inventory. Two baseline notes identify the proxy executor path; none of the assisted notes names it. Assisted notes more often cite named tests. |
| Picomatch architecture | 5/5 per arm describe entry points, parser compilation, and an independent scanner path correctly at the requested level. | All five assisted notes add relevant tests. Several baseline notes give a fuller helper inventory and compile path. No consistent overall quality winner. |
| Picomatch guide | All ten guides provide practical matching, ignore, and case examples; all 73 expected outcomes pass. | Three guides per arm mention flags taking precedence over `nocase`, but omit the empty-string exception. This is a small prose overgeneralization in both arms that neither headings nor their examples exposed. |
| Sentinel patch | All ten selected diffs narrowly alter the sentinel reduction mechanism and add tests for every member plus complete Option round trips. Protected grading passed in both arms. | Two assisted patches use `enum.pickle_by_enum_name`; the others use equivalent name-based `getattr` reconstruction. Test organization differs; no clear behavior or maintainability advantage established. |

For impact, the frozen source has concrete `_query` call sites in `symbol`,
`symbols`, `references`, `documentation_findings`, `context_for_task`,
`impact_analysis`, `repository_map`, `arch`, `emb`, `docs`, and `_call_edges`.
The latter serves callers/callees; `impact_analysis` invokes three queries.
The warm callback adapter is `_ConnectionExecutor.execute` in
`src/codira/mcp/proxy.py`; capabilities and index status bypass this boundary.
Examples with fuller inventories are baseline repetitions 1, 3, 4, and 5;
proxy-path discussion appears in baseline repetitions 2 and 5. Assisted
repetition 5 cites zero-file and pagination tests, but omits the most direct
warm-executor parity test and the affected caller inventory.

The impact prompt itself is underspecified about required completeness. These
are practical coverage differences, not automatic failures under its original
wording. A future task should explicitly request the caller set, dispatch
adapter, exclusions, and supporting tests so completeness can be scored fairly.

Architecture notes sometimes compress the Windows default behavior: the
frozen `index.js` wrapper applies detection when an options object is present
and `options.windows` is null/undefined; it does not unconditionally detect
the platform for every invocation. This qualification is useful for a deeper
entry-point task, but does not invalidate the requested high-level notes.

The baseline repetition 2 guide reuses `const isSourceFile` in separate
sections. Each example is correct independently; concatenation would need
separate scopes or different variable names. A usability rubric can distinguish
independent examples from a complete runnable script without rejecting correct
section-level examples.

A stronger prose check found a shared edge-case omission. The frozen
`picomatch.toRegex` uses `opts.flags || (opts.nocase ? 'i' : '')`. Therefore
`flags: ''` does not override `nocase: true`, whereas nonempty `flags: 'm'`
does. Three explicit probes confirmed those two outcomes and an `i`-flag
positive case. Baseline guides 2, 4, and 5 and assisted guides 1, 2, and 3
describe flags precedence without that qualification. This is a minor
overgeneralization, not a failure of their displayed examples. The probes
are saved in `guide-claim-probes.json`. Correct example comments alone cannot
validate every accompanying prose claim.

All ten patch tests inspect the transformed Option's name and default, not
merely a copied default variable. Every sentinel member is covered. Existing
behavioral grading is therefore more informative than identifier checks here.
Full project regression suites, all pickle protocol versions, and repository
style/type checks were not part of this retrospective patch review; they
should not be claimed as additional verified outcomes.

## 4. Broader task set: 24 candidate tasks

Use eight families with three distinct tasks each, rather than treating five
repetitions of one task as breadth. Retain small tasks as overhead controls,
add multi-step repository work, and include cases where reporting incomplete
evidence is the correct result. The following are proposed task definitions,
not admitted manifests or claims that a specific uninspected upstream bug
exists. IDs are candidate labels, not registered task IDs.

Use the current three public fixtures plus three new admission slots: a medium
Python service/plugin repository, a TypeScript workspace with re-exports, and
a Go service. Those slots require a selected public repository, pinned revision,
license, frozen environment, verified source evidence, and offline reference
checks before any campaign. Go preparation is not supported by the current
uv/npm/pip environment selector and requires explicit harness work. Candidate
size bands should be measured source-file counts and dependency depth; nominal
language or repository names are not complexity measures.

| Candidate | Fixture | Work requested | Grounded success evidence |
| --- | --- | --- | --- |
| N1 | Click | Resolve `UNSET`, `Sentinel.UNSET`, and its defining class, including alias relationships. | Canonical declaration, relationship, and exact source ranges. |
| N2 | New Python service | Select the correct method among identical short names in several classes using its described behavior. | Correct owner; distractors explicitly distinguished. |
| N3 | New TypeScript workspace | Trace a public re-export to its implementation and consumers. | Export chain, exact implementation, and verified consumer set. |
| D1 | Click | Diagnose the unset-default failure from an exception and observed copying behavior, without a symbol hint. | Causal mechanism, successful operations, failing operation, reproduction. |
| D2 | Picomatch | Explain case matching with `nocase` and nonempty or empty explicit flags. | Runnable positive/negative cases, empty-flags fallback, and source branch. |
| D3 | New TypeScript workspace | Diagnose an option-default propagation defect across a wrapper boundary. | Admitted real issue or frozen seeded mutation, causal path, reproduction. |
| T1 | Picomatch | Trace matcher, ignore, and callback execution for included and excluded paths. | Source branches and observed event ordering. |
| T2 | Codira | Trace one CLI option through configuration and the chosen query/backend boundary. | Complete ordered path and configuration precedence. |
| T3 | New Go service | Trace command configuration to a selected formatter/storage operation. | Package boundaries, concrete call path, executable observation. |
| I1 | Codira | Assess `_query` contract impact, listing direct callers, warm adapter, exclusions, and tests. | Reference caller inventory; warm/direct behavior; explicit scope. |
| I2 | Codira | Assess a backend/plugin interface change across first-party implementations and adapters. | Required implementation set and affected contracts; uncertainty labels. |
| I3 | New TypeScript workspace | Assess a re-exported API default change across runtime and type consumers. | Expected consumer set; runtime/type distinctions; negative controls. |
| P1 | Click | Preserve sentinel identity and complete Option copy/pickle behavior. | Existing protected behavior plus authored regression-test coverage. |
| P2 | Picomatch | Repair an admitted matcher/ignore regression spanning implementation and test. | Frozen seeded mutation or real historical issue; hidden edge cases. |
| P3 | New Go service | Repair an admitted empty/zero-value handling defect at a package boundary. | Independent behavioral checks plus unchanged unaffected cases. |
| F1 | Codira | Add a bounded CLI/query option consistently through existing layers. | New behavior, CLI errors, core contract, backward compatibility. |
| F2 | New Python service | Add a small plugin capability through its public adapter without bypassing the interface. | Contract tests, public API, existing plugin compatibility. |
| F3 | New TypeScript workspace | Extend an exported API parameter across wrapper and implementation. | Type checks, execution examples, old-call compatibility. |
| U1 | Picomatch | Write a usage guide with executable examples, flags precedence, and nonmatching cases. | Every claimed output checked, clear example execution scope. |
| U2 | New Python service | Write a concise operator/API recipe using the actual exported signature. | Real imports and runnable calls; useful failure explanation. |
| U3 | New Go service | Produce an operator runbook explaining startup/configuration precedence. | Verified commands/config cases and cited precedence branch. |
| E1 | Codira | Investigate an unavailable API and state what the evidence supports. | Correct absence/uncertainty answer; no invented symbol or path. |
| E2 | New Go service | Explain why evidence in an ignored/unsupported file is absent from the index. | Coverage warning, distinction from no repository evidence, safe fallback. |
| E3 | New TypeScript workspace | Investigate an edit, stale generation, and cursor continuation across re-indexing. | Freshness diagnosis; invalid old cursor rejected; new evidence retrieved. |

Each admitted task needs a reference evidence set beyond an expected answer
string: required facts, acceptable alternatives, critical incorrect claims,
source/relationship ranges, executable checks when applicable, and a clear
definition of completeness. Small/medium/large scope should be assigned after
admission. Keep source, implementation, test, and cross-layer tasks balanced;
avoid making all tasks explicit-symbol lookups or all tasks long bug fixes.

Split the 24 tasks into a development panel and a held-out panel of twelve,
balanced by family, language, and complexity. Fix the split before product
tuning. Keep scoring assets and answer keys outside the agent's indexed
workspace; ordinary source and legitimate tests remain available. Public
qualification tasks can coexist with separately frozen hold-out tasks. This
is a proposed validation protocol, not a claim of benchmark secrecy against
models trained on public source.

First qualify all reference checks and retrieval evidence offline. Then fix
the paid selection, repetitions, runtime, model, order, hypotheses, and budget
before inspecting new outcomes. More tasks and languages require a versioned
factory/executor extension: the current full stage accepts exactly six tasks,
three fixtures, and five repetitions. Do not hand-author an incompatible
campaign or silently broaden the current fixed stage.

## 5. Five high-leverage Codira/core and MCP improvements

The priorities below target failures supported by the trace and current source.
Expected benefit is an engineering hypothesis, not a measured future saving.
Existing item pagination and owner metadata must be retained and deployed;
they are not presented as new missing work.

| Rank / ID | Improvement | Evidence and expected benefit | Verification before claiming success |
| --- | --- | --- | --- |
| 1 / C1 | Preserve task intent and rank causal evidence ahead of generic vocabulary. | All five Sentinel context queries missed implementation and test. Diagnosis queries were broadened into test searches; high scores favored generic option material. Correct symptom/identifier anchors and mixed-intent routing should reduce follow-up searches for agents and irrelevant results for operators. | An offline query set including the five saved queries, paraphrases, explicit names, ambiguous names, and unrelated negative controls. Measure implementation/test recall at k, relevance precision, emitted evidence size, and ranking regressions on held-out tasks. |
| 2 / C2 | Make symbol resolution consistent for aliases, enum members, qualified owners, and re-exports. | Three `UNSET` lookups returned nothing while `Sentinel` resolved. Agents had to infer an owner; human operators face the same ambiguity. Reuse analyzer metadata and backend boundaries rather than inventing a parallel symbol registry. | Resolve declaration and canonical target for the Click forms; exercise duplicate method names and TypeScript exports; preserve case sensitivity; return all credible ambiguous matches with owners rather than selecting one silently. |
| 3 / C3 | Return expandable source and relationship evidence tied to stable symbol identity. | The current context excerpt is limited to six source lines, and exact symbols supply mainly locations. Agents still read source manually; impact answers omit concrete relationships despite correct identifiers. Provide discovery items and on-demand complete definitions, callers/consumers, and relevant tests with relation provenance. | Show the real sentinel value and reduction method without a second shell search; retrieve the `_query` caller inventory and proxy adapter; verify source ranges, ownership, freshness, and test links against a reference set. Never claim an unresolved static relation is a complete dynamic impact set. |
| 4 / C4 | Make default responses compact and uniform across core, CLI, and MCP while preserving complete significant items. | Status alone emitted 7,585 text characters in each Sentinel attempt; capabilities and context often reported overruns. Current context paging addresses one surface, while other tools still carry character-budget contracts and repeated analyzer metadata. Smaller default discovery/status output should lower agent context growth and improve human scanning. | Measure actual model-visible payloads, not just saved JSON sizes. Keep full diagnostics available on demand; retain query-bound cursors and item limits; label discovery snippets as snippets and offer whole definitions. No character cutting of significant items. Check CLI JSON, human output, MCP schemas, and caps together. |
| 5 / C5 | Expose interpretable retrieval/coverage diagnostics and exact runtime identity. | Irrelevant matches carried `confidence=1.0`; global ready status did not establish task-relevant coverage; package mismatch was invisible in outcomes. Let users see why a match was selected, which channel contributed, what is indexed, what is uncertain, and which core/analyzer build is serving the request. | Clearly distinguish ranking score from probability. Report task-relevant coverage and unresolved relationships. A compact discovery receipt identifies package/build/schema/profile/generation and all accepted parameter values. Explain-mode evidence must reproduce ranking decisions without dumping it into every ordinary answer. |

C1 should use existing retrieval planning, scoring, and explain infrastructure
in [classifier](https://github.com/marco0560/codira/blob/main/src/codira/query/classifier.py),
[context scoring](https://github.com/marco0560/codira/blob/main/src/codira/query/context_scoring.py), and
[context orchestration](https://github.com/marco0560/codira/blob/main/src/codira/query/context_orchestration.py).
Current classification prioritizes test vocabulary and option-related
configuration; `_extract_target_symbol` chooses an identifier-like token by
length, which can select ordinary task words. These mechanisms warrant
evaluation before choosing a new model or adding configurable profiles.
Do not encode a Sentinel-specific ranking exception.

C2 and C3 should share logical symbol identity and existing analyzer/backend
contracts. An alias does not need to be treated as a new callable; it needs
a discoverable relationship to the declaration. Full definitions should be
separate explicitly named evidence items, with safe source access bound to
the trusted repository and current generation. Test relationships should
say whether they come from static references, filename/name heuristics, or
verified behavior. Human operators need the same provenance.

C4 builds on the already implemented context cursor and whole-item response.
It should not revive character clipping or require every model to choose a
search profile. Defaults should serve common work; optional filters and
explain output should help advanced agents and people. Every accepted enum,
limit range, optional value, and profile remains discoverable through both
CLI caps and MCP capabilities, as already required by the operator.

C5 must not call heuristic rank confidence a probability of correctness.
Current [context rendering](https://github.com/marco0560/codira/blob/main/src/codira/query/context_render.py) defaults
confidence to 1.0 when no supplied map is available. A match score and its
reasons are more actionable than a certainty-like number. Compact ordinary
output and detailed operator diagnostics are compatible goals.

## 6. Three high-leverage harness and procedure improvements

| Rank / ID | Improvement | Why it matters | Acceptance evidence |
| --- | --- | --- | --- |
| 1 / H1 | Qualify exact deployed core/MCP behavior inside the pinned image. | The current admission probe accepts the legacy context shape. Host checks, fixture source hashes, and image existence did not prove that the campaign used the intended product. This invalidates protocol attribution. | Image receipt binds installed core/analyzer versions and source/build hashes, actual registered schemas, runtime profile, and model-visible tool set. Task-relevant probes prove limit=1, exact cursor continuation, wrong-query/stale-cursor rejection, whole evidence items, ownership, and coverage. New-protocol campaigns reject old runtimes before provider access. |
| 2 / H2 | Grade causal explanation, completeness, examples, and patch tests with traceable adjudication. | Seventeen answers containing the requested identifiers were rejected for spelling, while impact/path/headings checks could accept incomplete or empty explanations. Correctness and useful coverage need separate evidence. | Per-task rubrics accept equivalent wording and record required facts, counterclaims, relationship coverage, runnable examples, and protected behavior. Calibrate against known good, incomplete, and subtly wrong answers. Use deterministic executable checks first and a blinded reviewer for remaining semantics; disagreements retain the answer, rule, evidence, and reason. Original grades remain immutable. |
| 3 / H3 | Run representative, instrumented comparisons with an explicit treatment and hold-out procedure. | Six repeated tasks are narrow; required MCP use adds a starting tax and special guidance leaked across tasks. Aggregate tokens alone cannot locate overhead or establish general usefulness. | Admit the 24-task panel, separate development and hold-out tasks, isolate task-specific instructions, randomize arms, and keep the same model in the first corrected-runtime comparison. Record schema/prompt and tool payload sizes, first useful evidence, follow-up reads, per-phase timing, cached/uncached usage, observed pool spending, and every attempted trajectory. Compare optional MCP assistance with baseline, then a bounded forced-use ablation if needed. Report paired distributions and confidence/uncertainty with quality, cold/warm preparation costs, and all unsuccessful attempts. |

H1 is the first execution prerequisite. Its fixture and product receipts must
distinguish source under investigation from the installed tools that serve it.
Host source changes require a newly built/admitted image when the serving code
changes. A stable image digest is reproducibility evidence only after its
content has been qualified for the intended contract.

H2 does not require replacing every oracle with a paid model judge. Run
executable checks for examples and patches, deterministic source/relationship
checks where possible, and calibrated semantic review for explanation quality.
Score factual correctness, requested completeness, evidence grounding, and
usability separately. A concise answer should not lose credit for omitting
facts the task did not request. A source path or guide heading alone is not
proof of correct reasoning.

H3 should establish two separate measurements: retrieval quality before an
agent runs, and resulting work quality/resource use when the agent runs.
Reference evidence lets the first measurement run without paid completions.
The second captures whether good retrieval actually helps the model converge.
The default efficacy question should be whether available Codira improves
work; forced-first-use is a distinct interface/procedure experiment. Record
actual tool use in both. Shared task directives must remain identical across
arms, and pagination-specific instructions must be scoped to that task.

Keep the operator-approved observed dollar pool and permitted final-response
overshoot. Add informative progress/cost checkpoints rather than reinstating
worst-case reservations that stop measured spending far below the pool.
Preserve full paid evidence and uncertain in-flight requests after a crash;
settled completed attempts can join a fresh linked completion identity only
through the validated procedure. Instrumentation must not introduce new
hidden spending stops or automatically retry ambiguous paid calls.

## 7. Original proposed sequence and decisions — 2026-09-30

First review these reports and qualify H1 offline. Deploy the already written
pagination/owner fixes before attributing a new result to them. Establish H2's
reference quality checks and the offline retrieval panel. Evaluate C1 and C2
against that evidence, then C3–C5 against measured retrieval and payload gaps.
H3 supplies the broader experiment needed to test the resulting product.

A new model could be tested later as a separately frozen experiment after
the serving runtime is qualified. This campaign does not demonstrate that
model strength is the primary Sentinel problem; all ten diagnosis answers
were correct, and assisted retrieval initially missed the relevant evidence.
Choose model changes using an authenticated route and the pre-pilot checklist,
not an assumed catalogue availability or a larger token cap.

No future improvement percentage is asserted here. A successful intervention
must preserve substantive task quality and demonstrate reduced retrieval
detours, payload overhead, or end-to-end effort on the held-out panel. Negative
controls and new task variants are required to prevent tuning to these five
saved Sentinel query strings.

## Evidence and validation

The campaign source records, answers, patches, and full transcripts remain in
the immutable ignored `c006` and `c009` execution directories. The source
review used their protected fixture copies, not mutable upstream websites.
The [audience report](issue-053-audience-findings.md) describes reconstruction,
input digests, cost accounting, and all 30 paired deltas. Derived metrics,
guide check results, the read-only analysis script, and cached-image inspection
receipt are preserved in `.artifacts/analysis/c006-c009-forensic-20260930/`.

All 60 selected slots were verified against the frozen schedule; all have
complete usage and operational results. All 73 guide outcome checks passed.
The ten selected patch protected checks passed in their original records;
their source/test diffs were reviewed here without altering or rerunning the
paid attempts. No original campaign record was rewritten, and no new provider
completion was requested.

These tracked reports contain only public-safe summaries and repository-relative
paths; raw provider bodies, private host paths, and credentials are excluded.
The 2026-09-30 repository gate passed for the original report batch: exit `0`, 1,204 tests
passed, three skipped, and 86% coverage. The preserved log and exit record
are under `.artifacts/validation/repo-gates/phase8-assessment-20260930/`.
Report links, privacy, whitespace, and the required five/three recommendation
counts and 24 candidate tasks were checked.
Independent claim review is now complete. Implementation decisions, fixture
admission, paid authorization, publication and issue closure remain separate work.


## Closeout validation — 2026-10-07

Separate reviewers verified the legacy claims, the final 142 answer reviews and
14 appended amendments, all 24 task rows, paired estimates and their uncertainty,
cost scopes, source attribution and local links. Final receipts are retained in
`.artifacts/agent-efficiency/analysis/luna-semantic-review-20261007-r1/`;
the [semantic review](agent-efficiency-luna-semantic-review-2026-10-07.md)
documents methods and limitations.

The full repository gate passed: exit `0`, 1,394 tests passed, three skipped,
86% coverage and no blocking Semgrep findings. Log and exit evidence are retained
under `.artifacts/validation/repo-gates/issue053-closeout-20261007-r1/`.
Final documentation corrections after the full gate received focused integrity,
table, link and noncode checks. Phases 7–8 are complete and issue #53 is ready
for closure; publication and GitHub closure have not been performed.
