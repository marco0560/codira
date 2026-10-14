# Stress r1 follow-up: newly observed failures

Date: 2026-10-14. This is a live campaign snapshot, not final campaign results.
Source: primary checkout `.artifacts/benchmarks/test-material/local-stress/local-stress-20261010-r1/`.
The campaign still uses `3ee9cd9`; the seven completed findings commits are isolated
on `fix/stress-benchmark-findings` and have not altered its runtime.

## Review boundary and results

The retained coverage replay proves review through zero-based summary position
615, `duckdb-onnx-exact/json-schemastore/mcp`. To avoid gaps, positions 535–615
were also checked. The new tail contains 876 outcomes after that boundary;
the snapshot has 1,492 checkpointed outcomes, ending at
`sqlite-onnx-faiss-flat/json-schemastore/mcp`. Seven newer LLVM setup/structural
receipts exist outside the summary checkpoint; they contain no new command error.

| Tail status | Count |
| --- | ---: |
| passed | 246 |
| partial | 402 |
| partial_empty | 102 |
| excluded | 102 |
| failed | 24 |

All 24 failures are embedding population: both Sentence Transformers profiles,
12 repositories each. Ninety-six exclusions are their dependent context/semantic
measurements; six exclusions preserve unchanged deterministic fixture failures.
No additional command-error signature or MCP tool error was found in the tail.
The only failed structural source paths remain LLVM's encoding fixture and
CPython's three malformed tokenization fixtures. Fourteen SVG omissions now exist,
all at the old 60-second limit; they are covered by the existing rendering fix.
Coverage-label mismatches and silent omissions remain expected in this old runner;
the isolated fixes do not retroactively change this campaign's evidence.

## Uncovered causes

1. **Model cache resolution.** BGE exists in the legacy Hugging Face snapshot
   `~/.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5/snapshots/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a/`.
   Inspection found weights, tokenizer and model/pooling configuration with no
   broken snapshot symlinks. Codira instead supplies the explicit cache folder
   `~/.cache/codira/models/sentence-transformers`, which contains MiniLM but no BGE.
   The ST profiles use a Hub model ID without an explicit artifact location.
   ONNX profiles have working explicit ONNX/tokenizer paths. Presence of the ONNX
   export alone would not satisfy the PyTorch ST loader. No model was instantiated
   or downloaded in this investigation; native offline loading must still be tested.
2. **Offline and admission policy.** The runner sets offline environment flags,
   but `_load_model` catches a local miss and provisions automatically.
   `_configure_embedding_environment(offline=False)` rewrites those flags to zero.
   This permits online provisioning despite the campaign's offline setting; the
   observed provisioning fails. Admission never verified all engine-specific
   prerequisites, so the same environmental failure was measured 24 times.
3. **Profiling control lost by sanitation.** The corrected runner still strips
   every inherited `CODIRA_*` variable, including `CODIRA_EMBEDDING_PROFILE_DIR`
   used in its new documentation and `CODIRA_MODEL_ROOT`. Backend profiling works,
   but the documented environment-prefixed campaign launch does not pass its
   directory to children. This gap was not covered by the seven existing fixes.

## Proposed implementation: three separate commits

1. **Offline model resolution and policy:** support an explicit pinned local ST
   artifact while retaining logical model identity, respect explicit model-root
   overrides, and provide a controlled legacy-cache adoption/resolution path.
   Honor strict offline settings without automatic network provisioning; report
   the selected cache/artifact and actionable remediation. Test legacy cached BGE,
   explicit roots, missing artifacts, dimensions/revision identity and zero
   network attempts under strict offline conditions. Keep provisioning explicit.
2. **Runner model admission:** resolve and verify each selected engine's actual
   artifacts once before repository workloads. Record pinned revision/file hashes
   and engine-specific readiness; reject a campaign whose required profiles are
   unavailable before measuring expensive indexes. Tests must distinguish valid
   local ONNX assets from valid ST assets, use the child environment, and ensure
   unavailable prerequisites never become misleading repository failures. Preserve
   these 24 original failures. A corrected plan gets a new identity; do not patch
   the running r1 campaign or retry it silently.
3. **Runner profiling propagation:** carry a validated explicit profiling control
   through sanitation, assign unique stage/attempt journal directories and link
   journals from receipts. Preserve workspace/config isolation rather than
   forwarding arbitrary `CODIRA_*` overrides. Test both suites, child propagation,
   retained checkpoints, interrupted attempts and journal ownership. Update the
   documented command and identity controls to match implementation.

Run focused regression tests, repository quality preflight and the required full
gate in the same isolated findings worktree. No benchmark campaign is authorized
by this analysis. An operator-run new identity is needed to qualify real model
readiness and end-to-end timing after fixes. The running LLVM ONNX/FAISS population
was observed alive at roughly six CPU cores; its elapsed time alone does not
establish a stall. Existing checkpoint/profile fixes address that investigation.

Ignored evidence receipt: `.artifacts/analysis/local-stress-r1-followup-20261014/analysis-receipt.json`.
The running summary changes over time; the receipt freezes its digest, cutoff,
counts and original failure-output digests. No campaign files or processes changed.


## Implementation ledger

| Point | State | Evidence |
| --- | --- | --- |
| 1: offline model resolution | Implemented; 28 focused tests and quality preflight pass | Native offline BGE snapshot load and one fixed-text encoding: 384 dimensions, norm approximately 1 |
| 2: runner model admission | Pending | Required before repository workloads |
| 3: profiling propagation | Pending | Stage/attempt ownership and child-environment regressions required |

Point 1 adds `plugins.embedding-sentence-transformers.model_path`, reuses an
existing legacy cache only without an explicit model root, and respects strict
offline flags without automatic provisioning. The logical model ID remains
separate from the artifact path; operators pin `embeddings.version` to the
immutable snapshot revision. ST distribution 2.0.1/implementation 1.0.3, bundle
2.0.14 and installer 2.0.2 carry aligned pins and regenerated catalog metadata.
Ignored validation evidence is under
`.artifacts/validation/stress-followup-20261014/`. This native check is model
readiness, not a campaign comparison or retrieval-quality grade.
