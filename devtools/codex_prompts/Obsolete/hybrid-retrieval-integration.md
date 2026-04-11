# Hybrid Retrieval + Integration

PROJECT: codira
CURRENT_VERSION: v0.27.x
TASK: Implement hybrid retrieval (symbol + semantic + embedding) and prepare external integration
ROLE: Senior Engineer
MODE: PLAN -> CONFIRM -> EXECUTE -> VERIFY (STRICT)

---

## OBJECTIVE

Combine all retrieval channels into a **coherent hybrid system** and prepare
codira for real-world usage (Fontshow).

---

## CHANNELS

Available channels:

• symbol (exact, deterministic)
• semantic (token-based)
• embedding (vector-based)

Each channel MUST remain independent.

---

## CORE PRINCIPLE

Ranking is based on:

→ rank aggregation (RRF-like), NOT score merging

Channel scores are NOT comparable.

---

## PHASE 1 — ANALYSIS

Inspect:

• current merge logic
• channel outputs
• ranking stability

---

## PHASE 2 — PLAN

Define:

• final merge strategy
• deduplication strategy
• tie-breaking rules

Requirements:

• deterministic ordering
• stable results across runs
• no duplicate symbols

Then STOP.

---

## PHASE 3 — EXECUTION

Implement:

1. unified merge layer
2. deduplication across channels
3. stable sorting

Constraints:

• no change to individual channel logic
• no score normalization

---

## PHASE 4 — CONTEXT IMPROVEMENT

Improve output for LLM consumption:

• better snippet selection
• include docstrings when relevant
• improve readability

---

## PHASE 5 — DOGFOODING (codira)

Use codira on itself:

1. run docstring audit queries
2. generate patches
3. fix docstrings

Constraints:

• only modify real symbols
• one patch per unit

---

## PHASE 6 — FONTSHOW INTEGRATION

Steps:

1. switch to Fontshow repo

2. BEFORE any action:

   run:
   rg <query>

3. run:

   codira ctx "<query>" --json

4. identify:

   • docstring issues
   • structural issues

5. produce patches

---

## INTEGRATION RULES

• NEVER assume Fontshow structure
• ALWAYS verify with rg
• NEVER hallucinate symbols

---

## PHASE 7 — VALIDATION

Verify:

• codira works on external repo
• results are relevant
• patches are correct

---

## SUCCESS CRITERIA

• hybrid retrieval improves results
• codira works on codira and Fontshow
• integration workflow is reproducible

---

## CONTROL COMMANDS

CMD:ANALYZE
CMD:PLAN
CMD:EXECUTE
CMD:STOP

---

END OF PROMPT
