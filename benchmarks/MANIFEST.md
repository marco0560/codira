# Benchmark directory manifest

This directory contains benchmark inputs. Runtime output belongs under
`.artifacts/`; do not place generated run data beside the inputs.

## Layout

| Path | Role | Handling |
| --- | --- | --- |
| `agent-efficiency/` | Versioned campaign specifications, schemas, frozen fixtures, task/oracle pairs, protected probes, and reviewer configuration | Tracked experimental inputs; preserve historical identities. |
| `embedding-model-candidates.json` | Candidate model and engine definitions used by embedding campaigns | Tracked input; scripts and docs use this path. |
| `retrieval-quality-repos.local.json` | Repository set for retrieval-quality campaigns | Tracked input; default path used by scripts and docs. |
| Other root `*.local.json` files | Machine-local or generated benchmark manifests, when present | Ignored local inputs; keep at their documented paths because scripts and operator workflows may refer to them. Do not commit local datasets or path-bearing configs. |

## Navigation and retention

- `agent-efficiency/campaign-specs/` is the source for factory-generated
  campaigns. Generated campaigns and attempt evidence belong in
  `.artifacts/agent-efficiency/` or `.artifacts/ae/`.
- Schemas, fixtures, tasks, oracles, and protected probes are grouped by
  function under `agent-efficiency/`; preserve them as versioned controls.
- Performance benchmark input manifests remain at their established paths for
  CLI defaults and documented commands. Do not relocate them without updating
  every consumer and preserving local-only configurations.
- For runtime artifact groups, retention decisions, and the current review of
  potential cache cleanup, see [`.artifacts/MANIFEST.md`](../.artifacts/MANIFEST.md)
  and [`docs/process/artifact-retention-review-2026-09-27.md`](../docs/process/artifact-retention-review-2026-09-27.md).
