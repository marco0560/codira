# Semantic Pipeline Optimization Plan

## Purpose

Implement and validate the remaining high-value semantic indexing
optimizations:

1. less fragmented Markdown and plain-text documentation chunking;
2. richer embedding eligibility filters;
3. complete incremental invalidation for semantic policy changes;
4. manual garbage collection of unused payloads in the active vector set;
5. token- and memory-bounded adaptive embedding batches.

This is an implementation plan, not an exploratory design document. Follow it
phase by phase. Do not merge the work into `main` until the blocking CPU
performance and retrieval-quality campaign in Phase 8 passes.

## Accepted decisions

The following decisions are final for this workstream.

- Apply new chunking only to `documentation` artifacts produced by the
  Markdown and plain-text analyzers.
- Keep symbol payload generation unchanged.
- Change analyzer artifacts directly. Do not introduce a separate embedding
  chunk entity or many-to-many artifact/chunk schema.
- Put the deterministic chunking algorithm in a shared core utility and call
  it from both analyzers.
- Make the selected chunking policy the new default.
- Do not retain a legacy chunking mode.
- Select final chunk sizes through the bounded campaign defined below.
- Add glob-aware filters while preserving the prefix meaning of existing
  values.
- Add optional per-object-type rules for `symbol` and `documentation`.
- Do not add `kind` or `source_format` filtering in this workstream.
- Persist canonical semantic policies and their fingerprints.
- Reanalyze only files potentially affected by a changed policy.
- Reuse every still-valid vector through `content_hash`.
- Add manual active-set garbage collection as `codira emb purge --unused`.
- Keep compaction explicit through `--compact`.
- Do not run automatic garbage collection after indexing.
- Use deterministic static token/byte budgets plus batch-halving retry for
  recognized out-of-memory failures.
- Do not sample RAM or VRAM continuously during indexing.
- Keep `codira calibrate embeddings` as the explicit way to write
  hardware-specific configuration.
- Validate the implementation and blocking performance campaign on CPU first.
- Implement GPU-compatible behavior and unit tests now, but treat a real GPU
  campaign as a later hardware gate. Do not claim measured GPU performance
  before that gate runs.

## Branch and integration policy

Create one independent branch from an up-to-date `main`:

```bash
git switch main
git pull --ff-only
BASE_SHA=$(git rev-parse HEAD)
git switch -c perf/semantic-pipeline-optimization
```

Record `BASE_SHA` in the execution ledger embedded below. All
implementation, benchmark harness changes, measurements, and the final report
belong on this branch.

Rules:

- do not implement this plan directly on `main`;
- do not mix unrelated fixes into the branch;
- create at least one validated commit at the end of every phase;
- keep raw machine-local artifacts under `.artifacts/`;
- commit the final human-readable comparison report under `docs/process/`;
- do not merge until every blocking acceptance gate passes;
- if a blocking gate fails, keep the branch independent, document the failure,
  and either optimize further or revert the responsible phase;
- rebase or merge the current `main` into the branch before the final campaign,
  then rerun the complete campaign if the rebase changes relevant code.

## Execution ledger

This ledger is the authoritative progress record for the workstream. Update it
in the same commit that completes or changes an activity. Do not mark an item
complete merely because code was written: its phase validation and required
evidence must also exist.

### Ledger conventions

- Use `[ ]` for not started, `[-]` for in progress, `[x]` for completed, and
  `[!]` for blocked or failed.
- A phase is complete only when every required item is `[x]`, its stop
  condition is clear, and the validation command has passed.
- Record immutable identifiers: commit SHA, artifact path, manifest checksum,
  dataset checksum, and report path. Do not use only branch-relative links.
- Store raw measurements below `.artifacts/`; commit concise results and
  conclusions in this file or the Phase 8 report.
- If an activity is not applicable, mark it `[x]` and explain why in the
  decision log. Do not silently omit it.
- Append entries to logs; do not rewrite historical failures or decisions.

### Workstream identity

| Field | Value |
| --- | --- |
| Branch | `perf/semantic-pipeline-optimization` |
| Base SHA | `TBD` |
| Current candidate SHA | `TBD` |
| Started at | `TBD` |
| Last ledger update | `TBD` |
| Implementer | `TBD` |
| Baseline artifact directory | `TBD` |
| Candidate artifact directory | `TBD` |
| Final report | `docs/process/semantic-pipeline-optimization-results.md` |
| Overall status | `[ ] Not started` |
| Merge recommendation | `TBD` |

### Phase summary

| Phase | Deliverable | Status | Commit SHA | Evidence |
| ---: | --- | --- | --- | --- |
| 0 | Branch and reproducible baseline | `[ ]` | `TBD` | `TBD` |
| 1 | Metrics and policy models | `[ ]` | `TBD` | `TBD` |
| 2 | Shared documentation chunker | `[ ]` | `TBD` | `TBD` |
| 3 | Glob-aware and per-type filters | `[ ]` | `TBD` | `TBD` |
| 4 | Incremental semantic invalidation | `[ ]` | `TBD` | `TBD` |
| 5 | Unused-payload garbage collection | `[ ]` | `TBD` | `TBD` |
| 6 | Token- and byte-bounded batching | `[ ]` | `TBD` | `TBD` |
| 7 | Integration, documentation, versions | `[ ]` | `TBD` | `TBD` |
| 8 | Blocking performance and quality campaign | `[ ]` | `TBD` | `TBD` |
| 9 | Integration gate | `[ ]` | `TBD` | `TBD` |

### Phase 0 checklist

- [ ] Create the branch from an up-to-date `main`.
- [ ] Record `BASE_SHA` before the first implementation change.
- [ ] Record software, hardware, model, and operating-system versions.
- [ ] Freeze and checksum repository manifests and quality datasets.
- [ ] Run focused baseline validation.
- [ ] Run the one-iteration campaign preflight.
- [ ] Run the full blocking baseline campaign.
- [ ] Preserve raw baseline artifacts under a timestamped directory.
- [ ] Record the Phase 0 commit and evidence in the summary table.

### Phase 1 checklist

- [ ] Add the required indexing, chunking, cache, and batch metrics.
- [ ] Add canonical policy models and deterministic serialization.
- [ ] Add semantic and operational policy fingerprint separation.
- [ ] Preserve optional compatibility for third-party engines.
- [ ] Add and pass focused unit tests.
- [ ] Run the Phase 1 validation commands.
- [ ] Record the Phase 1 commit and evidence in the summary table.

### Phase 2 checklist

- [ ] Implement the shared deterministic documentation chunker.
- [ ] Integrate it into Markdown and plain-text analyzers only.
- [ ] Preserve heading hierarchy and deterministic stable identities.
- [ ] Add analyzer configuration and validation.
- [ ] Run every chunking candidate in the bounded selection campaign.
- [ ] Select and document the measured winning defaults.
- [ ] Bump affected analyzer versions.
- [ ] Add and pass focused and regression tests.
- [ ] Run the Phase 2 validation commands.
- [ ] Record the Phase 2 commit or commits and evidence.

