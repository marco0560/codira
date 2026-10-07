# Codira efficacy campaign 011 — initial task and paired analysis

> Interpretation corrected by the [forensic audit](agent-efficiency-campaign-011-forensic-analysis-2026-10-02.md): all observed MCP calls were denied, most protected patch commands passed before a grader contract defect, and the original semantic pass claims were not supported by source-grounded adjudication. The frozen records remain unchanged.

Campaign `codira-efficacy-campaign-011` completed all 48 scheduled starts with 48 immutable result records. The final native runner checkpoint status is `complete` and `resume-006.exit` is `0`. This report preserves the campaign's frozen records and reports operational completion, frozen grading status, and provisional semantic receipts separately.

## Frozen identity and admission

| Control | Admitted value |
| --- | --- |
| Stage / panel | `representative-campaign` / `representative-v1`; 24 tasks, one baseline and one Codira-MCP attempt per task |
| Model / reasoning / route | `gpt-6-luna`, high, native Codex subscription on ChatGPT Plus; no API key or OpenRouter fallback |
| Image | `ghcr.io/marco0560/codira-agent-benchmark@sha256:6a1979bae149069c67058d66aad9abc73fefc86f68fce4f6fc868f8e51f7f4ab` |
| Source fingerprint | `0ee458cddf8a53415468429a58c03584c50983569c50ef8e0349526c9a5c5cee` (Codira 2.0.2.post1.dev115, commit `c19490e`) |
| Runtime profile fingerprint | `fa064e8d8a4d607aa67ddca2f9ab23dcc20df1494468c17bdec0b3770fe128d2` |
| Harness fingerprint | `5d859fc1276fa3da1534196769ebc5bb6b034c667d96bbe1c60c0a432a8a7ba3` |
| Manifest fingerprint | `6c92430b7bac4f329280113836639ed605264aa0afec3553524f5afa1d5cc5e1` |
| Schedule | Seed `20261002`, `48` attempts |
| Per-attempt controls | 1,000,000 total-token planning ceiling, 32,000 output-token limit, 1,800-second timeout |

The frozen full repository gate passed before launch: 1,227 tests passed, three skipped, 86% coverage, zero blocking Semgrep findings and zero Codira audit findings. Image qualification passed, including the credential-read denial, writable-workspace, blocked-network canary. The prelaunch campaign checks included 72 rubric calibrations and 18 applied patch calibrations. The final authenticated preflight ran through the isolated pinned image and reported Plus, the exact model/effort, visible unexhausted quota and the expected `network-none` container transport. Its last snapshot showed the Codex quota bucket at 82% used and base-model inference at 0%; across the 48 start snapshots the observed ranges were 79–82% and 0–0%, respectively. These are provider-reported percentages, not token balances or a guarantee that every remaining attempt would fit. Dollar accounting is not applicable to this subscription route.

A host-side preflight retry first stopped at Podman's runtime permission boundary before authenticated checks; that trace is retained. The corrected isolated preflight passed. A separate launcher admission attempt stopped before starting an attempt because its Python path shadowed the standard-library `types` module; the path was corrected to the archive root and resume 006 launched the sole remaining attempt. The count stayed at 47 starts until that official launch. Resume 004 had stopped after attempt 47's token-limit classification with one pending attempt; the 48th attempt then completed. No start was retried or overwritten.

## Operational outcomes

- **44 operational passes and 4 operational failures.** All four failures are `usage_cap_exceeded`; none is a provider authentication, subscription quota, or transport rejection. All 48 records have complete normalized model usage.
- **10 frozen task-oracle grading failures:** ten attempts across five pairs. Eight failed `oracle_contract` checks (F2, F3, P1 and P3); two failed `workspace_capture` (P2). Their model turns completed operationally; subsequent audit identifies grader/capture defects, with one protected behavioral failure.
- **38 `not_evaluated` task-oracle results** before retrospective semantic review: four token-limit failures and 34 answers routed to quality review. `not_evaluated` is not a correctness pass.
- The execution receipt retains 48 native JSONL event streams (1804 events total), per-attempt diagnostics, generated protected traces, attempt artifacts, and launcher/resume logs and exit files. The public-safe generated report is report.md (`.artifacts/agent-efficiency/executions/codira-efficacy-campaign-011-20261002/reports/report.md`), with its canonical report.json (`.artifacts/agent-efficiency/executions/codira-efficacy-campaign-011-20261002/reports/report.json`). Raw events and traces remain under the ignored execution root and are not copied into this document.

