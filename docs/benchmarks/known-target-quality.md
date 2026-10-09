# Automatic known-target retrieval quality

Issue #59 compares embedding configurations using automatically derived,
source-verifiable targets. There is no manual grading, result pooling, grading
sheet, or LLM judge. The historical commit-path benchmark remains available;
its changed-file labels are not treated as gold labels for this mode.

## What the benchmark measures

A case contains an exact repository commit, query, intent, primary channel,
known targets, source SHA-256, and derivation rule. Generation reads Git blobs
at that commit, not mutable working-tree files. Execution regenerates the
source witnesses and rejects edited queries, targets, or provenance.

| Intent | Query source | Known target | Primary channel |
| --- | --- | --- | --- |
| `symbol_lookup` | Python definition name | Definition path and starting line | `emb` |
| `architecture_lookup` | Module docstring summary | Owning module file | `emb` |
| `task_lookup` | Definition docstring summary | Definition path and starting line | `emb` |
| `docs_lookup` | Markdown heading outside fenced code | Heading path and line | `docs` |
| `error_or_trace_lookup` | Literal raise argument, or its immediately preceding literal assignment | Owning definition path and line | `emb` |

Nested errors belong to their nested definition, not its enclosing function.
Interpolated messages, inferred call behavior, commit-changed paths, and cases
without a verifiable source witness are excluded. Public definitions are used;
test, fixture, benchmark, vendor and archive directories are excluded.
Generation requires the requested count in every repository/intent cell and
fails if a category is short. It does not fill gaps with guessed labels.

These labels are **not exhaustive semantic relevance judgments**. Module-file
cases have coarser resolution than definition or heading cases. Source-derived
queries can favor lexical matching. Recall means recall of known targets;
with one target it equals Hit at the same cutoff. Unlabeled results are not
established as irrelevant, and a better score does not prove more useful
agent answers. This benchmark does not replace #53 task-success evaluation.

## Versioned inputs

The public initial bank is
`benchmarks/retrieval-quality/known-target-v1/cases.jsonl`: 75 cases, with five
cases per intent for each of Codira, Fontshow, and sanikey. The adjacent
`fixtures.json` records public repository URLs and exact revisions. The full
initial local bank also includes one private repository and has **100 cases**.
Its cases and locator manifest remain ignored under
`.artifacts/benchmarks/retrieval-quality/datasets/known-target-20261008-v1/`.
Private query text, target identities and source evidence must never be copied
into tracked documentation, fixtures or reports.

Regenerate cases through `scripts/build_known_target_dataset.py`. The
`known-target-v1` format is validated by `scripts/known_target_quality.py`:
unique safe IDs, exact 40-character commits, known intents/channels, nonempty
queries and target sets, canonical repository-relative locations, positive
definition/heading lines (zero for file-level cases), and source digests.

Local locator manifests contain a `repositories` list with `label`, `path`,
and `commit`. Use the revisions from `fixtures.json`; leaving `commit` absent
selects current HEAD only when generating a new dataset. For example:

```json
{
  "schema_version": 1,
  "repositories": [
    {"label": "codira", "path": "ABSOLUTE_CODIRA_CHECKOUT", "commit": "PINNED_40_CHARACTER_SHA"}
  ]
}
```

Keep actual local paths and private repository entries in ignored storage.
All repositories referenced by a case bank must be present in the locator
manifest. A checkout may move or contain edits: execution archives its pinned
Git revision and checks frozen contents before each resume.

## Run, resume and rescore

Prerequisites: a Codira development checkout with `uv sync` completed; Git
objects for the pinned revisions; installed analyzers and embedding plugins;
the selected model assets available; and Linux for the campaign lock and
sampled process-tree RSS. Run commands from the Codira checkout. This mode
invokes its host `codira` executable and does not run a target project's UV
environment or setup scripts.

Create a local manifest at `REPOSITORY_MANIFEST`, then generate a new bank at
`CASE_BANK` if needed. Replace these names with actual paths before running:

```bash
uv run python -m scripts.build_known_target_dataset \
  --repo-manifest REPOSITORY_MANIFEST \
  --per-intent 5 \
  --output CASE_BANK
```

Expected output: `Generated N source-verified cases: ...`. A shortage or an
existing output path produces a nonzero exit. Correct the source/input issue
and select a new dataset output; do not overwrite existing evidence.

Choose a new ignored `RUN_DIRECTORY` under
`.artifacts/benchmarks/retrieval-quality/runs/`. Select models explicitly to
bound work; omitting `--model-id` selects the entire model manifest.

```bash
uv run python -m scripts.run_retrieval_quality_benchmark --known-target \
  --dataset CASE_BANK \
  --repo-manifest REPOSITORY_MANIFEST \
  --model-manifest benchmarks/embedding/model-candidates.json \
  --model-id bge-small-en-v1.5-onnx \
  --model-id jina-embeddings-v2-base-code-onnx \
  --baseline bge-small-en-v1.5-onnx \
  --k 1 5 10 \
  --output RUN_DIRECTORY
```