### Phase 3 checklist

- [ ] Implement repo-relative POSIX glob matching.
- [ ] Preserve prefix semantics for existing non-glob configuration.
- [ ] Add optional `symbol` and `documentation` rule tables.
- [ ] Apply global rules before type-specific rules.
- [ ] Add exclusion counters by reason.
- [ ] Verify deferred and immediate eligibility parity.
- [ ] Add and pass SQLite and DuckDB parity tests.
- [ ] Run the Phase 3 validation commands.
- [ ] Record the Phase 3 commit and evidence in the summary table.

### Phase 4 checklist

- [ ] Persist canonical semantic policies and fingerprints.
- [ ] Keep operational batching settings outside semantic fingerprints.
- [ ] Reanalyze only the smallest safe affected file set.
- [ ] Remove stale bindings and pending rows after policy restriction.
- [ ] Materialize newly eligible rows after policy expansion.
- [ ] Reuse valid cached vectors by `content_hash`.
- [ ] Verify zero inference when every required hash is cached.
- [ ] Add migration and compatibility tests for both backends.
- [ ] Run the Phase 4 validation commands.
- [ ] Record the Phase 4 commit and evidence in the summary table.

### Phase 5 checklist

- [ ] Add active-set unused-payload reporting to the vector-store contract.
- [ ] Implement exact unused-payload discovery in SQLite and DuckDB.
- [ ] Add `codira emb purge --unused` dry-run behavior.
- [ ] Add confirmed deletion through `--unused --yes`.
- [ ] Add explicit backend compaction through `--compact`.
- [ ] Count materialized and pending references correctly.
- [ ] Verify exact before/after counts and retrieval-result equality.
- [ ] Add and pass backend, CLI, and failure-atomicity tests.
- [ ] Run the Phase 5 validation commands.
- [ ] Record the Phase 5 commit and evidence in the summary table.

### Phase 6 checklist

- [ ] Add deterministic token-budgeted engine batching.
- [ ] Add byte-budgeted backend work segments.
- [ ] Add recognized-OOM classification and halving retry.
- [ ] Make single-input OOM terminal and explicit.
- [ ] Avoid retaining materialized vectors longer than necessary.
- [ ] Expose invocation, token, segment, truncation, and retry metrics.
- [ ] Verify CPU behavior for ONNX and SentenceTransformers.
- [ ] Add GPU-compatible unit tests without claiming GPU measurements.
- [ ] Verify SQLite and DuckDB parity.
- [ ] Run the Phase 6 validation commands.
- [ ] Record the Phase 6 commit and evidence in the summary table.

### Phase 7 checklist

- [ ] Integrate metrics in human-readable and JSON reports.
- [ ] Update configuration examples and reference documentation.
- [ ] Update CLI documentation for filters and garbage collection.
- [ ] Update release notes and affected package versions.
- [ ] Confirm package and lockfile coherence.
- [ ] Run focused integration tests and full repository validation.
- [ ] Record the Phase 7 commit and evidence in the summary table.

### Phase 8 checklist

- [ ] Bring the branch current with `main`.
- [ ] Record the final candidate SHA before measurement.
- [ ] Recreate isolated baseline and candidate worktrees.
- [ ] Verify identical environment, models, manifests, and datasets.
- [ ] Run the complete CPU baseline campaign against `BASE_SHA`.
- [ ] Run the complete CPU candidate campaign.
- [ ] Compare performance, peak RSS, volume, and retrieval quality.
- [ ] Verify policy invalidation and cache-reuse gates.
- [ ] Verify garbage-collection counts and retrieval equality.
- [ ] Mark every blocking gate `PASS` or `FAIL`.
- [ ] Write `semantic-pipeline-optimization-results.md`.
- [ ] Run full validation after the last code or harness change.
- [ ] Record the Phase 8 commit and evidence in the summary table.

### Phase 9 checklist

- [ ] Confirm every Phase 8 blocking gate is `PASS`.
- [ ] Confirm the branch is current with `main`.
- [ ] Confirm the final working tree is clean.
- [ ] Confirm no unreviewed raw artifact is committed.
- [ ] Confirm documentation and release metadata are complete.
- [ ] Record unresolved limitations and GPU gate status.
- [ ] Make an explicit merge or no-merge recommendation.
- [ ] Record integration PR, merge SHA, or rejection reason.
- [ ] Mark overall status and last ledger update.

### Environment and input record

| Item | Recorded value | Evidence or command |
| --- | --- | --- |
| Python | `TBD` | `python --version` |
| `uv` | `TBD` | `uv --version` |
| Codira | `TBD` | `uv run codira --version` |
| SQLite | `TBD` | `TBD` |
| DuckDB | `TBD` | `TBD` |
| ONNX Runtime | `TBD` | `TBD` |
| Torch | `TBD` | `TBD` |
| SentenceTransformers | `TBD` | `TBD` |
| CPU and logical cores | `TBD` | `TBD` |
| RAM and swap | `TBD` | `TBD` |
| OS and kernel | `TBD` | `TBD` |
| Power governor | `TBD` | `TBD` |
| Embedding models and dimensions | `TBD` | `TBD` |
| Repository manifest SHA-256 | `TBD` | `TBD` |
| Quality dataset SHA-256 | `TBD` | `TBD` |

### Measurement ledger

Add one row per campaign run or meaningful rerun. Use paths relative to the
repository unless evidence lives outside it.

| Time | Variant | SHA | Backend | Engine | Workload | N | Result | Artifact |
| --- | --- | --- | --- | --- | --- | ---: | --- | --- |
| TBD | baseline | TBD | TBD | TBD | TBD | 0 | TBD | TBD |

### Acceptance-gate ledger

| Gate | Baseline | Candidate | Delta | Threshold | Status | Evidence |
| --- | ---: | ---: | ---: | --- | --- | --- |
| Recall@5 | TBD | TBD | TBD | >= -1% rel. | [ ] | TBD |
| MRR@10 | TBD | TBD | TBD | >= -1% rel. | [ ] | TBD |
| Doc embeddings | TBD | TBD | TBD | >= 20% fewer | [ ] | TBD |
| Oversize inputs | TBD | TBD | TBD | zero unaccounted | [ ] | TBD |
| Peak RSS | TBD | TBD | TBD | bounded | [ ] | TBD |
| Cached inference | TBD | TBD | TBD | zero new | [ ] | TBD |
| Backend parity | TBD | TBD | TBD | exact | [ ] | TBD |
| Engine parity | TBD | TBD | TBD | same input set | [ ] | TBD |
| GC retrieval | TBD | TBD | TBD | exact | [ ] | TBD |
| Full validation | TBD | TBD | TBD | all pass | [ ] | TBD |

### Decision and deviation log

