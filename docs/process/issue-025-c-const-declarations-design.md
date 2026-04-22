# Issue 025 C `const` Declarations Design

## Purpose

This note resolves issue `#25` by defining whether bounded C `const`
declarations should enter the first-level declaration surface after the
completion of issue `#21`.

It does not change runtime behavior.

## Verified Findings

Current repository behavior and parser shape establish the following facts:

1. object-like macros are supported through `preproc_def`
2. function-like macros parse cleanly as `preproc_function_def`
3. ordinary `static const`, `const`, and `extern const` declarations parse as
   generic `declaration` nodes with either `init_declarator` children or direct
   declarator children
4. multiple declarators, computed expressions, aggregate initializers, and
   declaration-only `const` rows are all structurally visible in the current
   parse tree
5. the current C analyzer declaration path can extend this surface without
   inventing heuristic text parsing

That means C `const` support cannot be justified merely because the parser can
see a declaration name. The accepted boundary still requires deterministic
extraction, stable identity, explicit analyzer mapping, and non-noisy default
behavior.

## Compared Options

### Option 1 — Keep the narrow `static const` / literal-only boundary

Pros:

* preserves the current low-noise declaration boundary almost completely
* keeps exported declarations and declaration-only rows out of the symbol set
* avoids broader questions about multiple declarators and expression forms

Cons:

* excludes several syntactically stable constant forms users still mean when
  they ask for named constants
* forces an arbitrary distinction between literal-only and non-literal constant
  declarations even though both are parse-visible

Assessment:

* too restrictive for the broader constant model requested in issue `#25`

### Option 2 — Accept the expanded `const` declaration family plus
function-like macros

Examples:

```c
#define CALL(x) ((x) + 1)
const int LIMIT2 = 3;
extern const int SIZE = 3;
static const int A = 1, B = 2;
static const int VALUE = 1 + 2;
static const int VALUES[] = {1, 2};
const int DECL_ONLY;
```

Pros:

* every requested form is directly visible in the existing tree-sitter parse
  tree
* stable identity remains straightforward because each exposed name still maps
  to one owner-scoped declaration row
* the analyzer contract can stay explicit by keeping these rows under the
  existing canonical `constant` ontology
* this covers the user-facing constant shapes that the current narrow slice
  still omitted

Cons:

* the constant-versus-variable boundary becomes materially broader
* declaration-only rows add symbols without initializer evidence
* function-like macros continue to blur the constant-versus-callable intuition

Assessment:

* acceptable if the repository explicitly chooses broader C constant coverage
  over the narrower low-noise boundary

### Option 3 — Reject C declaration constants but include only macros

Examples:

```c
#define PORT 8080
#define CALL(x) ((x) + 1)
```

Pros:

* keeps the declaration boundary tight
* avoids variable-adjacent declaration rows entirely

Cons:

* does not satisfy the broader constant coverage requested in issue `#25`
* leaves ordinary named `const` declarations unmodeled

Assessment:

* simpler, but no longer aligned with the requested outcome

## Recommendation

Broaden C constant support to include both function-like macros and
`const`-qualified declaration families.

Accepted perimeter:

* object-like macros
* function-like macros
* `const` declarations
* `static const` declarations
* `extern const` declarations
* declaration-only `const` rows without initializer evidence
* multiple declarators per declaration statement
* computed expressions and aggregate initializers
* default plain-text `sym` behavior must remain unchanged unless exact lookup
  is requested

The following still remain out of scope:

* non-`const` variables
* declarations whose exposed declarator is a function prototype
* generic variable support without `const`
* changing the canonical ontology away from `constant`

## Implementation Perimeter for a Future Slice

If implementation is approved later, the design-to-code plan should start with
these required rules:

1. classify accepted rows under the existing explicit analyzer-owned constant
   and macro declaration kinds rather than overloading the generic variable
   surface
2. derive one stable ID per accepted declaration name using the existing
   owner-scoped declaration identity model
3. map both declaration `constant` rows and macro rows explicitly to the
   canonical `constant` ontology
4. add regression tests proving non-`const` variables and function
   declarations stay excluded
5. bump only the touched analyzer and bundle versions at the end of the slice

## Outcome

Issue `#25` resolves to a broader C constant model:

* function-like macros are accepted as constant-like symbols
* `const`-qualified declaration rows are accepted as constant symbols
* the runtime boundary excludes only non-`const` variables and function
  declaration forms
