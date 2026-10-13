# Pending embedding population and recovery

SQLite and DuckDB process deferred embeddings in bounded work segments. The
segment size is the existing `embeddings.batch_size` multiplied by
`embeddings.indexing.work_batch_multiplier`; model inference retains its own
configured batch size. Texts, cached vectors and generated vector lists no longer
need to hold the entire pending repository population simultaneously.

When the backend owns its connection, each completed segment commits its
structural embedding markers and pending-row removals. An interrupted current
segment rolls back; a subsequent explicit population processes the remaining
queue. An externally supplied connection remains under caller transaction
control: the backend neither commits nor rolls it back. Separate vector caches
may contain reusable data from an interrupted write, as before; committed
structural markers determine pending work. This is not an atomic transaction
across separate databases. The inference model and source selection are unchanged.

Explicit `index --embeddings-only` rebuilds derived similarity artifacts after
population even if the queue is already empty or the remaining vectors came
from cache. This repairs interruption between durable vector persistence and
similarity publication. Publication failure remains a command failure; completion
is reported only after it succeeds. A hard kill can lose the current segment,
but completed owned segments remain durable. The guarantee is database recovery,
not preservation of in-flight inference computations.

## Operator-controlled recovery and profiling

Prerequisites: select an installed Codira runtime containing these fixes, a
registered workspace with a usable structural index and enabled embeddings,
and no competing index writer. From that Codira checkout, replace the named
placeholders with the intended workspace and a fresh durable evidence directory:

```bash
OWNED_WORKSPACE=your-workspace-name
PROFILE_DIR="$PWD/.artifacts/validation/embedding-recovery-operator-r1"
CODIRA_EMBEDDING_PROFILE_DIR="$PROFILE_DIR" uv run --offline --no-sync codira index --workspace "$OWNED_WORKSPACE" --embeddings-only --json
```

Do not point this procedure at a running campaign's workspace or change that
campaign's source/runtime. Successful output reports `embedding_complete=true`
and zero active pending rows. After Ctrl-C, repeat this exact population command
for the same workspace; it reuses completed segments and gives the profiling
attempt a new journal filename. After a publication error, the same command also
repairs derived artifacts even when no vectors need recomputing.

Profiling is opt-in. Unique per-invocation JSONL journals record queue selection,
cache lookup, inference, serialization, persistence, checkpoint commit and total
population durations. Row counts and throughput accompany applicable phases;
interruption records the original exception type. Journals contain no source
text, vector data or exception messages. A failed diagnostic write warns and
disables further profiling without masking a processing error. A nonexistent
profile directory is created; failure to create it rejects profiling startup.

`population.total` overlaps its component spans; do not add it to their timings.
RSS is the process lifetime high-water mark, normalized to KiB where available;
it does not measure allocation within a phase or simultaneous process-tree
memory. Throughput can count unique inference texts or logical persistence rows,
so compare matching phases and units. The command's wall time also includes the
similarity rebuild, which is outside backend population spans. Profiling does
not resolve structural partial coverage or imply repository-wide completeness.

## Measurement limits

The retained focused probe uses native SQLite/DuckDB structural-marker writes,
8,192 pending rows, 384-dimensional simulated vectors, and 2,048-row segments.
It deliberately excludes a real embedding model, separated vector-store writes
and similarity construction. Its source hashes, alternating paired trials and
measurements are retained under
`.artifacts/validation/stress-findings-20261013/pending-persistence-final-*`.
These measurements establish the work-segment bound and local persistence
behavior; they cannot establish an end-to-end LLVM or campaign speedup. Full
campaign verification is operator-run with a new immutable identity.


Focused paired probe medians (three trials per mode; simulated inference):
| Backend | Whole-queue seconds | Bounded seconds | Whole-queue peak RSS KiB | Bounded peak RSS KiB |
| --- | ---: | ---: | ---: | ---: |
| sqlite | 0.417 | 0.298 | 79716 | 46704 |
| duckdb | 0.350 | 0.345 | 206304 | 180292 |

The bounded candidate reduced peak RSS in both native probes. DuckDB timings
are too close and variable to establish a speedup. These values exclude real
model inference, separated vector stores and similarity construction; they are
not campaign comparisons. Source digests and raw trials are retained.
