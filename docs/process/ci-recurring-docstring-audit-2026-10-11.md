# Recurring CI documentation-audit failures, 2026-10-11

The three inspected CI runs failed deterministically in the final documentation
audit, after the test suite passed. The newest run passed 1,548 tests with three
skips. Its Windows daemon and installer smoke jobs passed. This is not evidence
of a flaky test or infrastructure outage.

| Run | Source commit | Audit findings |
| --- | --- | --- |
| [38134653027](https://github.com/marco0560/codira/actions/runs/38134653027) | `f2c403334f21478e49c93c22649cf9f38a1d4d28` | 10 |
| [38122049894](https://github.com/marco0560/codira/actions/runs/38122049894) | `c3f959853f59b2cc167209c13625034d5dd66da9` | 5 |
| [38082493540](https://github.com/marco0560/codira/actions/runs/38082493540) | `c8a0ee3fd5a0e68c777f2e4cf1cc7ebf992c529a` | 5 |

## Causes

1. The NumPy parameter parser recognized only one identifier before a colon.
   Valid grouped declarations such as `stdout, stderr : str`,
   `prefix, name : str`, and `state, config : pathlib.Path` were ignored.
   This produced six false missing-parameter findings in the newest run.
   [The official format specification](https://numpydoc.readthedocs.io/en/v1.10.0/format.html)
   permits grouping parameters sharing a type and description. Context7 lookup
   did not provide the numpydoc documentation; the official specification was
   used as the fallback.
2. Three docstrings contained real contract errors: `Campaign.command` and
   `write_architecture_artifacts` omitted `Raises`; the generator implementing
   `index_response_scope` documented `Returns` instead of `Yields`. The latter
   generated two findings, giving four real findings in total.
3. The earlier local benchmark-findings gate used `CODIRA_CONFIG_FILE` pointing
   to a replacement configuration containing only `[embeddings] enabled = false`.
   Replacement configuration does not overlay the repository file. It omitted
   the tracked NumPy audit route, so no documentation diagnostics were generated.
   That local audit result did not demonstrate documentation compliance. A fresh
   structural index using the tracked configuration reproduced all ten findings.

## Fix and prevention

The parser now enumerates comma-separated valid parameter identifiers, including
starred variadic names, while rejecting malformed group headers. The three real
docstrings now describe the explicit exceptions and generator behavior.
The NumPy audit implementation revision advances to `2`, its distribution to
`2.0.1`, and the official bundle to `2.0.7`, with aligned pins and lockfile.

Both repository validation entry points rebuild all structural audit facts with
`--full --defer-embeddings`. They reject nonempty configuration, target, and
output routing environment overrides before executing validation children.
Ordinary Codira CLI override behavior remains available. Recovery commands and
limitations are documented in [the script guide](../scripts.md#scriptsvalidate_repopy).

Raw run logs, job metadata, baseline index and audit evidence are retained in the
isolated worktree under `.artifacts/analysis/ci-recurring-20261011/` (ignored).
Regression tests cover grouped and single parameters, whitespace, variadics,
invalid groups, early override rejection without value disclosure, and full
structural refresh in both gates. Validation results are recorded below after
execution. No benchmark campaign was run or stopped during this repair.

## Local validation findings

The first gate exposed four shifted suppression-inventory line references; these
were corrected without adding or relaxing suppressions. The second gate passed
1,559 tests with three skips and failed one stale packaging expectation, which
was aligned with the NumPy plugin version bump.

The second gate also paused in the empty-directory Semgrep rule-validation test.
A Semgrep worker was observed waiting in `fuse_check_timeout`; the exact remote
filesystem path was not established. A bounded probe using the same rules and
an explicit `--project-root` completed successfully within seconds. The test now
sets its temporary scan root explicitly, avoiding ancestor project discovery.
[Semgrep's CLI documentation](https://github.com/semgrep/semgrep-docs/blob/main/docs/snippets/cli-reference/help-scan.mdx),
retrieved through Context7, documents this override. This was a local validation
delay, not the cause of the inspected GitHub failures. The slow gate completed;
no benchmark process was interrupted.

## Final validation

The focused audit/workflow/package suite passed 79 tests. The focused packaging,
Semgrep and hygiene follow-up passed six tests. The final quality preflight
passed all seven checks, including a fresh configured documentation audit.

The full repository gate passed with exit 0: **1,560 tests passed, three skipped,
86% coverage**. Its full structural refresh indexed 751 files, reused none,
and failed none. The final configured documentation audit had zero findings
(the CLI reports its empty result as `no_matches`).
The Semgrep regression used an explicit project root; the full suite completed
in 328.31 seconds, compared with 824.22 seconds in the preceding slow run.
These are local validation timings, not benchmark measurements.

All three gate logs and exit statuses, the corrected audit JSON, and a validation
receipt are retained under `.artifacts/analysis/ci-recurring-20261011/`; transient
tmux/gate files are retired after examination. This fix is validated locally on
`fix/ci-recurring-failures`. GitHub CI confirmation requires submitting the
branch; no claim of a new successful remote run is made here. Main and its
running benchmark environment were left untouched.