Append one row whenever implementation departs from this plan, a placeholder
default is selected, an item is deemed not applicable, or a blocking result is
waived. A blocking acceptance gate may not be waived without explicit human
approval.

| Date | Phase | Decision or deviation | Reason and evidence | Approved by |
| --- | ---: | --- | --- | --- |
| `TBD` | 0 | `TBD` | `TBD` | `TBD` |

### Blocker and failure log

Keep failed attempts because they are useful evidence for later optimization.

| Opened | Closed | Phase | Blocker or failure | Resolution | Evidence |
| --- | --- | ---: | --- | --- | --- |
| `TBD` | `TBD` | 0 | `TBD` | `TBD` | `TBD` |

Suggested comparison setup after implementation:

```bash
git worktree add ../codira-semantic-baseline "$BASE_SHA"
git worktree add ../codira-semantic-candidate \
  perf/semantic-pipeline-optimization
```

Use separate output directories for baseline and candidate runs. Never let the
two worktrees share `.codira/`, model-write, or benchmark result directories.

## Scope

### In scope

- shared documentation chunking;
- Markdown and plain-text analyzer configuration and version bumps;
- embedding path globs and per-object-type eligibility;
- exclusion metrics by reason;
- canonical semantic policy serialization and SHA-256 fingerprints;
- incremental planning after analyzer or semantic policy changes;
- active-vector-set unused-payload reporting and deletion;
- optional backend compaction;
- token-budgeted engine batches;
- byte-budgeted backend work segments;
- recognized-OOM backoff;
- index report and benchmark metrics required by the gates;
- SQLite/DuckDB parity;
- ONNX/SentenceTransformers parity;
- user documentation, release notes, and package version updates.

### Out of scope

- symbol chunking;
- docstring chunking;
- semantic normalization before `content_hash`;
- semantic deduplication of non-identical text;
- a daemon, watcher, or background embedding worker;
- automatic or threshold-triggered garbage collection;
- filters on `kind` or `source_format`;
- persistent automatic rewriting of calibrated batch sizes;
- a Rust rewrite or new native extension;
- changes to embedding model identity or vector similarity ranking.

## Architectural invariants

- Indexing remains explicit, deterministic, and reproducible.
- `embeddings.enabled = false` remains a hard disable.
- Structural objects are retained even when their embedding is ineligible.
- Deferred and immediate modes select the same eligible payload set.
- A policy change may change bindings, pending rows, and produced artifacts,
  but must not silently leave stale active bindings behind.
- Batching parameters are operational and must not invalidate semantic data.
- Chunking and eligibility parameters are semantic and must invalidate the
  smallest safe set of files.
- `content_hash` remains the SHA-256 hash of the exact text sent to the engine.
- Existing third-party embedding engines and vector stores must not be broken
  merely because they do not expose optional metrics.
- SQLite and DuckDB must implement the same observable contract.
- Human and JSON output must agree on counts and mode names.
- Dry runs must not mutate data or compact databases.

## Configuration contract

Use these public names unless repository validation exposes a conflict.

### Analyzer chunking configuration

Add the following options to both
`[plugins.analyzer-markdown]` and `[plugins.analyzer-text]`:

```toml
chunk_min_chars = 300
chunk_target_chars = 1600
chunk_max_chars = 2200
forced_overlap_chars = 120
```

The values above are placeholders until Phase 2 selects one candidate. The
committed defaults must be the measured winner, not automatically these
placeholder values.

Validation:

```text
0 < chunk_min_chars <= chunk_target_chars <= chunk_max_chars
0 <= forced_overlap_chars < chunk_max_chars
forced_overlap_chars <= chunk_min_chars
```

The plugin configuration fingerprint must include all four values.

### Embedding eligibility configuration

Keep the existing global keys:

```toml
[embeddings.indexing]
object_types = ["symbol", "documentation"]
max_text_chars = 0
include_paths = []
exclude_paths = []
```

Add optional per-type tables with the same path and length semantics:

```toml
[embeddings.indexing.symbol]
max_text_chars = 0
include_paths = []
exclude_paths = []

[embeddings.indexing.documentation]
max_text_chars = 0
include_paths = []
exclude_paths = []
```

Rules:

- global rules apply first;
- the matching type-specific rules apply second;
- exclusions win over inclusions at each level;
- `max_text_chars = 0` means unlimited;
- an empty include list includes everything not otherwise excluded;
- existing values without glob metacharacters retain prefix behavior;
- values containing `*`, `?`, or `[...]` use repo-relative POSIX glob
  behavior;
- normalize separators to `/`;
- reject absolute paths, `..` traversal, empty items, and malformed patterns;
- do not resolve symlinks as part of matching.

### Adaptive batching configuration

Add:

```toml
[embeddings]
max_batch_tokens = 8192

[embeddings.indexing]
max_work_batch_bytes = 16777216
```

Semantics:

- `batch_size` remains the maximum input count per engine invocation;
- `max_batch_tokens` is the maximum summed post-truncation token count for one
  engine invocation;
- `max_work_batch_bytes` is the approximate maximum UTF-8 text and row-metadata
  size retained by one backend work segment;
- all limits are upper bounds, not targets;
- an individual item larger than a budget is processed alone after the normal
  tokenizer/model maximum is applied;
- batching keys are operational and excluded from semantic policy
  fingerprints;
- profiles and calibration may override the values explicitly.

If measurement shows that `8192` or `16777216` is unsafe or materially slower,
change the default in Phase 7 and record the evidence. Do not silently derive
hardware-specific values at runtime.

## Required metrics

Extend `EmbeddingIndexingMetrics` or add a narrowly scoped companion model so
the index JSON report and campaign can record:

- candidate rows;
- accepted rows;
- skipped rows in total;
- skipped disabled object type;
- skipped global include miss;
- skipped global exclusion;
- skipped type-specific include miss;
- skipped type-specific exclusion;
- skipped global text limit;
- skipped type-specific text limit;
- pending rows;
- cache hits;
- cache misses;
- unique texts sent to inference;
- engine invocation count;
- input rows per invocation: minimum, maximum, mean, and p95;
- tokens per invocation: minimum, maximum, mean, and p95 when available;
- work-segment bytes: maximum and mean;
- recognized OOM retries;
- smallest successful retry batch;
- inputs truncated by the engine safety limit;
- documentation artifact count;
- documentation character-size distribution;
- forced chunk splits;
- forced-overlap characters introduced.

Do not make optional engine metrics a mandatory third-party plugin contract.
Use a runtime-checkable optional protocol or an equivalent optional capability.
When metrics are unavailable, emit `null` or an explicit availability flag,
not a fabricated zero.

## Phase 0: branch, ledger, and reproducible baseline

### Phase 0 goal

Create the independent workstream and capture a baseline before behavior
changes.

### Phase 0 files

- update the execution ledger embedded in this document;
- optionally copy the ledger to
  `docs/process/semantic-pipeline-optimization-execution.md` if an external
  workflow requires a standalone tracker, but do not maintain two divergent
  authoritative copies;