Execution defaults to SQLite, CPU embeddings, immediate indexing, fixed
4,000-character indexing text limits, and separate state per model/repository.
The warm query daemon and indexing daemon are disabled. The run stores rendered
configuration, runtime capabilities and digest, Codira executable digest,
available local ONNX model/tokenizer digests, dataset/model-manifest checksums,
repository commits/archive checksums, Python/platform/CPU metadata, K values,
command timeouts, and benchmark harness source hashes. Local model asset paths in the model manifest are resolved
from the Codira working directory before freezing. Named sentence-transformers
models do not have local weight digests in this mode; pin and retain their
upstream/cache assets separately before claiming exact weight reproducibility.

Each repository is indexed once per model. Every case runs its primary `emb`
or `docs` retrieval and a separate `ctx` probe. Rankings come only from the
returned ordered results; nested references and expanded context do not become
extra ranked hits. K is configurable up to 100; 1, 5 and 10 are always retained.
Archived sources receive an isolated Git index so Codira discovers exactly
their tracked contents instead of consulting the surrounding artifact host.
The generated `.git` metadata is separate from immutable source verification.
An empty or incomplete index is an execution failure.
Before querying, the runner verifies that the isolated SQLite vector bindings
match the complete structural embedding inventory, including cached payload
availability. Indexing counters alone do not establish search readiness.

Progress is enabled by default on stderr. An interactive terminal shows a
refreshing bar with completed/planned operations, model, repository, phase,
elapsed seconds and checkpoint reuse. Indexing has a heartbeat while its
subprocess runs. Redirected logs contain operation transitions and heartbeats
at most every 15 seconds between transitions. Percentages count operations;
they are not an estimate of elapsed-time completion, because indexing and
queries have different costs. Query text is excluded from progress output.
Use `--quiet-progress` to suppress these messages.

Expected successful terminal output: `Known-target results: ...`, exit 0,
`quality-summary.json`, and `quality-summary.md`. Failed indexing, incomplete
embeddings, nonzero commands, timeout, malformed JSON or invalid responses
produce a nonzero terminal status and retained evidence.

Default limits are 3,600 seconds per index and 900 seconds per query. Override
them with `--index-timeout` and `--query-timeout` when creating a run. Optional
`--memory-budget-mib` and `--max-index-seconds` record comparison budgets;
the latter applies to total model indexing time across selected repositories.

For long campaigns, supervise the same command with the established tmux
workflow and retain a log and separately written exit status alongside the run.
After interruption, rerun the **same command with `--resume` appended**. Successful
operations are reused only after checking their command and output digests.
Failures receive new numbered attempt directories; previous raw stdout,
stderr and measurements remain intact. Malformed successful responses are
retryable failures. Changed controls, runtime, model assets, source trees or
configurations require a new run identity. Do not edit saved records to force
reuse, and do not execute or rescore one identity concurrently.

Rescore without models, Git checkouts or retrieval execution:

```bash
uv run python -m scripts.run_retrieval_quality_benchmark --known-target \
  --output RUN_DIRECTORY \
  --rescore
```

Rescoring verifies the retained case checksum and successful raw-output
digests, reconstructs rankings from stdout, and rewrites only derived reports.
It returns nonzero if planned results or `ctx` probes are missing/failed.

## Interpretation and model comparison

Reports contain Hit@1, known-target Recall@5, MRR@5/10, and other requested
cutoffs. Breakdowns cover repositories and intents. Macro means equal weight
per repository; micro means the mean per-query metric. Failed and missing
primary queries remain in the full planned denominator with zero scores;
valid empty rankings are misses. Failures, empty rankings and `ctx` failures
are reported separately. Operational exit 0 is not a retrieval hit.

Primary-query median latency is reported separately for `emb` and `docs`;
`ctx` median latency and full-index wall time are additional cost measurements.
RSS is the largest process-tree resident-memory sum observed every 50 ms from
Linux `/proc`. It is a **sampled lower bound on peak**, can double-count shared
pages, and cannot establish compliance with a hard peak-memory budget.

With an explicit baseline, report the macro Recall@5 and MRR@10 differences,
the issue's suggested material-gain thresholds (+0.05 absolute for either),
and `emb`/`ctx` median-latency ratios against the suggested 1.25x limit.
Incomplete coverage yields `needs_more_data`; a complete comparison without
material gain yields `rejected`; a material known-target gain yields
`quality_profile_candidate` pending broader usefulness and resource validation.
The baseline remains a reference. No candidate is automatically promoted to
the default, and no installed configuration is modified.

Use small synthetic fixtures for automated validation. A fixture executable
tests the runner's protocol, persistence and scoring mechanics; it does not
qualify real embedding quality. Retain actual runtime smoke results separately
from a representative multi-repository comparison.

## Recovering from missing vector bindings

The initial local `known-target-full-20261008-v1` comparison completed its
commands but lost bindings from earlier indexing batches. Its zero quality
scores and model rejection cannot support a model-selection conclusion.
The backend now persists partial work segments incrementally. Keep that run
intact and repeat the documented execution with a new output identity, such
as `.artifacts/benchmarks/retrieval-quality/runs/known-target-full-20261008-v2`.
Do not append `--resume` to the old run after changing the harness or runtime.

## Optional relevance judgments

After a corrected comparison finishes, use the independent
[LLM retrieval grader](llm-retrieval-grading.md) to assess pooled snippet
relevance through OpenRouter. It requires an explicit judge and budget and
keeps those judgments separate from automatic known-target metrics.