## Frozen grading and provisional semantic receipts

The ten frozen grading failures remain unchanged. Their failure labels do not
establish patch incorrectness: seven protected commands passed before a composite
quality branch raised a contract error; one F3 assisted command genuinely failed,
and both P2 attempts failed runner capture before grading. See the forensic audit
for the individual causes and separate retrospective checks.

The 34 opaque quality packets and quote-bound receipts remain preserved. The
prior adjudication script marked almost every criterion supported mechanically,
without source-grounded per-criterion validation. Its former 32/34 pass claim is
withdrawn. The two N2 grounding deficiencies are provisional findings, not a
complete validated semantic outcome set. The forensic audit also identifies
missed I1, E3 and N3 issues. No replacement blinded scores are asserted here.

## Task-by-task paired results

Token counts are recorded input plus output usage; `Δ` is Codira-MCP minus baseline, so negative values mean fewer reported tokens in the assisted arm. Labels distinguish frozen grading status from unverified retrospective review. Token deltas remain descriptive even when one or both task outcomes failed.

| Task / family / split | Fixture and task | Baseline: operations / correctness | Codira-MCP: operations / correctness | Baseline tokens | Codira-MCP tokens | Δ tokens |
| --- | --- | --- | --- | ---: | ---: | ---: |
| panel-d1 · diagnosis (development) | click-public — An unset option default survives shallow and deep copying but pickling raises an enum value lookup error. Diagnose the cause without assuming copying also fails. Give a minimal reproduction and source evidence. | passed / review unverified | passed / review unverified | 218,973 | 222,652 | +3,679 |
| panel-d2 · diagnosis (holdout) | picomatch-public — Explain matching with nocase and absent, empty and nonempty flags. Provide positive and negative executable cases and identify the source branch. | passed / review unverified | passed / review unverified | 285,880 | 165,715 | -120,165 |
| panel-d3 · diagnosis (holdout) | typescript-workspace-synthetic — Diagnose why format(text, {enabled:false}) changes case. Trace the wrapper boundary, explain the default rule and provide a reproduction. | passed / review unverified | passed / review unverified | 85,976 | 107,361 | +21,385 |
| panel-e1 · evidence (development) | codira-current-public — Investigate an alleged codira teleport_repository API. State what the repository and index evidence can establish; cite the search scope and avoid inventing an implementation. | passed / review unverified | passed / review unverified | 473,544 | 378,078 | -95,466 |
| panel-e2 · evidence (holdout) | go-service-synthetic — Investigate operator-notes.txt with the text analyzer disabled. Explain missing index coverage, distinguish absent retrieval from absent repository evidence, and use a safe source fallback. | passed / review unverified | passed / review unverified | 146,501 | 313,047 | +166,546 |
| panel-e3 · evidence (holdout) | typescript-workspace-synthetic — Index the fixture, request paged context, then edit transform and reindex. Demonstrate that the old cursor is rejected and new discovery/evidence reflects the edit. Explain index generation and source freshness. | failed / not evaluated (token limit) | passed / review unverified | 2,921,387 | 698,301 | -2,223,086 |
| panel-f1 · feature (development) | codira-current-public — Add context --max-results as a bounded integer from 1 to 100, default 10. Connect it through CLI to core paging without cutting evidence items. Test valid values, errors and default compatibility. | failed / not evaluated (token limit) | failed / not evaluated (token limit) | 1,717,792 | 1,074,856 | -642,936 |
| panel-f2 · feature (holdout) | python-service-synthetic — Add Adapter.capabilities() returning a case_conversion boolean. Built-in Upper/Lower advertise true through the plugin interface; legacy render-only plugins work and advertise false. | passed / oracle fail: oracle_contract | passed / oracle fail: oracle_contract | 198,629 | 207,567 | +8,938 |
| panel-f3 · feature (holdout) | typescript-workspace-synthetic — Add an optional third suffix parameter to the public format API, wrapper and implementation. Append it after conversion; default empty suffix preserves existing calls and declarations. | passed / oracle fail: oracle_contract | passed / oracle fail: oracle_contract | 102,751 | 142,922 | +40,171 |
| panel-i1 · impact (development) | codira-current-public — Assess a change to MCPAdapter._query. List every direct caller, the warm connection executor, operations that bypass it, and relevant tests. Label dynamic uncertainty. | passed / review unverified | passed / review unverified | 350,675 | 966,468 | +615,793 |
| panel-i2 · impact (holdout) | codira-current-public — Assess changing BackendQueryConnection.execute. Identify first-party implementations and warm/proxy adapters, affected query callers and contract tests. Distinguish static evidence from dynamic completeness. | failed / not evaluated (token limit) | passed / review unverified | 1,138,788 | 972,000 | -166,788 |
| panel-i3 · impact (holdout) | typescript-workspace-synthetic — Assess changing the exported default for format. Enumerate runtime and type consumers, wrapper behavior and negative controls. | passed / review unverified | passed / review unverified | 130,489 | 218,937 | +88,448 |
| panel-n1 · navigation (development) | click-public — Resolve UNSET, Sentinel.UNSET and the defining class. Explain the alias chain and cite exact declaration ranges. | passed / review unverified | passed / review unverified | 130,788 | 157,170 | +26,382 |
| panel-n2 · navigation (development) | python-service-synthetic — Select the method that converts text to lower case among the identically named methods. Identify its owner, adapter dispatch and distractors. | passed / provisional grounding gap | passed / provisional grounding gap | 133,798 | 122,752 | -11,046 |
| panel-n3 · navigation (holdout) | typescript-workspace-synthetic — Trace public format from its re-export through the implementation. List runtime consumers and distinguish the unrelated format. | passed / review unverified | passed / review unverified | 133,365 | 108,879 | -24,486 |
| panel-p1 · patch (development) | click-public — Fix sentinel pickling by name while preserving every member identity for copy, deepcopy and pickle and complete Option name/default behavior. Add regression tests. | passed / oracle fail: oracle_contract | passed / oracle fail: oracle_contract | 680,511 | 408,916 | -271,595 |
| panel-p2 · patch (development) | picomatch-public — Repair the seeded ignore regression. Ensure an ignored matching path returns false and onIgnore runs instead of onMatch; nonignored matches remain true. Add regression tests. | passed / oracle fail: workspace_capture | passed / oracle fail: workspace_capture | 164,426 | 297,133 | +132,707 |
| panel-p3 · patch (holdout) | go-service-synthetic — Repair the seeded zero-limit defect: zero means unlimited, including empty text, while negative limits remain errors and positive truncation remains unchanged. Add Go regression tests. | passed / oracle fail: oracle_contract | passed / oracle fail: oracle_contract | 165,680 | 177,634 | +11,954 |
| panel-t1 · tracing (development) | picomatch-public — Trace matcher, ignore and callbacks for a match, an ignored match and a nonmatching path. Give executable observations of event order. | passed / review unverified | passed / review unverified | 175,180 | 143,326 | -31,854 |
| panel-t2 · tracing (development) | codira-current-public — Trace context --search-profile from argument parsing through configuration, query execution and backend selection. Explain configuration precedence and errors for an unknown profile. | passed / review unverified | passed / review unverified | 745,914 | 482,613 | -263,301 |
| panel-t3 · tracing (holdout) | go-service-synthetic — Trace SERVICE_MODE and mode=lower from startup configuration to formatting. Give the package boundaries, call order and executable output. | passed / review unverified | passed / review unverified | 138,387 | 354,752 | +216,365 |
| panel-u1 · usage (development) | picomatch-public — Write a concise usage guide with runnable matching/nonmatching examples, ignore callbacks and flags precedence including the empty-flags exception. State actual expected outputs. | passed / review unverified | passed / review unverified | 232,769 | 223,852 | -8,917 |
| panel-u2 · usage (development) | python-service-synthetic — Write a runnable operator/API recipe using the actual exported signature. Demonstrate both modes and unsupported-mode failure; cite public adapter behavior. | passed / review unverified | passed / review unverified | 199,914 | 162,170 | -37,744 |
| panel-u3 · usage (holdout) | go-service-synthetic — Write an operator runbook with executable startup commands. Explain default/environment/argument precedence, expected outputs and the current zero-limit failure. | passed / review unverified | passed / review unverified | 200,959 | 312,684 | +111,725 |

