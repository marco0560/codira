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
| `retrieval-quality/known-target-v1/` | Public pinned, automatically derived cases and fixture revisions | Tracked controls; regenerate through `scripts/build_known_target_dataset.py`. Private cases remain ignored. |
| `performance/` | Backend torture, generated-size, and short-run manifests | Local-only inputs; ignored and grouped by benchmark family. |
| `semantic-pipeline/frozen-repos.local.json` | Frozen repository set for semantic-pipeline work | Local-only input; ignored and separate from generic performance manifests. |

## Navigation and retention

- Agent-efficiency campaign specifications are under
  `agent-efficiency/campaign-specs/`. Generated manifests, executions, and
  attempt evidence are under `.artifacts/agent-efficiency/campaigns/`,
  `.artifacts/agent-efficiency/executions/`, and
  `.artifacts/agent-efficiency/attempts/<identity>/` respectively.
- Schemas, fixtures, tasks, oracles, and protected probes are grouped by
  function under `agent-efficiency/`; preserve them as versioned controls.
- `performance/` and `semantic-pipeline/` keep machine-local manifests out of
  the root while leaving them ignored. Keep generated results under
  `.artifacts/benchmarks/`.
- For runtime output groups, retention decisions, and the completed cache
  cleanup, see [`.artifacts/MANIFEST.md`](../.artifacts/MANIFEST.md) and the
  [retention review](../docs/process/artifact-retention-review-2026-09-27.md).

## Representative agent panel

`agent-efficiency/panels/representative-v1.json` is the editable 24-task bank;
`panels/representative-v1/{fixtures,tasks,oracles}/` and its receipt are generated
by `scripts/generate_agent_efficiency_panel.py`. `synthetic/` contains frozen
small Python, TypeScript and Go inputs. `protected/panel-*/` contains protected
behavior probes and digest provenance. Keep this panel separate from legacy
task/oracle identities. `panels/sentinel-retrieval-v1.json` drives the offline
retrieval evaluator, not paid model execution.

`representative-v1-calibration.json` contains full source-curated answer examples.
`representative-v1-patch-calibration.json` summarizes the 18 applied patch checks
without local paths. Reproduce them with
`scripts/calibrate_agent_efficiency_panel.py`; retain complete traces under
the image qualification record. Campaign specs 010 and 011 select the same
panel through OpenRouter and native subscription routes respectively. See the
[preparation report](../docs/process/agent-efficiency-campaign-preparation-2026-10-02.md).
