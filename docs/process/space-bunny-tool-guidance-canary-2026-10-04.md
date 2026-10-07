# Space Bunny tool-guidance diagnostic

The operator authorized clearer MCP guidance, the four proposed diagnostic
improvements and one new Space Bunny readiness canary on 2026-10-04. Retain the
previous tests-key limits: $0.25, 200,000 received/reserved tokens, 64,000 output
per response, seed 261004, max reasoning, 45 logical requests and three transport
attempts. Main campaign execution is not authorized by this diagnostic request.

Work is isolated on branch fix/space-bunny-tool-guidance so the running Luna
campaign 020 retains its original checkout, image, prompts and harness. The
old blocked Space Bunny campaign 019 and its evidence remain immutable. The
fresh selected factory identity is campaign 022; only its preparation canary will run.
Its image extends the exact campaign 019 base and inherits that base's native
binaries, with the updated serving source reinstalled by the repository builder.

Changes: actual MCP request schemas explain nullable first-page cursors and
supported profile names; the context tool description explains pagination;
validation errors include corrections without coercing invalid inputs. The
canary explicitly supplies cursor=null and search_profile=default, calls
index_status first and rejects any failed tool even if later calls succeed.
Offline checks cover schema and argument preservation through provider mapping.
Canary diagnostics verify retained response digests and compare provider output
arguments with native started-call arguments using multiplicity rather than
ordering, because tools can run concurrently. JSON and SSE are both supported.
The diagnostic retains only names, counts and argument digests; complete values
remain in ignored raw responses and native events.

A local replay of campaign 019 verified all seven upstream response bodies and
matched all nine Codira calls, including the invalid arguments. The local client
path therefore did not rewrite those arguments in that canary. Transformations
inside OpenRouter remain outside this evidence boundary.

This experiment changes both prompt and interface guidance together. A passing
canary would show that this combination supports the qualification task; it
would not identify the contribution of each change or prove campaign efficacy.
One failed canary remains a bounded negative result, with no automatic retry or
main launch. Persist build, preparation, gate, route, accounting and argument
comparison results under a fresh ignored execution root and retain terminal
status. Do not modify tracked inputs after the ready receipt is issued.

The operational preparation command is retained at
.artifacts/agent-efficiency/analysis/spacebunny-guidance-20261004-r1/prepare-022.sh
in the original checkout; it runs the standard launcher from the isolated
worktree and writes all campaign evidence to the original durable artifact root.

Campaign 021 was superseded before preparation or model contact: the source
audit required the changed validator to document its raised contract error.
Keep its factory artifacts and first image as unused diagnostic provenance.
Campaign 022 binds the final audited source and rebuilt image instead.

The canary result and the follow-up omitted-parameter canary are recorded in
[the campaign 022 outcome](agent-efficiency-space-bunny-tool-guidance-outcome-2026-10-04.md)
and [the campaign 023 outcome](agent-efficiency-space-bunny-omit-options-canary-2026-10-04.md).