## Paired analysis and limits

All 24 pairs have complete usage records. The report's all-pair mean token difference is **-102,220** tokens (Codira-MCP minus baseline), median **-2,619**, with task-resampled 95% bootstrap interval **[-333,970, 60,081]**. The interval crosses zero. This includes operationally failed attempts and is strongly affected by E3 baseline's unusually large completed turn, so it is not an efficacy estimate.

For the 16 pairs the generated report includes with `outcome="success"` and complete usage, Codira-MCP used fewer tokens in 8 pairs and more in 8; the median difference was **-2,619** tokens and the nearest-rank p90 was **+216,365**. Eight other pairs are excluded from this successful-outcome subset: five pairs with grading failures and three pairs affected by token-limit failures (F1, E3 and I2). The previous semantic claims for this subset are unverified; N2 has a provisional grounding deficiency in both arms. With one repetition per task, heterogeneous task families and these exclusions, the token comparison is descriptive and does not establish a general efficiency gain.

Total recorded usage was **19,292,861 tokens** across 48 attempts. The four token-limit failures were:

| Attempt | Input | Output | Total | Above 1,000,000 |
| --- | ---: | ---: | ---: | ---: |
| `panel-f1-r01-baseline` | 1,704,169 | 13,623 | 1,717,792 | 717,792 |
| `panel-f1-r01-codira-mcp` | 1,066,970 | 7,886 | 1,074,856 | 74,856 |
| `panel-i2-r01-baseline` | 1,126,801 | 11,987 | 1,138,788 | 138,788 |
| `panel-e3-r01-baseline` | 2,902,537 | 18,850 | 2,921,387 | 1,921,387 |

