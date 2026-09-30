# Campaign 006 answer adjudication and patch-stop investigation

Campaign `codira-efficacy-campaign-006` exited with code 2 after 55 of 60
scheduled attempts. It left 27 complete pairs, one unmatched Codira patch
attempt, and five unstarted attempts. The 55 settlements total $4.09832850 at
the campaign's configured price ceilings. Original result records and frozen
campaign identities remain unchanged. This document records a retrospective
manual adjudication and the separate prospective oracle revisions.

## Adjudication of the 17 failed text answers

The reviewed task prompts request the responsible symbol or method, its source
path, and, for the context task, the regression test. All 17 answers provide
those facts. Their original failures came from exact substring checks, not
from missing requested identities. This finding is based on inspection of
each saved `BENCHMARK_ANSWER.md`; it does not establish that every explanatory
detail in those answers is correct.

| Attempt | Decision | Rejected wording and retained evidence |
| --- | --- | --- |
| `context-page-001-r01-baseline` | Accept | Gave the exact method and both paths; qualified the test as `test_mcp_server.test_context_items_page_complete_evidence_and_method_owner`. |
| `impact-001-r01-baseline` | Accept | Described `MCPAdapter._query` as the adapter query boundary at the requested path. |
| `impact-001-r01-codira-mcp` | Accept | Described the same method as the shared query boundary at the requested path. |
| `impact-001-r02-baseline` | Accept | Described the `_query(operation)` contract and direct/warm query boundary at the requested path. |
| `impact-001-r02-codira-mcp` | Accept | Named `MCPAdapter._query`, its path, and its shared boundary behavior. |
| `impact-001-r03-baseline` | Accept | Named the adapter query boundary, path, and direct callers. |
| `impact-001-r03-codira-mcp` | Accept | Named `MCPAdapter._query`, its path, and shared adapter query boundary. |
| `impact-001-r04-baseline` | Accept | Named `MCPAdapter._query`, its path, and shared execution boundary. |
| `impact-001-r04-codira-mcp` | Accept | Named `MCPAdapter._query`, its path, and shared read boundary. |
| `localize-001-r01-codira-mcp` | Accept | Named `Sentinel.UNSET` and its path; explained why the `object()` enum value fails pickle reconstruction. |
| `localize-001-r02-baseline` | Accept | Named `Sentinel`, its path, and the pickle value-identity failure. |
| `localize-001-r02-codira-mcp` | Accept | Named `Sentinel`, its path, and the pickle value-identity failure. |
| `localize-001-r03-baseline` | Accept | Named `Sentinel.UNSET`, its path, and the pickle value-identity failure. |
| `localize-001-r03-codira-mcp` | Accept | Named `Sentinel.UNSET`, its path, and the pickle value-identity failure. |
| `localize-001-r04-baseline` | Accept | Named `Sentinel`, its path, and the pickle value-identity failure. |
| `localize-001-r04-codira-mcp` | Accept | Named `Sentinel`, its path, and the pickle value-identity failure. |
| `localize-001-r05-codira-mcp` | Accept | Named `Sentinel`, its path, and the pickle value-identity failure. |

The impact oracle required the exact phrase `MCP adapter query boundary`.
Each failed answer identified `_query`, `src/codira/mcp/adapter.py`, and a
boundary but used a different phrase. The localization oracle required
`click._utils.Sentinel` as one contiguous string; each failed answer gave
`Sentinel` or `Sentinel.UNSET` together with `src/click/_utils.py`. The context
oracle accepted two test-ID formats but omitted the module-qualified spelling
used in the saved answer.

The revised public oracle definitions accept these equivalent spellings while
still requiring the named symbol or method and source path. A read-only replay
of all 28 completed text-task artifacts under the revised definitions passed
28/28: all 17 former failures and all 11 former passes. This is a retrospective
diagnostic, **not** a replacement for campaign 006's frozen grades or a new
campaign result. The text oracles still check named facts, not the full causal
explanation or complete impact set. Future paid runs require a fresh campaign
identity and the pre-pilot checklist because oracle fingerprints changed.

## `patch-002-r05-codira-mcp` terminal trace

The attempt recorded 23 upstream HTTP 200 responses totaling 687,079 input
and 20,847 output tokens (707,926 combined). The 24th request was refused by
the local proxy with `session_token_reservation_exceeded` (HTTP 429). Its
remaining whole-session allowance was 292,074 tokens. The proxy conservatively
reserves the UTF-8 request-body byte count plus the configured 32,000 output
tokens, so this refusal implies a request body above 260,074 bytes. The exact
request-body size was not retained in the safe response observations. Actual
provider usage had not reached the 1,000,000-token limit, and the evidence
does not show upstream throttling or exhaustion of the $10 shared pool. The
attempt's settled ceiling-priced charge was $0.18740500. Its incomplete turn
has zero normalized usage in the result record; the 23 response observations
are the source for the token count above.

The saved trajectory contains 28 shell commands, 12 failed commands, three
repeated commands, and two MCP calls. After a successful reproduction, the
agent attempted several malformed `git apply` patches. One eventually added
`__reduce_ex__` after module-level type aliases in `src/click/_utils.py`,
outside the `Sentinel` class. The test file gained only imports; it did not
gain a regression test. No completed patch artifact or protected oracle result
was produced. The stop is therefore both an early conservative reservation
limit and a nonconverging edit trajectory. More token allowance alone would
not have established a correct patch.

## Implications

- Report the original campaign as 37 oracle passes, 17 literal-oracle
  failures, one operational failure, and five missing attempts; do not
  silently replace its grades with the retrospective adjudication.
- The 17 reviewed text answers meet the named task requirements. For those
  answers, the original pass-rate difference between arms measured formatting
  sensitivity. The four completed patch pairs passed in both arms; the fifth
  patch pair is incomplete.
- Before another paid campaign, use the changed oracles under a new immutable
  identity, verify the controls, and separately address patch editing behavior
  and the conservative token-reservation policy. Preserve campaign 006's raw
  attempt evidence for further review.

Evidence remains in the ignored
`.artifacts/agent-efficiency/executions/c006/state/records/` and
`state/attempt-work/` directories. This report contains no credential values,
raw provider bodies, or paths outside the repository.

## Validation

Focused oracle and corpus checks passed: 13 tests. The first full gate stopped
at a test-file formatting check; the file was formatted and that failed gate
record was retained. The final full gate passed with 1,192 tests passed, three
skipped, and 86% coverage. Its durable evidence is
`.artifacts/validation/repo-gates/c006-adjudication-r2-20260930/validation.log`
and `validation.exit` (value `0`). A tracked-report scan found no credentials
or paths outside the repository in this document.
