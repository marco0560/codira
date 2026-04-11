# Dead code removal workflow (generic Python repo)

PROJECT: target repository
TASK: Dead-code triage and removal using codira
ROLE: Senior Engineer
ENVIRONMENT: Codex CLI agent
MODE: PLAN -> CONFIRM -> EXECUTE -> VERIFY (STRICT)

---

## SOURCE OF TRUTH

The current repository filesystem is the only source of truth.

Rules:

- NEVER assume files, symbols, entry points, or frameworks not present in the
  target repository
- NEVER rely on prior conversation memory
- If any required symbol, command, or path is missing -> STOP and ask

---

## ASSUMPTION

Assume the target repository is a Python repository and `codira` is
installed in the local `.venv`.

Assume the available CLI surface includes:

- `codira index`
- `codira sym <name>`
- `codira calls <name>`
- `codira calls <name> --incoming`
- `codira refs <name>`
- `codira refs <name> --incoming`
- `codira ctx "<query>"`

Before broad analysis, verify that:

1. `.venv` exists
2. `codira index` succeeds in the target repository

Treat `codira` call and reference data as heuristic only.

It is useful for triage, not proof.

Typical strengths:

- direct same-module calls
- straightforward same-repo imported calls
- `self` / `cls` method calls
- direct callable-object references such as registry values and assignment
  values

Typical weaknesses:

- dynamic dispatch
- decorators and registries with dynamic registration
- reflective lookup
- plugin wiring
- unresolved attribute chains
- framework-specific magic

---

## OBJECTIVE

Use `codira` to identify dead-code candidates and remove only code that is
well-supported as unused by:

- static call-edge evidence
- callable-reference evidence
- exact symbol checks and `rg` reference checks
- repository entry-point inspection
- tests and architecture checks

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
   - exports from `__init__` or `__main__`
   - tests
   - decorators / registries
   - plugin hooks
   - framework configuration
   - dynamic imports or reflective lookup

Determine whether the symbol is:

- clearly dead
- probably live
- ambiguous

If ambiguous -> do not remove it.

---

## REQUIRED EVIDENCE BEFORE REMOVAL

You may remove a symbol only if all of the following hold:

1. `rg` confirms no meaningful references outside its own definition
2. static call-edge inspection shows no inbound callers, or only callers that
   are themselves dead candidates
3. callable-reference inspection shows no inbound references, or only
   references from symbols that are themselves dead candidates
4. the symbol is not a public API that should remain exported
5. the symbol is not wired through CLI, registries, decorators, plugins, or
   reflective lookup
6. tests do not rely on it directly or indirectly
7. before removal, verify that no indirect dependency exists through:
   - re-export (`__init__`)
   - wildcard imports
   - dynamic import patterns
   - framework discovery rules
8. prefer removing entire symbols over partial edits
9. after each removal batch, the repository must remain indexable by
   `codira`

Absence of inbound call edges alone is NOT sufficient evidence for removal.

Absence of inbound callable references alone is NOT sufficient evidence for
removal.

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

If a candidate becomes ambiguous during implementation, abort that candidate
and explain why.

---

## VERIFICATION REQUIREMENTS

Provide exact commands and expected results for:

- exact symbol checks with `rg`
- `codira` call-edge inspection
- `codira` callable-reference inspection
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