The limit was a post-turn usage check on the native route: these four model turns reached terminal output before the executor could classify them, so the 1,000,000-token setting did not interrupt a runaway turn at that boundary. E3 baseline produced a complete answer artifact at nearly 2.92 million tokens; both F1 arms produced patch artifacts, and I2 baseline produced an answer. Those outputs lack frozen oracle decisions. This supports evaluating whether a higher guard is appropriate, but does not justify changing this campaign's frozen control or converting these four operational failures into passes. Any rerun with a different ceiling must use a new immutable campaign identity and repeat admission. The cap should remain a runaway-task safeguard rather than an interpretation of correctness.

## Evidence and validation

Factory artifacts remain under `.artifacts/agent-efficiency/campaigns/codira-efficacy-campaign-011/`; the 48-attempt execution root, route snapshots, native events, diagnostics and review receipts remain under `.artifacts/agent-efficiency/executions/codira-efficacy-campaign-011-20261002/`. The automated report validates each immutable record against the frozen configuration fingerprint. The semantic review receipts bind decisions to answer and rubric digests and quotes, but do not establish factual validity. No original attempt result was edited.

## Final repository gate

After preparing this report, `uv run python scripts/validate_repo.py` passed in tmux session `campaign011-results-gate-20261002-r1`: 1,227 tests passed, three skipped, 86% coverage, and exit status 0. Its durable log and exit file are retained under `.artifacts/validation/repo-gates/campaign011-results-20261002-r1/`; this audit has not verified continued session retention.
