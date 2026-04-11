# Dead code removal workflow

PROJECT: codira
CURRENT_VERSION: v0.27.x
TASK: Dead-code triage and removal using the implemented AST call graph
ROLE: Senior Engineer
ENVIRONMENT: Codex CLI agent
MODE: PLAN -> CONFIRM -> EXECUTE -> VERIFY (STRICT)

---

## SOURCE OF TRUTH

The current repository filesystem is the only source of truth.

Rules:

- NEVER assume files, symbols, or entry points not present in the repo
- NEVER rely on prior conversation memory
- If any required symbol or path is missing -> STOP and ask

---

## ASSUMPTION

Assume `codira` already supports a static AST-derived call graph and exposes
grounded call-edge inspection through the current CLI and indexed database.

Current grounded CLI surface:

- `codira calls <name>`
- `codira calls <name> --incoming`
- `codira calls <name> --module <module>`
- `codira refs <name>`
- `codira refs <name> --incoming`
- `codira refs <name> --module <module>`

Treat that graph as heuristic only.

It is useful for triage, not proof.

The graph is strongest for:

- direct same-module calls
- straightforward same-repo imported calls
- `self` / `cls` method calls

The graph is weaker for:

- dynamic dispatch
- decorators and registries
- reflective lookup
- plugin wiring
- unresolved attribute chains

Use `codira refs` to inspect callable-object references such as registry
bindings, assignment values, and returned function objects when `codira
calls` is insufficient.

---

## OBJECTIVE

Use `codira` to identify dead-code candidates and remove only code that is
well-supported as unused by:

- static call-graph evidence
- exact symbol checks and `rg` reference checks
- repository entry-point inspection
- test coverage and architecture checks

The goal is safe dead-code removal, not aggressive deletion.

Prefer report-first triage over immediate deletion.

---

## WORKFLOW (MANDATORY)

You MUST follow this sequence:

1. ANALYZE
2. PROPOSE PLAN
3. WAIT FOR CONFIRMATION
4. EXECUTE SMALL REMOVALS
5. VERIFY
6. STOP

No step skipping.

---

## PHASE 1 - ANALYSIS

For each candidate symbol:

1. Verify symbol existence with `rg`
2. Query `codira` for exact call edges, callable references, and related
   context:
   - `codira calls <name>`
   - `codira calls <name> --incoming`
   - `codira refs <name>`
   - `codira refs <name> --incoming`
   - `codira ctx "<query>"`
3. Inspect the defining file
4. Inspect possible entry points:
   - CLI registration
   - imports from `__init__` or `__main__`
   - tests
   - decorators / registries
   - plugin hooks

Determine whether the symbol is:

- clearly dead
- probably live
- ambiguous

If ambiguous -> do not remove it.

---

## REQUIRED EVIDENCE BEFORE REMOVAL

You may remove a symbol only if all of the following hold:

1. `rg` confirms no meaningful references outside its own definition
2. static call-graph inspection shows no inbound callers, or only callers that
   are themselves dead candidates
2a. callable-reference inspection shows no inbound registry / assignment /
    returned-function references, or only references from symbols that are
    themselves dead candidates
3. the symbol is not a public API that should remain exported
4. the symbol is not wired through CLI, registries, decorators, plugins, or
   reflective lookup
5. tests do not rely on it directly or indirectly
6. Before removal, verify that no indirect dependency exists through:

    - re-export (__init__)
    - wildcard imports
    - dynamic import patterns

7. Prefer removing entire symbols over partial edits.
   Do not partially modify functions to make them "used".
8. After each removal batch, the repository must remain indexable by codira.

Absence of inbound call edges alone is NOT sufficient evidence for removal.

If any of these checks fail or remain unclear -> STOP and leave the code in
place.

---

## PREFERRED CANDIDATES

Prioritize:

- private helpers
- isolated internal wrappers
- functions with no inbound references and no exports
- dead leaf utilities in scripts or tests

Avoid early removal of:

- public APIs
- CLI entry points
- registry participants
- methods on framework-facing classes
- anything reached via dynamic patterns

---

## PLAN OUTPUT

Produce a plan with:

- the exact dead-code candidates
- the evidence for each candidate
- the exact `codira calls`, `codira refs`, and `rg` commands used to
  justify each candidate
- impacted files
- risks
- the smallest safe patch set

Then STOP and wait.

---

## EXECUTION RULES

When confirmed:

- remove only the approved symbols
- keep diffs minimal
- update imports if needed
- add or update tests only when behavior/invariants change
- do not mix dead-code removal with refactoring

If a candidate becomes ambiguous during implementation, abort that candidate and
 explain why.

---

## VERIFICATION REQUIREMENTS

Provide exact commands and expected results for:

- exact symbol checks with `rg`
- `codira` caller/callee inspection
- repository validation commands
- tests touching the affected area

Expected results must show:

- the removed symbol is gone
- no inbound references remain
- validation and tests still pass

---

## SUCCESS CRITERIA

The task is complete only when:

- removed symbols are strongly supported as dead
- no live entry point is broken
- tests and validation pass
- ambiguous candidates are explicitly left untouched

---

## CONTROL COMMANDS

CMD:ANALYZE
CMD:PLAN
CMD:EXECUTE
CMD:STOP

---

END OF PROMPT
