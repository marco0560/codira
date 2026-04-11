# AST call graph implementation

PROJECT: codira
CURRENT_VERSION: v0.27.x
TASK: Add AST-derived static call graph support
ROLE: Senior Engineer
ENVIRONMENT: Codex CLI agent
MODE: PLAN -> CONFIRM -> EXECUTE -> VERIFY (STRICT)

---

## SOURCE OF TRUTH

The current repository filesystem is the only source of truth.

Rules:

- NEVER assume files, modules, tables, or CLI commands that are not present
- NEVER rely on prior conversation memory
- If any required structure is missing or ambiguous -> STOP and ask

---

## OBJECTIVE

Add a useful, deterministic AST-derived static call graph to `codira`.

This call graph must improve:

- caller/callee navigation
- impact analysis
- dead-code triage
- context expansion around functions

The implementation must be clearly presented as static and heuristic, not as a
proof of runtime reachability.

---

## SCOPE

Implement a minimal but production-usable first version.

Required outcomes:

1. Parse call sites from repository Python files using AST
2. Resolve straightforward same-repo call edges where possible
3. Persist call edges in SQLite
4. Expose at least one CLI path for inspection
5. Add deterministic tests
6. Keep retrieval and indexing behavior stable unless directly extended

Out of scope unless already easy and grounded in the repo:

- perfect interprocedural resolution
- dynamic dispatch solving
- reflection / getattr / monkey-patching resolution
- framework-specific plugin inference

---

## WORKFLOW (MANDATORY)

You MUST follow this exact sequence:

1. ANALYZE current parser, indexer, schema, and CLI surfaces
2. PRODUCE a minimal plan
3. WAIT for confirmation
4. EXECUTE with surgical patches
5. VERIFY with exact commands and expected output
6. STOP

No step skipping.

---

## PHASE 1 - ANALYSIS

Inspect only:

1. `src/codira/parser_ast.py`
2. `src/codira/indexer.py`
3. `src/codira/schema.py`
4. `src/codira/query/*`
5. `src/codira/cli.py`
6. relevant tests under `tests/`

Determine:

A. What callable metadata is already extracted
B. Whether call-edge storage already exists and how complete it is
C. How symbols are represented and keyed
D. The smallest reliable resolution strategy for function calls
E. Where a new CLI entry should live, if needed

If call-edge storage already exists partially, extend it rather than replacing
it.

---

## PHASE 2 - PLAN

Produce a plan containing:

- single implementation strategy
- minimal schema/index/parser changes
- exact files to modify
- exact tests to add or update
- risks and known heuristics

Then STOP and wait.

---

## PHASE 3 - EXECUTION RULES

When confirmed:

- apply the smallest correct diff
- preserve project style
- do not refactor unrelated code
- do not rewrite unrelated retrieval logic
- prefer extending existing tables, parser outputs, and query helpers

The implementation should prefer:

- direct-name call extraction
- imported-name resolution where already available from the parser/index
- module-qualified calls only when resolvable from local static information
- an explicit unresolved bucket or omission for ambiguous calls

---

## REQUIRED DESIGN CONSTRAINTS

1. The call graph must be presented as static and heuristic.
2. At minimum, the implementation should distinguish:

    - resolved call edges
    - unresolved or skipped call sites

3. Useful first-step invariants:

    - deterministic ordering
    - deterministic database writes
    - no duplicate call edges for the same caller/callee pair
    - no dependency on runtime execution

4. If symbol resolution is ambiguous, prefer dropping the edge over inventing one.
5. Each call edge MUST be uniquely identified by:

    - caller_module,
    - caller_name,
    - callee_module,
    - callee_name

6. Do not rely on line numbers for identity.
7. Call graph extraction MUST be part of indexing, not query-time.
8. No dynamic recomputation during query.
9. The call graph must be stored in a way that allows future extension (e.g. edge
   types, confidence, unresolved reasons) without schema rewrite.

---

## TESTING REQUIREMENTS

Add focused, deterministic tests for:

1. direct local function calls
2. same-module helper calls
3. imported same-repo function calls when straightforward
4. ambiguous or dynamic calls being skipped or marked unresolved
5. deterministic edge ordering / storage
6. CLI inspection path if one is added

Tests must not require network, external binaries, or non-deterministic input.

---

## VERIFICATION OUTPUT FORMAT

Provide exact commands:

- command to rebuild or inspect the index
- command to exercise the new call-graph path
- test command(s)
- lint/type-check command(s) if applicable

For each command provide:

- Command: `<exact command>`
- Expected result: `<exact observable behavior>`

---

## SUCCESS CRITERIA

The task is complete only when:

- `codira` stores deterministic static call edges
- at least one grounded inspection path exists for callers/callees
- tests cover the new behavior
- no unrelated behavior regresses
- the static / heuristic limitations are explicit in code or docs where needed

---

## CONTROL COMMANDS

CMD:ANALYZE
CMD:PLAN
CMD:EXECUTE
CMD:STOP

---

END OF PROMPT