- add a committed example campaign manifest if the current harness cannot
  express this plan;
- keep actual local repository paths in an ignored `.local.json` manifest.

### Phase 0 actions

1. Create `perf/semantic-pipeline-optimization` as specified above.
2. Update the embedded execution ledger and record:
   - `BASE_SHA`;
   - branch name;
   - Python, `uv`, Codira, SQLite, DuckDB, ONNX Runtime, Torch, and
     SentenceTransformers versions;
   - CPU model, logical core count, RAM, swap, OS, and kernel;
   - active power governor;
   - model identities and dimensions;
   - repository manifest checksum;
   - quality dataset checksum.
3. Run the focused repository validation before changing code.
4. Run a one-iteration preflight campaign.
5. Run and preserve the blocking baseline campaign with the same commands
   defined for Phase 8.
6. Store raw results below a timestamped directory such as:

   ```text
   .artifacts/semantic-pipeline-campaign/baseline-<timestamp>/
   ```

7. Do not reuse a pre-existing index for a cold/full-index measurement.

### Minimum baseline workloads

For each selected repository:

- cold full index;
- warm no-change index;
- one-file documentation change;
- one-file source-code change;
- deferred full index plus `--embeddings-only`;
- retrieval-quality queries for `emb`, `docs`, and `ctx`;
- active vector-store size and payload/binding/pending counts.

Run both structural backends and both first-party embedding engines on CPU.
Use `RUNS=5` and `WARMUP=1` where the current harness supports repeated
measurements. A one-run preflight is not baseline evidence.

### Phase 0 validation

```bash
uv run pytest -q \
  tests/test_retrieval_quality_benchmark.py \
  tests/test_bootstrap_scripts.py
uv run python scripts/validate_repo.py
```

### Phase 0 stop condition

Stop if the baseline cannot be reproduced, if model artifacts differ between
runs, or if the dataset/manifests are not immutable during comparison. Fix the
harness before implementation.

### Phase 0 suggested commit

```text
test(benchmarks): establish semantic pipeline baseline
```

## Phase 1: metrics and policy models

### Phase 1 goal

Add measurement and canonical policy primitives before changing behavior.

### Phase 1 primary files

- `src/codira/contracts.py`
- `src/codira/config.py`
- `src/codira/indexer.py`
- `src/codira/plugin_config.py`
- `src/codira/semantic/embeddings.py`
- `tests/test_config.py`
- `tests/test_contracts.py`
- `tests/test_embeddings.py`
- `tests/test_incremental_indexing.py`

### Phase 1 implementation

1. Replace the single skipped counter with reasoned counters while preserving
   the existing total.
2. Add immutable canonical models for:
   - artifact-production policy;
   - embedding-eligibility policy;
   - operational batching policy.
3. Serialize semantic policies with:
   - sorted mapping keys;
   - stable list order after normalization;
   - compact UTF-8 JSON;
   - no machine-local paths;
   - no batching/thread/device values.
4. Compute SHA-256 over the canonical UTF-8 JSON.
5. Add unit tests proving:
   - equivalent policies produce identical canonical JSON and fingerprints;
   - semantic changes alter the appropriate fingerprint;
   - batching, threads, and device changes alter neither semantic
     fingerprint;
   - normalization is deterministic on Windows-style separators.
6. Add optional runtime embedding metrics without requiring third-party
   plugins to implement them.
7. Include metrics in `IndexReport`, text output where useful, and JSON output.
8. Bump the relevant JSON schema version only if the repository contract
   requires it, and update schema tests in the same commit.

### Phase 1 validation

```bash
uv run pytest -q \
  tests/test_config.py \
  tests/test_contracts.py \
  tests/test_embeddings.py \
  tests/test_incremental_indexing.py
uv run ruff check src/codira tests
uv run ruff format --check src/codira tests
```

### Phase 1 stop condition

Do not begin chunking while counters or fingerprints depend on dictionary
insertion order, environment paths, active hardware, or unavailable optional
plugin methods.

### Phase 1 suggested commit

```text
feat(embeddings): add semantic policy and batch metrics
```

## Phase 2: shared documentation chunker

### Phase 2 goal

Replace heading-per-artifact and character-window fragmentation with one
deterministic shared chunker for Markdown and plain text.

### Phase 2 primary files

- add `src/codira/documentation_chunking.py`;
- add `tests/test_documentation_chunking.py`;
- update
  `packages/codira-analyzer-markdown/src/codira_analyzer_markdown/__init__.py`;
- update
  `packages/codira-analyzer-text/src/codira_analyzer_text/__init__.py`;
- update both analyzer package test files;
- update root plugin defaults and both plugin JSON schemas.

### Shared data model

Create internal immutable models equivalent to:

```python
@dataclass(frozen=True)
class DocumentationChunkingPolicy:
    min_chars: int
    target_chars: int
    max_chars: int
    forced_overlap_chars: int


@dataclass(frozen=True)
class DocumentationUnit:
    text: str
    start_line: int
    end_line: int
    title: str
    heading_path: tuple[str, ...]
    anchor: str


@dataclass(frozen=True)
class DocumentationChunk:
    text: str
    start_line: int
    end_line: int
    title: str
    heading_path: tuple[str, ...]
    anchor: str
    ordinal: int
    forced_split: bool
```

Names may follow repository conventions, but keep responsibilities separate:
analyzers parse source into units; the core utility splits and packs units.

### Deterministic algorithm

1. Normalize line endings but preserve text content otherwise.
2. Remove empty units.
3. For a unit over `max_chars`, split in this order:
   - paragraph boundary;
   - sentence boundary;
   - line boundary;
   - deterministic character cut.
4. Use overlap only for the final forced character-cut case.
5. Never emit a chunk over `max_chars`.
6. Greedily append adjacent pieces while the result is at or below
   `target_chars`.
7. If a chunk remains below `min_chars`, merge it with the next adjacent piece
   when the result is at or below `max_chars`; otherwise leave it unchanged.
8. Preserve source order.
9. For Markdown, retain heading lines in text and carry the common heading
   hierarchy. For a chunk spanning different headings, use their longest
   common heading-path prefix and keep the individual headings in the text.
10. For plain text, use paragraph units and preserve source line ranges.
11. Make `stable_id` depend only on:
    - source-relative path;
    - normalized anchor;
    - source start line;
    - deterministic chunk ordinal.
12. Emit uniform chunk-oriented stable IDs for the new implementation. Do not
    preserve a parallel legacy ID mode.

### Analyzer behavior

- Markdown still strips front matter according to existing configuration.
- Markdown heading-level selection remains effective before chunking.
- Heading-less Markdown and accepted text files use the same shared chunker.
- Text analyzer path eligibility remains unchanged in this phase.
- Bump both analyzer implementation versions.
- Bump package versions according to repository release policy.
- A changed chunking config must change the analyzer configuration fingerprint.

