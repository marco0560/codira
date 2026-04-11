# Embedding introduction in codira

PROJECT: codira
CURRENT_VERSION: v0.27.x
TASK: Introduce semantic embeddings as a new retrieval channel
ROLE: Senior Engineer
MODE: PLAN -> CONFIRM -> EXECUTE -> VERIFY (STRICT)

---

## SOURCE OF TRUTH

The repository filesystem is the only source of truth.

Rules:

• NEVER assume models, APIs, or storage not present
• NEVER introduce external services unless explicitly required
• If ambiguity exists -> STOP

---

## OBJECTIVE

Add a new retrieval channel based on **semantic embeddings**, while preserving:

• determinism
• existing behavior
• performance constraints

This must be an **additional channel**, not a replacement.

---

## SCOPE

Implement a minimal, production-usable embedding system:

1. Local embedding generation (no external API)
2. Precomputed embeddings stored during indexing
3. Query-time embedding similarity
4. Integration into existing merge pipeline

---

## STRICT DESIGN CONSTRAINTS

1. Embeddings MUST be:

   • computed at indexing time
   • persisted (SQLite or file-backed)
   • NOT recomputed at query time

2. Channel independence:

   • embedding channel MUST NOT modify symbol or semantic channels
   • merging remains rank-based

3. Determinism:

   • same repo + same query -> same ranking

4. Minimalism:

   • use a lightweight local model only
   • do not introduce large frameworks

---

## PHASE 1 — ANALYSIS

Inspect:

• indexing pipeline
• schema
• storage layer
• merge logic

Determine:

• where embeddings can be stored
• how symbols are uniquely identified
• how to attach embeddings to symbols

---

## PHASE 2 — PLAN

Provide:

• model choice (local, small)
• storage strategy
• embedding granularity:

* function name
* docstring
* optional code snippet

• integration into retrieval pipeline

Constraints:

• NO architectural rewrite
• NO premature optimization

Then STOP.

---

## PHASE 3 — EXECUTION RULES

When confirmed:

• add embedding generation in indexing
• store embeddings deterministically
• add query embedding computation
• implement cosine similarity

Do NOT:

• modify existing channels
• change ranking logic beyond adding a channel

---

## PHASE 4 — MERGE INTEGRATION

Embedding channel must:

• produce ranked results independently
• be merged via rank-based method (RRF-like)

Do NOT:

• mix raw scores across channels
• normalize across channels

---

## PHASE 5 — TESTING

Add deterministic tests:

1. same query → same ranking
2. semantically similar queries → overlapping results
3. no regression in symbol channel

---

## PHASE 6 — VERIFICATION

Provide:

• indexing command
• query command
• expected behavior

---

## SUCCESS CRITERIA

• embedding channel improves recall
• no regression in precision
• deterministic behavior preserved

---

## CONTROL COMMANDS

CMD:ANALYZE
CMD:PLAN
CMD:EXECUTE
CMD:STOP

---

END OF PROMPT
