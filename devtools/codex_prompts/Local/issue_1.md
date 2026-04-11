# PHASE 3.X — REAL EMBEDDINGS (OPTION B)
PROJECT: codira
ROLE: Senior Engineer
MODE: HARD-FAIL DETERMINISTIC
BRANCH: dev/embeddings-option-b

OBJECTIVE
---------
Introduce real embeddings into codira as an indexed artifact,
while preserving the current operational model:

• indexing remains explicit (codira index)
• embeddings are computed at index time only
• queries reuse stored vectors
• no background indexing
• deterministic invalidation rules

This phase introduces embeddings WITHOUT changing:
• CLI workflow model
• retrieval architecture (multi-channel)
• explicit user control

────────────────────────────────────────────
SOURCE OF TRUTH
────────────────────────────────────────────

You will receive:
1. Repository snapshot (SOT archive)

Rules:

• NEVER assume structure not present in snapshot
• NEVER invent modules or functions
• If mismatch occurs → STOP
• All patches must be minimal and surgical

────────────────────────────────────────────
INVARIANTS (MANDATORY)
────────────────────────────────────────────

Embeddings MUST be recomputed when:

1. Source content changes
2. Embedding backend changes
3. Embedding backend version changes

Embeddings MUST be reused when none of the above changes.

No hidden recomputation allowed.

────────────────────────────────────────────
EMBEDDING BACKEND (FIXED CHOICE)
────────────────────────────────────────────

Use:

- sentence-transformers
- model: all-MiniLM-L6-v2

Properties:

• local execution (no network)
• CPU-friendly
• deterministic given fixed version
• 384-dimensional vectors
• small (~22M params)

Reasons:

• best tradeoff quality/speed/complexity
• no GPU required
• no service dependency
• stable for reproducible indexing

DO NOT introduce:
• remote APIs
• large models
• GPU-only dependencies

────────────────────────────────────────────
ARCHITECTURAL CONSTRAINTS
────────────────────────────────────────────

Embeddings are:

• index-time artifacts
• stored in SQLite
• immutable unless invalidated

Embeddings are NOT:

• recomputed at query time
• lazily generated
• dependent on runtime environment

────────────────────────────────────────────
IMPLEMENTATION PLAN
────────────────────────────────────────────

STEP 1 — Embedding abstraction

Create or extend:

    src/codira/semantic/embeddings.py

Define a backend interface:

    class EmbeddingBackend:
        name: str
        version: str
        dimension: int

        def embed_text(self, text: str) -> list[float]:
            ...

Add module-level constants:

    EMBEDDING_BACKEND = "minilm"
    EMBEDDING_VERSION = "1"

DO NOT derive version dynamically.

────────────────────────────────────────────
STEP 2 — Concrete backend

Implement MiniLM backend:

    SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

Requirements:

• CPU-only
• deterministic output
• normalize embeddings (L2)

────────────────────────────────────────────
STEP 3 — DB schema extension

Extend SQLite schema with embeddings table:

    embeddings:
        symbol_id (FK)
        embedding (BLOB)
        content_hash (TEXT)
        backend (TEXT)
        backend_version (TEXT)
        dimension (INT)

Constraints:

• embedding stored as float32 bytes
• NOT JSON
• NOT text

If schema versioning exists → bump version

────────────────────────────────────────────
STEP 4 — Content hashing

Define stable hash:

• based on extracted text used for embedding
• NOT raw file bytes necessarily
• must be deterministic

Example input:

    function_name + signature + docstring

Store hash alongside embedding.

────────────────────────────────────────────
STEP 5 — Indexing integration

Extend indexing pipeline:

For each symbol:

1. extract embedding text
2. compute content_hash
3. check DB:

    if embedding exists AND matches:
        reuse
    else:
        compute embedding
        store

Ensure:

• no recomputation if unchanged
• no missing embeddings after indexing

────────────────────────────────────────────
STEP 6 — Retrieval integration

Replace semantic channel logic:

OLD:
    token overlap

NEW:
    cosine similarity on stored embeddings

Procedure:

1. embed query
2. fetch candidate embeddings
3. compute cosine similarity
4. return ranked results

IMPORTANT:

• do NOT scan entire DB blindly
• reuse existing candidate filtering if present

────────────────────────────────────────────
STEP 7 — Merge integration

Embedding channel integrates into existing merge:

• no special-case logic
• just another channel with scores

Ensure:

• score scaling compatible
• deterministic ordering

────────────────────────────────────────────
STEP 8 — CLI / EXPLAIN

Extend explain output:

Add:

    embedding_backend
    embedding_version

Optional:

• show embedding score contribution

────────────────────────────────────────────
STEP 9 — TESTS

Add tests:

1. Determinism:
   same input → identical embedding bytes

2. Reuse:
   unchanged file → no recomputation

3. Invalidation:
   content change → recompute

4. Backend change:
   version change → recompute

5. Schema compliance

Tests must:

• run offline
• not require GPU
• not require network

────────────────────────────────────────────
STEP 10 — DOCUMENTATION

Document clearly:

• embeddings increase indexing cost, not indexing frequency
• explicit invalidation rules
• how to force rebuild

────────────────────────────────────────────
SAFETY RULES
────────────────────────────────────────────

• NO background threads
• NO hidden caching layers
• NO lazy embedding
• NO network calls
• NO nondeterministic behavior

If any invariant is violated → STOP

────────────────────────────────────────────
EXIT CRITERIA
────────────────────────────────────────────

✔ codira index computes embeddings deterministically
✔ embeddings persisted and reused
✔ invalidation works correctly
✔ retrieval uses stored embeddings
✔ all tests pass
✔ CI passes

STOP when all criteria are satisfied.