### Candidate selection campaign

Evaluate all valid combinations:

| Parameter | Candidates |
| --- | ---: |
| `min_chars` | 200, 300 |
| `target_chars` | 1200, 1600 |
| `max_chars` | 1800, 2200 |
| `forced_overlap_chars` | 0, 120, 180 |

Use two stages.

#### Stage A: static shortlist

Run all candidates without embedding inference on the selected repositories.
Record chunk count, size distribution, forced splits, overlap, and number of
chunks below `min_chars`.

Reject candidates that:

- emit any chunk over `max_chars`;
- lose non-whitespace source text other than configured front matter;
- reorder source text;
- produce unstable output across two runs;
- fail to reduce documentation chunks by at least 20% on qualifying
  fragmented-Markdown repositories.

A repository qualifies as fragmented when the baseline has at least 20
Markdown documentation artifacts and at least 30% contain fewer than 300
characters.

Keep at most four Pareto candidates, preferring:

1. fewer forced splits;
2. fewer sub-minimum chunks;
3. fewer total chunks;
4. less overlap;
5. smaller `max_chars`.

#### Stage B: inference and quality

Run the shortlisted candidates through the same model, engine, backend, query
dataset, and hardware used for the baseline.

Reject any candidate whose aggregate `Recall@5` or `MRR@10` decreases by more
than 1% relative to baseline.

Among passing candidates choose, in order:

1. lowest median documentation embedding time;
2. lowest peak process-tree RSS;
3. highest `MRR@10`;
4. fewest documentation embeddings;
5. lexicographically smallest parameter tuple.

Commit the selected values as defaults and record the full table in the
execution ledger.

### Phase 2 required tests

- headings inside fenced code blocks remain ignored;
- front matter behavior is unchanged;
- duplicate and Unicode headings produce deterministic IDs;
- short adjacent units merge deterministically;
- unrelated source order is never changed;
- long paragraphs split below the maximum;
- sentence and line boundaries are preferred to character cuts;
- overlap appears only after forced character cuts;
- no empty chunks;
- no output over the maximum;
- line ranges cover the emitted text correctly;
- two runs produce byte-identical artifacts;
- configuration validation rejects inconsistent limits;
- analyzer version changes force affected Markdown/text files to reindex;
- symbol artifacts and symbol embedding payloads are unchanged.

### Phase 2 validation

```bash
uv run pytest -q \
  tests/test_documentation_chunking.py \
  packages/codira-analyzer-markdown/tests/test_markdown_package.py \
  packages/codira-analyzer-text/tests/test_text_package.py \
  tests/test_incremental_indexing.py
uv run python scripts/validate_repo.py
```

### Phase 2 stop condition

Stop if no candidate satisfies both the 20% reduction and quality gates.
Retain the measurements, revise the algorithm on the branch, and rerun both
stages. Do not weaken the quality gate to select a winner.

### Phase 2 suggested commits

```text
feat(documentation): add deterministic shared chunking
test(benchmarks): select documentation chunk defaults
```

## Phase 3: glob-aware and per-type embedding filters

### Phase 3 goal

Extend the existing useful filters without changing their current prefix
meaning.

### Phase 3 primary files

- `src/codira/config.py`
- `src/codira/contracts.py`
- `src/codira/indexer.py`
- `tests/test_config.py`
- `tests/test_contracts.py`
- `tests/test_incremental_indexing.py`
- both backend embedding-policy tests
- `docs/configuration.md`

### Phase 3 implementation

1. Add a typed per-object policy model.
2. Replace `_embedding_path_matches` with a helper that distinguishes:
   - literal prefix;
   - glob include match;
   - glob exclude match.
3. Keep matching repo-relative and POSIX-normalized.
4. Apply global path rules before per-type rules.
5. Evaluate row-specific rules after the path-owning file is known.
6. Count exactly one terminal exclusion reason per candidate row using this
   order:
   - disabled object type;
   - global include miss;
   - global exclusion;
   - type include miss;
   - type exclusion;
   - global text limit;
   - type text limit.
7. Preserve the existing total `skipped` counter as the sum of reasoned
   counters.
8. Ensure deferred and immediate modes use the same filtering function.
9. Preserve structural objects for skipped rows.

### Phase 3 required tests

- old prefix examples behave exactly as before;
- `docs/**/*.md` and `src/**/generated/*` behave as globs;
- backslashes normalize to `/`;
- excludes win over includes;
- per-type documentation rules do not affect symbols and vice versa;
- empty per-type tables inherit only the global restrictions;
- every skipped row increments one reason and the total once;
- SQLite and DuckDB accept identical rows;
- immediate and deferred modes produce identical eligible stable IDs;
- invalid absolute/traversal patterns fail configuration validation.

### Phase 3 validation

```bash
uv run pytest -q \
  tests/test_config.py \
  tests/test_contracts.py \
  tests/test_incremental_indexing.py \
  packages/codira-backend-sqlite/tests/test_sqlite_backend_package.py \
  packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py
```

### Phase 3 stop condition

Stop if compatibility tests show any previously valid literal prefix changing
meaning. Fix matching semantics instead of documenting a breaking change.

### Phase 3 suggested commit

```text
feat(embeddings): extend indexing eligibility filters
```

## Phase 4: complete incremental semantic invalidation

### Phase 4 goal

Make artifact and eligibility policy changes update exactly the potentially
affected files while preserving vector reuse.

### Phase 4 primary files

- `src/codira/contracts.py`
- `src/codira/indexer.py`
- structural backend schemas and persistence adapters;
- `tests/test_incremental_indexing.py`;
- backend contract and parity tests.

### Persisted state

Persist, for the last successful index:

- canonical artifact-production policy JSON;
- artifact-production SHA-256 fingerprint;
- canonical eligibility policy JSON;
- eligibility SHA-256 fingerprint.

Operational batching settings must not be persisted in these fields.

Use the repository current-schema-only policy:

- update SQLite and DuckDB physical schemas;
- bump each backend schema version as required;
- update schema expectations and package versions;
- do not add a long-lived migration layer unless existing repository policy
  explicitly requires it.

### Planning behavior

1. Load previous canonical policies and fingerprints with existing file hashes,
   file ownership, and analyzer inventory.
2. If persisted policy is missing or malformed, safely reindex all current
   files once.
3. Detect analyzers whose version or configuration fingerprint changed.
4. Reindex every file owned by a changed analyzer.
5. When only eligibility policy changes:
   - compare old and new canonical policies;
   - select the union of paths allowed by either old or new global path policy;
   - include paths whose selected object type could have changed because of
     object-type, per-type path, or length changes;
   - do not reanalyze files that are provably disallowed by both policies.
6. When only operational batching changes, reuse every unchanged file.
7. Before writing new rows for an affected file, remove its obsolete
   materialized bindings and pending rows.
8. Recreate eligible associations.
9. Resolve every required `content_hash` through the persistent vector cache
   before inference.
