# Phase 6 paid-review gold-standard protocol

Status: active process control. This document authorizes no provider request.
Every paid request still needs a separately approved experiment identity.

## Purpose

Produce model-comparison evidence that is reproducible, attributable, and
diagnosable. A transport, schema, parser, accounting, or harness failure is an
indeterminate experiment outcome, never evidence of review quality.

## Non-negotiable invariants

1. Freeze the manifest, diffs, prompts, model IDs, provider controls, output
   schema, limits, and artifact root before reading a credential.
2. Persist the exact received provider response in an ignored per-attempt
   artifact before parsing or semantic validation. Terminal state records the
   artifact path and SHA-256, never the response body.
3. Never persist credentials, request headers, or decrypted environment data.
   Do not emit a response body to logs or tracked files.
4. Use no fallback provider. Prove the returned model identity, provider
   identity, `finish_reason`, and complete usage before admitting a result.
5. Stop at the first indeterminate outcome. Do not retry, resume, increase a
   limit, or reinterpret it as a model verdict.
6. A changed prompt, output schema, model/provider route, fixture, runner, or
   control creates a new experiment identity and needs explicit approval.

## Stage 0 — Offline protocol qualification

Run without credentials or network access. The qualification suite must cover
the exact request serialization and deterministic fixtures for at least:

- valid structured response;
- prose or Markdown preceding an otherwise valid verdict;
- invalid JSON and schema-invalid JSON;
- missing or incomplete usage;
- wrong returned model or provider identity;
- truncated response and transport failure; and
- a valid response body rejected by a semantic grader.

For every received-body fixture, assert that the artifact is written before the
failure state, its digest is recorded, and no body reaches stdout, stderr, or a
tracked file. Run the focused tests, static checks, `codira audit --json`, and
the repository gate in tmux before a paid stage is considered.

## Stage 1 — Route and schema admission

Use non-completion checks first: public model catalog for price/capabilities and
authenticated `/models/user` for key-visible models and reasoning controls.
Require each exact model to advertise the controls used by the frozen request.

The default response contract is OpenRouter strict JSON Schema,
`response_format.type = json_schema`, with `strict: true`. Its schema must use
an enum verdict and an explicit findings array. Require the response-format
parameter in provider routing and keep `allow_fallbacks: false`. Do not use a
prompt-only first-line parser as the primary wire contract.

If either route cannot prove support for the exact strict-schema request, stop
before a completion and report it as an admission failure.

## Stage 2 — Paid calibration

Calibration is a distinct, explicitly approved experiment, not a benchmark.
Its manifest sets a separately bounded request and monetary cap, normally one
request per exact model. It proves only that the live route returns a complete,
model-identified, provider-identified response conforming to the frozen schema
and accounting contract.

Store request and prompt digests, response evidence, provider metadata, usage,
latency, and validation result. Calibration success does not establish review
quality. Calibration failure blocks the paired evaluation.

## Stage 3 — Paired evaluation

Only a passed calibration unlocks a separately approved paired evaluation.
Use the same frozen labeled corpus, prompt template, controls, output schema,
and repetitions for every model. Classify each attempt as:

- `admitted`: complete response and accounting satisfy every contract;
- `indeterminate`: a provider or harness contract failed; or
- `not_run`: blocked by an earlier terminal outcome.

Calculate quality, cost, and latency only from admitted attempts. Report
indeterminate and not-run counts independently; never impute them as passes,
failures, zero cost, or zero latency.

## Stage 4 — Failure investigation and restart decision

Before any change or later run, publish a short evidence note containing the
experiment identity, terminal state, artifact digest/path, request controls,
provider/accounting evidence, and failure classification:

- request/admission;
- transport/provider;
- response-schema or parser;
- accounting/identity; or
- model-quality result.

For a harness defect, add the exact offline response fixture first, make the
smallest repair, and pass the full repository gate. For a provider or model
result, do not change the harness merely to obtain a favorable outcome. In both
cases, a subsequent paid call requires a new identity and explicit approval.

## Budget and operator controls

Each approved stage states both budgets independently:

- OpenRouter: maximum requests, output tokens, timeout, conservative USD cap,
  preflight key limit/remaining balance, and stop condition.
- Agent work: one bounded evidence investigation and one surgical repair cycle
  per failure. If the evidence does not identify a safe next action, stop and
  ask the operator rather than performing speculative probes or retries.

The operator receives the preflight record, terminal result, and failure note.
No model replacement or default-model change follows from a failed calibration
or incomplete paired record.

## Sources adopted

This protocol incorporates strict JSON-Schema output and required provider
parameters from OpenRouter's Structured Outputs guidance, the versioned cases,
deterministic assertions, and captured actual-provider-event pattern documented
by Promptfoo, and repeatable documented TEVV controls from NIST AI RMF.
