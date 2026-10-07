# Space Bunny omitted-parameter canary 023

One authorized canary ran on codira-tests under the $0.25 and 200,000-token caps. The only changed experimental instruction was to call context_for_task with query and limit, explicitly omitting cursor and search_profile. The core source, image, model, route and reasoning remained those of campaign 022. A fresh factory identity and execution directory preserved earlier evidence.

## Result

Blocked. index_status succeeded. context_for_task supplied empty strings for both cursor and search_profile; server validation rejected the cursor. The model stopped without retrying or writing the readiness marker. Native exit 0 is not readiness success. The generic result classification refers to the absent shell capture; the primary observed cause is the invalid tool arguments.

All three received upstream responses were HTTP 200, complete usage, SHA256-verified, with provider-reported cost zero. Provider/native tool arguments matched for both calls. Received tokens: 35,769. Conservative price-ceiling ledger: $0.00608428. Raw bodies and events remain in the execution readiness/model-requested-mcp/model-canary directory.

## Interpretation

Omitting optional parameters in the prompt did not prevent invalid generated arguments on this route. The model claimed the keys were required, but the retained offline wire capture for the unchanged core/native interface lists only query as required and allows nullable cursor/profile. This does not reveal transformations within OpenRouter or establish general model incompetence. A provider-side schema investigation is more informative than repeating prompt-only retries. No further model calls or main campaign launch occurred.

## Validation and isolation

100 focused offline tests passed on the host. Sandbox test runs failed Unix socket bind with PermissionError; the host rerun resolved that environment limitation. Full retained gate exit 0: 1,350 passed, 3 skipped, 85% coverage. Image/native/fixture/rubric and all 18 patch-pipeline checks passed. Original Luna checkout and campaign controls were not changed.

Prompt and versioned campaign spec committed as ae6f125 on fix/space-bunny-tool-guidance.
