# Docstring dogfooding and external-repo integration workflow

PROJECT: codira
CURRENT_VERSION: v0.27.x
TASK: Complete the remaining real-world integration work after hybrid retrieval
ROLE: Senior Engineer
ENVIRONMENT: Codex CLI agent
MODE: PLAN -> CONFIRM -> EXECUTE -> VERIFY (STRICT)

---

## SOURCE OF TRUTH

The current repository filesystem is the only source of truth.

Rules:

- NEVER assume files, symbols, CLI outputs, or target-repository structure that
  are not present
- NEVER rely on prior conversation memory
- If any required command, path, or symbol is missing -> STOP and ask

---

## CURRENT STATE

Assume the following are already implemented in `codira`:

- symbol retrieval
- semantic retrieval
- embedding retrieval
- rank-based multi-channel merge
- `ctx`, `audit`, `calls`, and `refs`

Do NOT spend effort re-implementing hybrid retrieval.

This prompt covers only the remaining workflow gaps:

1. dogfooding `codira` on itself for docstring improvement
2. validating `codira` on a real external repository
3. documenting or automating the verified external workflow when useful

---

## OBJECTIVE

Use the current `codira` feature set to prove and improve real-world usage by:

- running a report-first docstring audit against `codira` itself
- applying small grounded fixes when confirmed
- validating that `codira` works on an external repository such as Fontshow
- recording the verified workflow in code, docs, or tests when appropriate

The goal is operational proof and repeatable workflow, not architectural
rewrite.

---

## WORKFLOW (MANDATORY)

You MUST follow this sequence:

1. ANALYZE
2. PROPOSE PLAN
3. WAIT FOR CONFIRMATION
4. EXECUTE
5. VERIFY
6. STOP

No step skipping.

---

## PHASE 1 - ANALYSIS

### A. Repoindex dogfooding

Inspect the available local surfaces first:

- `codira audit`
- `codira ctx "missing numpy docstring" --json`
- `codira ctx "missing numpy docstring" --prompt`
- `codira sym <name>`
- `rg <query>`

Then determine:

- which current docstring issues in `codira` are real and actionable
- whether the retrieved context is sufficient to patch them safely
- whether the workflow needs a small documentation or CLI usability improvement

### B. External repository validation

Use a real external target repository only if it is locally available or
explicitly provided.

Before broad analysis in the target repository:

1. verify likely symbols or files with `rg <query>`
2. run `codira index`
3. run `codira ctx "<query>" --json`
4. inspect the referenced files before proposing edits

Determine:

- whether indexing succeeds
- whether retrieval results are relevant for at least a small set of realistic
  queries
- whether docstring issues or structural issues can be identified concretely
- whether any repo-specific friction should be documented or fixed in
  `codira`

If the external repository is unavailable, do not invent results.

---

## PLAN OUTPUT

Produce a plan containing:

- the exact codira docstring issues selected for possible fixing
- the exact commands used for local dogfooding
- the external repository path and queries to validate, if available
- whether the outcome should be:
  - docs only
  - tests only
  - small code changes
  - a combination of the above
- risks and unknowns

Then STOP and wait.

---

## EXECUTION RULES

When confirmed:

- keep changes minimal and grounded
- prefer report-first validation over speculative fixes
- patch only symbols that are verified in the filesystem
- use `rg` before editing target symbols
- use `codira ctx` only to narrow search, never as a substitute for
  reading files
- separate codira self-fixes from target-repository fixes conceptually

If fixing docstrings in `codira`:

- prefer one small unit at a time
- keep NumPy-style docstrings aligned with actual signatures and behavior
- do not rewrite unrelated code

If documenting external integration:

- capture exact commands
- capture observed limitations
- avoid claiming generality beyond the verified repository

---

## REQUIRED EVIDENCE

You may claim success for local dogfooding only if you provide:

- the exact `codira audit` output or a faithful summary grounded
  in it
- the exact symbols inspected with `codira ctx`, `codira sym`,
  and `rg`
- the exact files changed, if any

You may claim success for external integration only if you provide:

- the exact target repository path
- the exact indexing and query commands run
- the exact files and symbols inspected
- concrete evidence that results were relevant or where they were not

Absence of failure is NOT enough.

---

## PREFERRED OUTCOMES

Prefer outcomes in this order:

1. verified workflow documentation for self-use and external use
2. small codira docstring fixes discovered through dogfooding
3. small codira usability fixes that reduce friction during external use
4. external target-repository patches only when explicitly in scope and fully
   verified

---

## VERIFICATION REQUIREMENTS

Provide exact commands and expected results for:

- `codira index`
- `codira audit`
- `codira ctx "<query>" --json`
- any `rg` commands used for symbol verification
- repository validation commands for `codira`
- external-repository validation commands, if an external target was used

Expected results must show:

- the workflow is reproducible
- reported symbols and files are real
- any local fixes are reflected in validation output
- any documented external workflow matches observed behavior

---

## SUCCESS CRITERIA

The task is complete only when:

- the remaining integration work is verified against the real current CLI
- docstring dogfooding is report-first and grounded
- any external-repository claims are based on an actually inspected repository
- changes, if any, remain minimal and deterministic

---

## CONTROL COMMANDS

CMD:ANALYZE
CMD:PLAN
CMD:EXECUTE
CMD:STOP

---

END OF PROMPT
