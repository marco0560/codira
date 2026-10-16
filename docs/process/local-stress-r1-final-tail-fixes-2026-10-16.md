# Stress r1 final-tail failures: investigation and fixes

The completed `local-stress-20261010-r1` campaign added three failed stages after
its previous 1,492-outcome review. The fixes are isolated on
`fix/stress-final-tail`, based on `9de487f` and the earlier stress corrections.
Main and the immutable original campaign remain unchanged.

## Family MCP

The original family context command took 16,237.92 seconds and returned a total
of 11,996 candidates. The following MCP attempt retained capabilities and status
responses, then a generic exception group. Its configured request budget was
3,600 seconds. A request timeout remains the best-supported explanation; the old
receipt discarded the nested exception, so its exact original cause is unproven.

Inspection found two sources of avoidable work. Family collection reran complete
member retrieval/ranking for every 100-item member page. MCP also collected module
expansion and source-reference rows that it discarded when constructing its
match-and-snippet response. A live LLVM probe localized substantial work to that
unused reference scan.

A scoped core page reader now retrieves/ranks once per member operation. Family
collection retains all candidate items and their source evidence. The MCP item
path explicitly omits unused auxiliary expansion; full CLI output and MCP explain
retain it. There is no cross-request result cache or changed result limit. Native
mixed-backend tests compare complete item order, identities, scores and evidence
against public pages and direct-core output. Cursor and freshness tests remain
part of the full validation surface.

MCP transport failures now retain the active tool, elapsed time, exception type,
and complete nested traceback in the ignored attempt directory, alongside server
stderr and completed responses. A simulated SDK exception-group regression checks
retention and checkpoint reuse; it is not a native provider or transport proof.

## LLVM warm-query daemon

The original warm probe's traceback ends in socket receive with an uncaught
`TimeoutError`. Both the IPC server's execution budget and client timeout default
to five seconds. A valid large-index read can exceed that opportunistic CLI budget.

Transport timeouts and disconnects now become `QueryDaemonUnavailableError`, the
existing domain error consumed by normal CLI fallback. The standalone benchmark
accepts a finite positive `--request-timeout-seconds`, defaulting to 300, and uses
it consistently for server execution, initial warm qualification and measured
clients. It records the selected budget. Stress manifests can set
`daemon_query_timeout_seconds`; the launch receipt retains that explicit argument.
Normal CLI routing retains its five-second default. Native socket tests verify
both controlled fallback under a short budget and success under an explicit
longer one.

A separate copied LLVM index answered the retained `init` query warmly with exit
0 in 11.62 seconds under the explicit budget. That copy comes from the finished
daemon clone, after the campaign's semantic cleanup; it does not reproduce the
original pre-cleanup vector population and is not a comparative performance run.

## Foreground source-change reconciliation

The original daemon activity log shows successful initial reconciliation, no
second reconciliation, and shutdown after a one-hour wait. The runner edited its
witness immediately after observing initial success. The native watcher was only
created on subsequent generator iteration, after initial reconciliation, exposing
a startup window in which that edit could be missed.

The runtime now primes the watcher before initial reconciliation. Events during
initial indexing remain queued, and iterator/scheduler cleanup runs on every exit.
A native notification regression edits a file during the initial pass and requires
a second pass with an unchanged Git HEAD. The old startup order loses that event.
The harness also retains explicit timeout/process-exit reasons, observed generation
and state, elapsed time and process exit code when its second wait fails; it always
restores the witness bytes.

## Qualification evidence

Ignored evidence is under
`.artifacts/analysis/stress-final-tail-20261016/` in this worktree. The analysis
receipt identifies the original summary digest, reviewed patch, copied state and
probe scope. Original campaign files were not retried or overwritten.

- `native-warm-result.json`: native copied-LLVM warm request, exit 0.
- `native-family-member-r2-result.json`: all 11,894 current LLVM member candidates
  retain evidence, retrieved in 142.01 seconds. This is one member, not the entire
  family. Its candidate population is not asserted equal to the old campaign's
  runtime, which predates the inherited findings fixes.
- `native-family-member-interrupted.json`: preceding diagnostic probe deliberately
  stopped after stack sampling localized unused reference expansion. Its original
  script and log remain retained.
- `native-family-mcp-r3/receipt.json`: real stdio MCP returns 240 complete items
  across three pages from independently indexed SQLite and DuckDB repositories.
  Every item retains evidence and a distinct identity. Two earlier probe-launcher
  failures (parent Git scope and missing process-pool main guard) remain recorded
  separately and are not product results.
- `native-daemon-harness/receipt.json`: eight native synthetic harness stages pass,
  including real warm queries, a newer foreground generation, restoration, vector
  purge and semantic reset. This is qualification, not corpus task-success grading.

Repository quality preflight passes all seven checks. The first full gate passed
1,704 tests and skipped three, with one failure caused by the new worktree's model
directory symlink resolving outside its installation root. The directory now
contains local model files, and the unchanged containment test passes. That failed
gate's log, exit status and diagnosis are retained under
`.artifacts/validation/stress-final-tail/full-gate-r1/`.

The final `uv run python scripts/validate_repo.py` gate exits 0: **1,705 passed,
3 skipped, 86% coverage**, with 778 indexed files, zero failed files and zero
coverage issues. The completed tmux gate session and temporary gate log/exit files
were removed after examination; the final result receipt is retained under
`.artifacts/validation/stress-final-tail/full-gate-r2.json`.

No full stress campaign was rerun; any such run requires a fresh immutable identity
under the documented workflow. Implementation and validation used the isolated
worktree. No merge, release or publication was performed.
