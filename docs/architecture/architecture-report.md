# Repository architecture reports

`codira arch` turns the current repository index into a
deterministic, analyzer-independent architecture snapshot. It is useful before
a large change, during design review, and when an agent needs a compact map of
modules, dependencies, cycles, and policy pressure points.

## Generate a report

Refresh the index after a meaningful edit batch, then write the report:

```bash
codira index
codira arch
```

The default output directory is `.codira/architecture-report`. Use `--output`
to keep a report elsewhere:

```bash
codira arch --output /tmp/my-project-architecture
```

The command always writes these replayable artifacts from one shared model:

- `architecture.dot` — module/file dependency graph in Graphviz DOT.
- `architecture.md` — summary, module inventory, hotspots, cycles, and
  policy violations.
- `dependencies.json` — complete module inventory, analyzer facts, aggregate
  dependencies, retained evidence, cycles, and degree metrics.
- `hotspots.json` — stable ranking by `fan_in + fan_out`, then fan-out,
  fan-in, and module name.
- `violations.json` — policy violations with rule ID, severity, edge kind, and
  retained symbol evidence.
- `manifest.json` — emitted files and optional SVG status.

When Graphviz `dot` is available, Codira also writes `architecture.svg`. It is
optional: a missing or failing `dot` never removes the mandatory artifacts and
is recorded as a stable warning in `manifest.json`.

## Layer policies

Define layers in order with repository-relative path prefixes. Earlier layers
win when prefixes overlap, which makes ownership explicit and deterministic.
Forbid one directed layer dependency with a stable rule ID and severity:

```bash
codira arch \
  --layer api=src/api \
  --layer core=src/core \
  --forbid api-must-not-call-core:api:core:error
```

Layer values must use `NAME=PATH_PREFIX`; rules must use
`RULE:SOURCE_LAYER:DESTINATION_LAYER:SEVERITY`. Empty names, duplicate IDs,
duplicate directed rules, unknown layers, and ambiguous duplicate prefixes are
rejected before artifacts are written. Modules outside every layer remain
explicitly unlayered and do not create a violation.

## JSON evidence and limitations

JSON analyzer facts are ordinary indexed declaration artifacts. The inventory
therefore includes conservative generic manifest structure (keys, object paths,
arrays, references, URL/path values, and truncation diagnostics) alongside
persisted JSON facets and a known ecosystem only when its recognizer proved it.
The report renderer does not assign JSON-specific semantics.

The graph is intentionally conservative. It aggregates indexed imports, static
calls, and callable references only when both module endpoints are resolved.
Dynamic imports, runtime dispatch, external packages, and unresolved targets
are missing evidence—not negative architectural facts. Read the retained
symbol evidence before acting on a graph edge or violation.
