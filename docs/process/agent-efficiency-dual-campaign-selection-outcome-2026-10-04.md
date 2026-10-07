# Dual campaign preparation outcome

Campaign 020 (OpenRouter GPT-6 Luna, high) has complete passing readiness.
Campaign 019 (Space Bunny Alpha, max) is blocked after its authorized canary.
Neither main campaign was launched. Commit: bea43e3. Both final gates: 1332
passed, 3 skipped, exit 0.

Space Bunny requested context_for_task seven times with invented cursor values
`.` or the empty string, sometimes also using unsupported search_profile `.`.
Only index_status and capabilities succeeded. The prompt explicitly required
stopping on a failed tool, which the route did not follow. Seven verified
upstream HTTP 200 responses preceded a local 429 session_token_reservation_exceeded.
Received usage was 81,720 tokens; the guard additionally reserves the next
UTF-8 request body and 64,000 output tokens, so admission can stop below 200,000
received tokens. This is not upstream throttling.

The ceiling-priced ledger was $0.01350684, distinct from the zero catalog price.
Reported response cost fields: [0, 0, 0, 0, 0, 0, 0]. All seven exact received bodies were
SHA-256 verified. Raw responses, native events and failure evidence are retained.
No further inference was attempted. A larger guard alone would not establish
that the model can construct valid tool arguments or obey stopping instructions.

Recommended next experiment: clarify the common readiness prompt with explicit
first-page arguments, cursor=null and search_profile=default, then requalify
both models under fresh campaign identities to keep the qualification harness
matched. Keep main task prompts and guards unchanged. This requires explicit
authorization for two additional bounded canaries; the original two have been
consumed. Alternatively retain Space Bunny as blocked and use only Luna.

Luna launch must reproduce the recorded PATH/PYTHONPATH/XDG_RUNTIME_DIR. The
command in luna-launch-command.txt reproduces these bindings before invoking
the standard receipt-only launcher. It does not replace campaign controls.
Its original authenticated admission expires after fifteen minutes; do not
rewrite that receipt or claim an implemented four-hour refresh command.