10. Persist the new policy only after a successful index commit.
11. On abort, preserve the previous policy and index state.

If proving that a file is unaffected would require reconstructing unavailable
old analyzer output, reindex that file. Prefer a safe extra parse over a stale
semantic index.

### Required scenarios

Test each scenario on SQLite and DuckDB:

1. add `documentation` to `object_types`;
2. remove `documentation` from `object_types`;
3. widen and narrow a global include;
4. add and remove a global exclusion;
5. change a documentation-only path rule;
6. raise and lower global and type-specific text limits;
7. change Markdown chunk sizes;
8. change only `batch_size`;
9. change only `max_batch_tokens`;
10. change only `max_work_batch_bytes`;
11. abort an index after planning but before commit;
12. load an index created before semantic fingerprints exist.

Assertions:

- decisions explain `semantic artifact policy changed` or
  `embedding eligibility policy changed`;
- only potentially affected files are indexed;
- stale bindings and pending rows disappear;
- unchanged hashes are cache hits;
- when all required hashes are cached, inference receives zero texts;
- batching-only changes cause zero reanalysis and zero inference;
- failed runs do not persist new fingerprints.

### Phase 4 validation

```bash
uv run pytest -q \
  tests/test_contracts.py \
  tests/test_incremental_indexing.py \
  packages/codira-backend-sqlite/tests/test_sqlite_backend_package.py \
  packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py
uv run python scripts/validate_repo.py
```

### Phase 4 stop condition

Do not continue if a restrictive policy leaves an old active binding or if
fingerprints are updated before a successful transaction commit.

### Phase 4 suggested commit

```text
fix(index): invalidate changed semantic policies
```

## Phase 5: active vector-set unused-payload garbage collection

### Phase 5 goal

Delete cached payloads that are no longer referenced inside the active vector
set, without changing search results.

### CLI contract

Support:

```text
codira emb purge --unused
codira emb purge --unused --dry-run
codira emb purge --unused --yes
codira emb purge --unused --yes --compact
```

`--stale`, `--all`, and `--unused` are mutually exclusive.

Rules:

- no `--yes` means dry run, consistent with the existing command;
- `--older-than` and `--keep` remain valid only with `--stale`;
- `--compact` requires an executing purge with `--yes`;
- reject `--compact` with an effective dry run;
- no automatic purge occurs during indexing;
- an active payload is used when its `content_hash` is referenced by either a
  materialized binding/vector or a pending row in the same vector set;
- delete all unused active-set payloads without age retention;
- never delete a binding, materialized vector, or pending row in unused mode;
- compaction is backend-specific and its limitations must be reported.

### Contract changes

Extend `VectorStorePurgeRequest` and `VectorStorePurgeResult` without
overloading unrelated counters:

- represent mode explicitly as `stale`, `all`, or `unused`;
- include selected/deleted unused payload count;
- include whether compaction was requested and performed;
- preserve existing JSON fields for compatibility where possible.

### SQLite implementation

For the active vector set:

1. select `vector_payloads` rows whose `content_hash` appears in neither
   `vector_bindings` nor `pending_vectors`;
2. in dry run, report exact rows without mutation;
3. on execution, delete corresponding rows from the sqlite-vec payload table
   and `vector_payloads` in one safe transaction;
4. when `--compact` is requested, commit deletion first and run `VACUUM`
   outside the transaction;
5. report size before and after.

### DuckDB implementation

For the active vector set:

1. select `vector_cache` rows whose `content_hash` appears in neither
   `vectors` nor `pending_vectors`;
2. report or delete only those cache rows;
3. retain existing materialized vectors and pending rows;
4. run the backend-supported explicit checkpoint/compaction path only when
   `--compact` is requested;
5. do not promise file shrink when the backend does not guarantee it;
6. report size before and after.

### Phase 5 required tests

- exact dry-run counts;
- dry run produces byte-identical database contents;
- one payload shared by two bindings is retained;
- a payload referenced only by pending work is retained;
- an unreferenced payload is deleted;
- materialized and pending row counts are unchanged;
- search results and scores before/after are identical;
- repeated unused purge is idempotent;
- `--compact` validation is correct;
- SQLite/DuckDB JSON output has parity;
- stale/all behavior remains unchanged.

### Phase 5 validation

```bash
uv run pytest -q \
  tests/test_embeddings.py \
  tests/test_prefix_filtering.py
uv run pytest -q \
  packages/codira-vector-store-sqlite/tests/test_sqlite_vector_store_package.py
uv run pytest -q \
  packages/codira-vector-store-duckdb/tests/test_duckdb_vector_store_package.py
```

### Phase 5 stop condition

Stop on any search-result change, live payload deletion, or disagreement
between dry-run and execution counts.

### Phase 5 suggested commit

```text
feat(embeddings): purge unused active vector payloads
```

## Phase 6: token- and byte-bounded adaptive batching

### Phase 6 goal

Bound memory with deterministic input packing and recover from recognized OOM
failures without hiding unrelated errors.

### Phase 6 primary files

- `src/codira/config.py`
- `src/codira/contracts.py`
- `src/codira/semantic/embeddings.py`
- both first-party embedding engine implementations and tests;
- SQLite and DuckDB embedding flush paths and tests;
- calibration and benchmark scripts.

### Shared batch packer

Add a deterministic helper that preserves input order and packs items under:

- maximum row count;
- maximum summed post-truncation tokens;
- optional maximum estimated bytes.

Required behavior:

- every input appears exactly once before any retry;
- an oversized single input becomes a one-item batch;
- empty inputs preserve existing zero-vector behavior;
- identical inputs preserve existing deduplication behavior;
- output order equals input order;
- no batch exceeds a limit except the documented single-item case.

### ONNX engine

1. Tokenize incrementally so token counts used for packing are exact after
   `max_tokens` truncation.
2. Reuse those encodings for the runtime input feed; do not tokenize the same
   batch twice merely to count tokens.
3. Avoid converting the full attention mask to nested Python lists when
   pooling can consume the array directly.
4. On recognized OOM:
   - split the failing batch in half;
   - retry left then right to preserve order;
   - continue until success or one input remains;
   - re-raise at one input with engine, provider, row count, and token count.
5. Do not classify arbitrary ONNX failures as OOM.

### SentenceTransformers engine

1. Use the loaded model tokenizer to obtain deterministic post-truncation token
   counts.
2. Pack under row and token limits before `model.encode`.
3. Accept the extra token-counting cost only if the campaign gates pass.
4. On recognized `MemoryError`, Torch out-of-memory exception, or an explicitly
   matched allocation error:
   - halve and retry as above;
   - clear only safe runtime caches appropriate to the active device;
   - never swallow an unrelated `RuntimeError`.
5. Preserve text deduplication and returned order.

### Backend work segments

Replace row-count-only slicing with a shared iterator bounded by:

- `batch_size * work_batch_multiplier` rows;
- `max_work_batch_bytes`.

