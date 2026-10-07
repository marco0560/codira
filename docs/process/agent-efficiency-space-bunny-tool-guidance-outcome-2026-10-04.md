# Space Bunny tool-guidance canary outcome — 2026-10-04

Implemented and committed on isolated branch `fix/space-bunny-tool-guidance`:
`a9140ee`, followed by audited qualification correction `37d7df8`. The original
Luna checkout and campaign 020 controls were not changed. Original blocked
campaign 019 remains immutable. Campaign 021 was superseded before preparation
or model contact; selected campaign 022 used the final audited image.

## Implementation and validation

Actual MCP schemas, capability discovery and context-tool descriptions explain
first-page cursors, exact returned continuation tokens and supported profile
names. Cursor/profile validation errors include correction guidance without
coercing invalid arguments. The canary requests index_status first, then exact
query/limit/cursor=null/search_profile=default arguments, and forbids retries.
Admission rejects any failed tool even if later calls succeed. Retained-provider
diagnostics verify raw-body digests and compare argument digests with native
MCP dispatch, preserving call multiplicity and allowing concurrent ordering.

Focused MCP/readiness tests: 123 passed, 1 skipped. Existing provider/runner
regressions: 68 passed, 2 skipped. Factory/image tests: 20 passed. The final
retained repository gate exited 0: 1350 passed, 3 skipped, 85% coverage,
zero blocking Semgrep findings. Independent Codira audit had no findings.
Image/runtime, native dispatch, fixture freshness, rubric and all 18 patch
pipeline cases passed before authenticated model admission.

## The single new canary failed

The model successfully called index_status, then generated:

```json
{"cursor":">null","limit":1,"query":"Qualification probe helper","search_profile":"default"}
```

Codira correctly rejected this string as an invalid continuation cursor and
returned the improved first-page guidance. The model stopped after that error,
did not retry and did not write the ready marker. This is improved stopping
behavior compared with campaign 019, but context retrieval remains unqualified.
The native process completed its turn; readiness failed on the tool/marker
contract. The generic run-result label `infrastructure_failure` / `tool-output
capture event is absent` is a downstream consequence of the missing shell step,
not evidence of a provider outage or the earlier bubblewrap problem.

Three upstream responses returned HTTP 200. Complete received usage was
36,614 tokens. The ceiling-based ledger was $0.00627316, within the approved
$0.25 / 200,000-token canary limits. Provider cost fields are recorded in
outcome.json separately from this conservative ledger. There was no local
429 or reservation exhaustion. All three raw responses were digest-verified;
all two Codira calls matched native dispatch arguments. No main campaign was
launched and no additional external model call was attempted.

## Actual native-wire inspection, with no external model calls

The model claimed cursor was declared as string-only. A mocked-provider probe
using the same native client, image and provider mapping captured the actual
model-facing context_for_task schema. It retained cursor anyOf string/null,
search_profile anyOf enum(default)/null, and required only query. Thus the local
client did not strip nullable support or make cursor mandatory. Native schema
normalization does drop defaults, minLength and numeric bounds; server-side
validation still enforces them. These changes do not explain the generated
string >null. This probe
captured the wire schema; its intentionally rejected mock response caused a
native timeout, so it is not a successful model execution or readiness result.
Only public tool-schema data was retained from the request, not request bodies
or credentials. Failed preliminary offline probes remain separate evidence;
the successful schema capture is offline-native-wire-schema-r4/wire-schema.json.

The old canary replay also verified all seven upstream bodies and matched all
nine Codira calls. Together these checks rule out argument rewriting in the
inspected local path. They cannot distinguish the underlying model from
transformations inside OpenRouter, nor prove general model inadequacy.

## Remaining hypothesis

A future separately authorized canary could provide only
{"query":"Qualification probe helper","limit":1} and explicitly require
omitting cursor and search_profile. Both omissions are valid in the inspected
wire schema and select first page/default on Codira. Keep the same guards and
other controls, use a fresh immutable identity, and preserve campaign 022 as
a qualified negative result. This would test whether avoiding explicit-null
argument generation helps this route; it would not isolate all prompt/schema
changes or establish main-campaign competence. No such extra canary was run.
