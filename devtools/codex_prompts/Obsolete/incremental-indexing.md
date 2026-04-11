# PHASE X — Incremental Indexing for codira
PROJECT: codira
ROLE: Senior Engineer
MODE: HARD-FAIL DETERMINISTIC
BRANCH: dev/incremental-indexing

OBJECTIVE
---------
Introduce incremental indexing so that re-running `codira index`:

• reuses existing index data
• only reindexes changed files
• recomputes embeddings only when necessary
• preserves deterministic behavior
• avoids full rebuilds when possible

This must work for:
• symbol indexing
• semantic indexing (token channel)
• embedding channel (current or future)
• call graph and structural data

NO background daemon, no live indexing. Indexing remains an explicit command.

────────────────────────────────────────────
SOURCE OF TRUTH
────────────────────────────────────────────

The following are authoritative:

1. The repository snapshot (SOT archive)
2. Existing indexing pipeline under:
   - src/codira/indexer.py
   - src/codira/scanner.py
   - src/codira/storage.py
   - src/codira/models.py
3. Existing database schema (SQLite)

Rules:
• Do not infer missing structures
• Do not invent schema changes silently
• If the current schema is insufficient, propose a migration

────────────────────────────────────────────
ARCHITECTURAL REQUIREMENTS
────────────────────────────────────────────

Incremental indexing MUST be based on file identity and content change.

You MUST implement:

1. A stable per-file fingerprint
   • computed deterministically
   • based on file content (e.g. hash)
   • stored in DB

2. A decision mechanism:
   • unchanged file → skip
   • changed file → reindex
   • deleted file → remove from index

3. Change detection MUST NOT rely on:
   • timestamps alone
   • filesystem metadata only

────────────────────────────────────────────
DATABASE CHANGES
────────────────────────────────────────────

You MAY extend the DB schema, but must:

• propose a version bump
• migrate deterministically
• never destroy existing data without explicit migration

Required minimum data:

For each indexed file:
• file path
• content hash
• last indexed commit (optional)
• embedding hash (if embeddings exist)

────────────────────────────────────────────
EMBEDDINGS (IF PRESENT)
────────────────────────────────────────────

If embeddings exist:

• Embeddings MUST be recomputed only when:
  - source content changed
  - embedding backend changed
  - embedding version changed

• Embeddings MUST be cached
• Embedding invalidation must be explicit

────────────────────────────────────────────
INDEXING ALGORITHM
────────────────────────────────────────────

At high level:

1. Load existing index metadata
2. Scan filesystem
3. Compute file fingerprints
4. Compare with stored fingerprints
5. Classify files as:
   - unchanged
   - modified
   - added
   - deleted
6. Update DB incrementally

This must be deterministic and auditable.

────────────────────────────────────────────
CLI BEHAVIOR
────────────────────────────────────────────

`codira index` should:

• perform incremental indexing by default
• support a `--full` flag to force full rebuild
• emit summary:

Indexed: N
Reused: M
Deleted: K

If embeddings are enabled:

Embeddings recomputed: X
Embeddings reused: Y

────────────────────────────────────────────
EXPLAINABILITY
────────────────────────────────────────────

If `--verbose` or `--explain` is used:

• show why a file was reindexed or skipped
• show embedding reuse vs recompute

────────────────────────────────────────────
DETERMINISM & SAFETY
────────────────────────────────────────────

• No nondeterministic hashing
• No implicit model changes
• No background threads
• No silent failures

If inconsistency is detected:

• FAIL HARD
• Suggest full rebuild

────────────────────────────────────────────
TESTS
────────────────────────────────────────────

Add tests to validate:

• unchanged files are skipped
• changed files are reindexed
• deleted files are removed
• embeddings are reused correctly

Tests must not depend on:
• network
• external ML models

────────────────────────────────────────────
EXIT CRITERIA
────────────────────────────────────────────

✔ Incremental indexing works deterministically
✔ Full indexing still works
✔ Existing functionality unchanged
✔ Tests pass
✔ CI passes

STOP when all above are met.
