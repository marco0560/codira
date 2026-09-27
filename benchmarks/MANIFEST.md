# Benchmark directory manifest

This tree contains benchmark inputs. Runtime output belongs under
`.artifacts/benchmarks/`; do not place generated run data beside the inputs.

## Layout

| Path | Role | Handling |
| --- | --- | --- |
| `agent-efficiency/` | Versioned campaign specs, schemas, fixtures, task/oracle pairs, protected probes, and reviewer configuration | Tracked experimental controls; preserve historical identities. |
| `embedding/model-candidates.json` | Candidate model and engine definitions | Tracked input shared by embedding and retrieval-quality tools. |
| `embedding/uv-backed-repos.local.json` | Repository set for the embedding campaign | Ignored local input; keep local dataset and paths untracked. |
| `retrieval-quality/repos.local.json` | Repository set for retrieval-quality campaigns | Tracked input used by retrieval-quality defaults. |
| `performance/` | Backend torture, generated-size, and short-run manifests | Local-only inputs; ignored and grouped by benchmark family. |
| `semantic-pipeline/frozen-repos.local.json` | Frozen repository set for semantic-pipeline work | Local-only input; ignored and separate from generic performance manifests. |

## Navigation and retention

- Agent-efficiency campaign specifications are under
  `agent-efficiency/campaign-specs/`. Generated manifests, executions, and
  attempt evidence are under `.artifacts/agent-efficiency/campaigns/`,
  `.artifacts/agent-efficiency/executions/`, and
  `.artifacts/agent-efficiency/attempts/` respectively.
- Schemas, fixtures, tasks, oracles, and protected probes are grouped by
  function under `agent-efficiency/`; preserve them as versioned controls.
- `performance/` and `semantic-pipeline/` keep machine-local manifests out of
  the root while leaving them ignored. Keep generated results under
  `.artifacts/benchmarks/`.
- For runtime output groups, retention decisions, and the completed cache
  cleanup, see [`.artifacts/MANIFEST.md`](../.artifacts/MANIFEST.md) and the
  [retention review](../docs/process/artifact-retention-review-2026-09-27.md).
