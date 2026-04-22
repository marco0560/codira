# Issue 021 C Constants Design Check

## Purpose

This note records the short design check for C constants requested after the
Python constant and declaration-ontology slices for issue `#21`.

It does not change runtime behavior.

## Verified Findings

Current tree-sitter C parse shapes in this repository distinguish three
relevant top-level forms:

1. object-like macros parse as `preproc_def`
2. function-like macros parse as `preproc_function_def`
3. `static const` or `const` declarations parse as ordinary `declaration`
   nodes with `init_declarator` children

That matters because the current C analyzer declaration path only normalizes
named type declarations such as `struct`, `union`, `enum`, and `typedef`.

Additional verified constraints from `ADR-016`:

* arbitrary module-level variables remain deferred
* generic constants without a stable declaration rule remain deferred
* default query behavior must stay non-noisy
* new categories must have deterministic extraction and stable identity rules

Enum members are already covered as subordinate enum metadata and should not be
reintroduced as peer constant symbols.

## Candidate Categories

### Object-Like Macros

Examples:

```c
#define PORT 8080
#define NAME "codira"
```

Pros:

* top-level parse form is explicit and distinct from ordinary declarations
* exposed name is deterministic
* function-like macros can be excluded cleanly by node type

Risks:

* comments and semantic text need a dedicated attachment rule
* macro replacement text is syntactic, not typed, so ontology mapping must
  remain clearly analyzer-specific
* default symbol noise can grow quickly in macro-heavy headers

### `static const` and `const` Declarations

Examples:

```c
static const int LIMIT = 3;
const char *TITLE = "codira";
```

Pros:

* names and literal initializers are available in the declaration tree
* values are often user-facing

Risks:

* these forms are much closer to ordinary variables than to named type
  declarations
* storage class, pointer syntax, and rebinding patterns make the constant
  boundary less stable than the Python all-caps rule
* this direction risks violating the ADR deferral on arbitrary module-level
  variables

### Function-Like Macros

Examples:

```c
#define CALL(x) ((x) + 1)
```

Recommendation:

* explicitly out of scope for the first C-constant slice

Reason:

* they behave more like callable preprocessors than named constants and would
  blur the callable-versus-declaration boundary

## Recommendation

Do **not** implement C constants yet as part of issue `#21`.

If the repository later chooses one bounded C-constant slice, the only
reasonable first target is:

* object-like `#define` macros only

with these required boundaries:

1. accept `preproc_def` only
2. exclude `preproc_function_def`
3. require one explicit stable ID rule such as
   `c:macro:<owner_id>:<name>`
4. keep default plain-text `sym` behavior unchanged unless exact lookup is
   requested
5. add deterministic comment and replacement-text rendering rules before
   persistence lands

The following should remain deferred:

* `static const` declarations
* non-`static` `const` declarations
* macro functions
* enum members as peer symbols

## Outcome

No implementation is recommended in the current step.

The next C-constant slice, if approved later, should start with a dedicated
design-to-code plan for object-like macros only.
