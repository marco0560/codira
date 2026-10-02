# Native Codex subscription provider

## Selecting the route

A ChatGPT Plus subscription includes the native Codex client. It does not provide
OpenAI API credits. The harness therefore supports two distinct immutable routes:

| Control | OpenRouter | Native Codex subscription |
| --- | --- | --- |
| Provider | `openrouter` | `codex-subscription` |
| Model identity | `openai/gpt-6-luna` | `gpt-6-luna` |
| Wire contract | `responses` | `codex-cli` |
| Authentication | Scoped SOPS environment | Existing managed Codex login, bound read-only |
| Accounting | Observed campaign dollar pool | Native account quota; USD fields are zero sentinels |
| Provider evidence | Exact received HTTP responses | Complete native JSONL events and process diagnostics; raw HTTP responses unavailable |
| Request and output limits | Enforced by the proxy | Native client owns these; manifest values are planning controls |
| Session token ceiling | Planning estimate in a shared pool | Checked after the native turn completes |
| Stop controls | Dollar pool, timeout, request/retry limits | Quota between attempts, timeout, six-hour checkpoint |

Changing providers requires a fresh specification, factory output directory and
execution identity. There is no fallback from subscription to an API key or
OpenRouter. `forced_login_method="chatgpt"` rejects API-key authentication.
Zero prices mean **not applicable**, not a claim that subscription usage is free.
Native quota exhaustion checkpoints before another attempt; an unfinished start
requires investigation rather than an automatic retry. A provider can exhaust
quota during a turn. The native route cannot reproduce the OpenRouter proxy's
per-response budget enforcement or raw HTTP forensic evidence.

The account can advertise several quota buckets without identifying which one
applies to the selected model. Admission stops only when every advertised bucket
is exhausted. A full unrelated bucket does not block a model whose provider may
use another bucket; the native provider decides actual model eligibility. Quota
snapshots are measurements, not a reservation for the whole campaign.

## Admission and credential isolation

The image must contain the exact qualified Codex executable and bundled
bubblewrap. Offline qualification first uses a public fake credential and checks
that model tools cannot read `/codex-state/auth.json`, can write `/workspace`, and
cannot reach the network. Actual managed credentials are mounted only after this
check passes. They are never copied into scratch state or included in receipts.

The native permissions profile denies the whole client state directory, disables
tool network access, and runs without overriding legacy `sandbox_mode` or
`--sandbox danger-full-access` settings. Podman retains a read-only root,
`network=none`, no-new-privileges, its default seccomp policy and a PID limit.
All capabilities are dropped, then **SETFCAP alone** is restored for the native
route: Linux requires it when bubblewrap maps UID zero into a nested user
namespace. The OpenRouter route retains its original capability policy.
Privileged containers and unconfined seccomp are diagnostic probes only and are
not campaign launch settings.

The native client reaches only exact allowlisted TLS CONNECT destinations through
a host Unix socket and a container loopback relay. The tunnel forwards opaque
TLS bytes without decrypting, logging or persisting authorization headers.
Model tools are denied access to that socket along with the client state.

Read-only admission uses the native app-server's `account/read`, `model/list`
and `account/rateLimits/read`. Receipts retain plan type, model, reasoning effort
and quota measurements; they omit email, account identity and authentication
material. These calls do not start a model turn. Admission is repeated before
execution and quota is checked before every scheduled attempt.

## Factory and launcher

Use the same campaign factory and deterministic launcher as OpenRouter. Native
specifications require `representative-campaign`, `wire_api="codex-cli"`,
`budget_reservation_mode="subscription-quota"`, and zero USD prices and ceilings.
OpenRouter specifications require positive prices and dollar ceilings. The
schema and runtime reject crossed accounting modes.

The launcher additionally requires `--subscription-codex` naming the qualified
host client and `--subscription-auth-source` naming the existing managed login.
Only the path and client executable digest are inspected by preparation; the
login contents are not read. Native launch commands do not invoke SOPS and do not
supply provider API credentials. Always generate commands through the factory
and launcher; do not replace them with an ad-hoc Codex invocation.

A successful route preflight proves account/model/quota visibility and transport
admission. It does not prove that an agent can solve the benchmark tasks or that
an entire campaign fits within the remaining subscription quota.