Estimate bytes deterministically from:

- UTF-8 text bytes;
- UTF-8 stable ID and content hash bytes;
- fixed documented row overhead.

Do not include serialized vector bytes before inference. After inference,
flush vectors without retaining completed segments longer than required.

### Backoff policy

- initial batch respects configured limits;
- each retry halves by row count while preserving order;
- retry count is bounded by `ceil(log2(initial_rows))`;
- a single-item OOM is terminal;
- no successful retry is written back to config automatically;
- expose successful and failed batch sizes in metrics;
- calibration remains the only explicit persistent tuning workflow.

### Phase 6 required tests

- packer respects row, token, and byte budgets;
- deterministic batch boundaries;
- one oversized item behavior;
- ONNX encodings are not duplicated for token counting;
- fake OOM succeeds after one and multiple halvings;
- one-item OOM is re-raised with context;
- unrelated runtime failures are not retried;
- output order is preserved across recursive retries;
- CPU behavior is covered;
- CUDA/Torch OOM classification is unit-tested without requiring a GPU;
- work segments flush at the byte boundary on both backends;
- batching-only config changes do not invalidate the index;
- metrics report actual batch and retry behavior.

### Phase 6 validation

```bash
uv run pytest -q \
  tests/test_embeddings.py \
  tests/test_calibration.py \
  packages/codira-backend-sqlite/tests/test_sqlite_backend_package.py \
  packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py
uv run pytest -q \
  packages/codira-embedding-onnx/tests/test_onnx_package.py
uv run pytest -q \
  packages/codira-embedding-sentence-transformers/tests/\
test_sentence_transformers_package.py
uv run python scripts/validate_repo.py
```

### Phase 6 stop condition

Stop if token counting causes a median full-index regression above 3%, if an
unrelated engine error is retried, or if a successful retry changes vector
ordering or count.

### Phase 6 suggested commit

```text
perf(embeddings): bound adaptive inference batches
```

## Phase 7: integrated behavior, documentation, and versions

### Phase 7 goal

Finish user-facing contracts before the blocking campaign.

### Update

- `README.md`
- `docs/configuration.md`
- `docs/scripts.md`
- relevant architecture documentation or ADRs;
- `CHANGELOG.md` according to repository policy;
- capability declarations and JSON schemas;
- analyzer, backend, vector-store, embedding-engine, bundle, and root version
  constraints touched by the work;
- `uv.lock`.

Document:

- new chunking defaults and stable-ID rebuild implication;
- prefix-versus-glob matching;
- per-type filter examples;
- policy invalidation behavior;
- unused-payload GC and its cache-reuse tradeoff;
- dry-run and `--yes` safety;
- compaction limitations;
- token and byte budgets;
- OOM backoff;
- CPU validation status and unmeasured GPU status.

### Full functional validation

```bash
uv run pre-commit run --all-files
uv run pytest -q
uv run python scripts/validate_repo.py
uv run codira index
uv run codira audit
uv run codira caps --json
uv run codira emb purge --unused --dry-run
```

Run all commands from the branch checkout with first-party packages installed
from the working tree, not from older published wheels.

### Phase 7 stop condition

Do not begin the final campaign with a dirty validation surface, stale
editable installs, or undocumented public configuration.

### Phase 7 suggested commit

```text
docs(embeddings): document semantic pipeline controls
```

## Phase 8: blocking pre-merge performance and quality campaign

### Phase 8 goal

Compare `BASE_SHA` and the final branch on the same hardware and decide whether
the branch is eligible for integration.

### Reproducibility rules

- use the baseline and candidate worktrees;
- use the same Python and dependency lock;
- use the same model files and verify checksums;
- use the same repository revisions and dataset;
- run no unrelated high-load jobs;
- record ambient memory and swap before every run;
- randomize or alternate baseline/candidate run order to reduce thermal drift;
- preserve every command, exit status, stdout, stderr, and timing record;
- run a one-iteration preflight before the measured campaign;
- use five measured runs and one warmup for timing comparisons;
- measure process-tree peak RSS, not only the parent Python process;
- report median and dispersion, not only the best run.

### Repository set

Use at least:

- Codira;
- Fontshow;
- Chatops;
- Sanikey;
- one medium repository;
- one large repository already used by the existing benchmark catalog.

The committed manifest must identify labels and expected categories; local
paths remain in the `.local.json` counterpart.

### Matrix

Blocking CPU matrix:

- structural backend: SQLite, DuckDB;
- embedding engine: ONNX, SentenceTransformers;
- device: CPU;
- mode: immediate, deferred plus embeddings-only;
- state: cold full, warm unchanged, partial documentation change, partial
  source change.

Do not multiply every exploratory chunk candidate through the final matrix.
Phase 2 must already have selected one final candidate.

### Quality channels

Run:

- `codira emb`;
- `codira docs`;
- `codira ctx`.

Report at least:

- `Recall@5`;
- `MRR@10`;
- nDCG at the existing benchmark cutoff;
- Hit@10;
- per-repository and aggregate results.

### GC verification workload

1. Build the active vector set.
2. Change documentation so at least one cached hash becomes unused.
3. Reindex.
4. Capture queries and exact scores.
5. Run `--unused --dry-run`.
6. Run `--unused --yes`.
7. Re-run queries and compare exact stable IDs and scores.
8. Run unused purge again and require zero candidates.
9. Run the compact variant separately and report size change without making
   shrinkage a functional gate.

### Incremental-policy workload

For each backend:

1. index with symbols only;
2. enable documentation;
3. verify affected files and cache behavior;
4. narrow documentation paths;
5. verify obsolete bindings disappear;
6. restore the policy;
7. change only batch budgets;
8. require zero reanalysis and zero inference for the final step.

### Blocking acceptance gates

All must pass.

#### Correctness

- complete repository validation is green;
- SQLite/DuckDB and ONNX/SentenceTransformers have functional parity;
- no stale materialized or pending bindings after restrictive policy changes;
- GC leaves retrieval stable IDs and scores unchanged;
- batching retries preserve vector count and order;
- no input exceeds the declared engine limit without an explicit forced split
  or counted truncation.

#### Retrieval quality

- aggregate `Recall@5` decreases by no more than 1% relative;
- aggregate `MRR@10` decreases by no more than 1% relative;
- investigate any repository/channel regression above 3% even if the
  aggregate passes;
- do not average away a complete failure on one repository.

Relative decrease is:

```text
(baseline - candidate) / baseline
```

If a baseline metric is zero, require the candidate to be no worse in absolute
terms and report the case separately.

#### Embedding volume

- at least 20% fewer documentation embeddings on every qualifying fragmented
  Markdown repository;
- no increase in symbol embedding count except where an unrelated corrected
  eligibility bug is explicitly documented;
- cache-hit and cache-miss counts reconcile with inference input counts.

#### Performance

- median cold full-index time must not regress by more than 3% in any primary
  backend/engine aggregate;
- at least one fragmented-documentation workload must improve median
  documentation embedding time by 15% or more;
- warm unchanged indexing must not regress by more than 5%;
- policy-only reindex with fully cached hashes must execute zero inference;
- candidate run must complete without OOM.

#### Memory

- on stress workloads whose baseline peak process-tree RSS is at least 4 GiB,
  candidate peak RSS must fall by at least 20%;
- below 4 GiB baseline RSS, candidate peak RSS must not regress by more than
  5%;
- swap growth during a candidate measured run must not exceed 256 MiB;
- no unbounded growth across consecutive work segments;
- report maximum work-segment bytes and maximum engine batch tokens.

If the operating system or measurement tool cannot produce reliable
process-tree RSS and swap deltas, the campaign is incomplete rather than
passed.

### Selection and rollback rules

- If quality fails, revisit chunking before batching.
- If volume passes but time fails, profile token counting and serialization.
- If memory fails, reduce byte/token defaults and rerun the full matrix.
- If only one backend fails, fix backend parity; do not exclude it.
- If GC fails, revert or repair Phase 5 without weakening invariants.
- If a batching engine fails, keep the branch unmerged; do not silently
  disable adaptive behavior for that engine.

### Final report

Add:

```text
docs/process/semantic-pipeline-optimization-results.md
```

Include:

- base and candidate SHAs;
- environment and checksums;
- exact commands;
- selected chunking candidate and rejected candidates;
- metric tables by repository/backend/engine;
- quality deltas;
- timing and RSS deltas;
- policy invalidation evidence;
- GC counts and retrieval equality;
- every acceptance gate with `PASS` or `FAIL`;
- known limitations;
- GPU gate status;
- explicit merge recommendation.

### Phase 8 suggested commit

```text
test(benchmarks): validate semantic pipeline optimizations
```

## Phase 9: integration gate

### Preconditions

- Phase 8 report says `PASS` for every blocking gate.
- Branch is current with `main`.
- Full validation was rerun after the last code change.
- Working tree is clean.
- Package versions and lockfile are coherent.
- Commit messages satisfy repository hooks.
- Raw artifacts are archived outside Git or retained under the repository
  artifact policy.

### Final commands

```bash
uv run pre-commit run --all-files
uv run pytest -q
uv run python scripts/validate_repo.py
uv run codira index
uv run codira audit
git status --short
```

Use the repository commit-block workflow for the final commit and PR. The PR
must link the final report and state that the real GPU campaign remains a later
hardware validation gate when applicable.

Do not merge automatically as part of executing this plan. Prepare the branch
and evidence, then request the repository owner's explicit merge decision.

## GPU follow-up gate

Run after suitable GPU hardware is available and before making measured GPU
performance claims.

Use the same candidate SHA and:

- record GPU model, VRAM, driver, CUDA, Torch, provider, and power limit;
- run ONNX and SentenceTransformers GPU-capable configurations where
  supported;
- force synthetic OOM backoff tests below the real VRAM ceiling;
- confirm token packing and batch-halving preserve order;
- compare throughput and peak VRAM with the previous fixed batching;
- confirm CPU defaults and fingerprints remain unchanged.

GPU findings may justify a later calibrated profile change, but must not
silently mutate the semantic policy or invalidate existing indexes.

## Definition of done

The workstream is done only when:

- the branch contains all scoped implementation and documentation;
- selected chunking defaults are evidence-based;
- filters support compatible prefixes, globs, and per-type rules;
- semantic policy changes invalidate the smallest safe file set;
- cached hashes avoid redundant inference;
- unused active payloads can be safely dry-run, purged, and optionally
  compacted;
- batches are bounded by rows, tokens, and work bytes;
- recognized OOM failures back off deterministically;
- all functional tests and repository gates pass;
- the blocking CPU comparison passes every acceptance gate;
- the final report explicitly recommends or rejects integration;
- no merge into `main` occurs without the owner's decision.

## 2026-07-27 closeout report

### Decision

**REJECTED: do not merge `perf/semantic-pipeline-optimization` into `main`.**

The branch is retained for historical investigation only. Its implementation
and repair commit were deliberately not merged into `main`.

| Field | Value |
| --- | --- |
| Base SHA | `5bda60c5c5ae11898829be495b543988c23dbca8` |
| Optimization commit | `70d2e4e12141acc8e56635ee62f2a54f2fec0bf2` |
| Branch repair commit | `b38efee` |
| Branch | `perf/semantic-pipeline-optimization` |
| Main-branch report commit | Recorded with this report |

### Campaign evidence

The initial performance comparison was not valid for the warm-workload gate:
baseline and candidate adaptive resolution selected different context queries.
The branch repair commit added baseline-selection reuse and Hyperfine
per-result failure detection. The corrected candidate measurement completed
all 24 cells without recorded command failures:

- immediate: `.artifacts/semantic-pipeline-measure-corrected-v2-20260727/immediate/20260727T204149/`;
- deferred: `.artifacts/semantic-pipeline-measure-corrected-v2-20260727/deferred/20260727T212742/`;
- paired baselines: `.artifacts/semantic-pipeline-final-rerun-20260727/`.

The corrected comparison reused each baseline's resolved command selection.

### Measured result

| Mode | Cold full-index aggregate | Warm unchanged-index aggregate | Gate result |
| --- | ---: | ---: | --- |
| Immediate | +3.85% | +6.38% | FAIL |
| Deferred | +2.57% | +0.78% | PASS for these timing measures |

The plan requires cold full-index regression no greater than 3% and warm
unchanged-index regression no greater than 5%. Immediate mode therefore fails
both blocking timing gates.

The candidate campaign did not supply process-tree RSS or swap measurements,
so the memory gate is **INCOMPLETE**, not passed. It also did not rerun the
retrieval-quality dataset after the vector-binding repair, so the final quality
gate is **INCOMPLETE**, not passed.

### Correctness repairs found during measurement

Two branch-local defects were found and repaired before the corrected
measurement:

1. DuckDB incremental replacements could violate a unique index because
   deleted keys remained visible until a transaction boundary.
2. Segmented embedding writes in both vector stores could remove bindings from
   preceding segments, leaving only the final segment searchable.

Focused backend/campaign tests and the full repository validation passed on
the branch after these repairs. They remain branch-local because the branch
failed its optimization acceptance gates.

### Interpretation and follow-up

Documentation chunking reduced vector-row counts on qualifying workloads, but
the measured immediate-mode elapsed time regressed. The campaign does not
contain sufficient per-inference token, vector-persistence, or incremental
index profiling to attribute the overhead precisely. Do not resume this plan
from intuition or rerun the same matrix unchanged.

Any future performance effort must begin with a new, independently reviewed
hypothesis and paired preflight that proves identical inputs, commands,
versions, vector bindings, RSS instrumentation, and retrieval-quality inputs
before a long campaign is launched.
