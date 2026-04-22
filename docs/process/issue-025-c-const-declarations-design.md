# Issue 025 C `const` Declarations Design

## Purpose

This note resolves issue `#25` by defining whether bounded C `const`
declarations should enter the first-level declaration surface after the
completion of issue `#21`.

It does not change runtime behavior.

## Verified Findings

Current repository behavior and parser shape establish the following facts:

1. object-like macros are now supported through `preproc_def`
2. function-like macros remain excluded through `preproc_function_def`
3. ordinary `static const` and `const` declarations still parse as generic
   `declaration` nodes with `init_declarator` children
4. the current C analyzer declaration path only normalizes categories with
   explicit top-level classifier nodes or similarly bounded naming rules
5. `ADR-016` still defers arbitrary variables and generic constants without a
   stable declaration rule

That means C `const` support cannot be justified merely because the parser can
see a declaration name. The accepted boundary still requires deterministic
extraction, stable identity, explicit analyzer mapping, and non-noisy default
behavior.

## Compared Options

### Option 1 — Reject C `const` declarations for now

Pros:

* preserves the current low-noise declaration boundary completely
* avoids conflating `const` declarations with ordinary variables
* avoids premature rules for pointer forms, linkage, and multiple declarators

Cons:

* leaves a real user-facing category unmodeled even when it is structurally
  stable
* creates an asymmetry between bounded Python constants and obviously literal
  C constants

Assessment:

* defensible, but stricter than necessary if a narrower perimeter can be
  defined cleanly

### Option 2 — Accept only `static const` with one declarator and a
literal-only initializer

Examples:

```c
static const int LIMIT = 3;
static const char *NAME = "codira";
```

Accepted initializer families for this option would need to be explicit and
syntactic:

* numeric literals
* character literals
* string literals

Deferred even inside this option:

* aggregate initializers
* compound literals
* macro-expanded values
* expression trees such as `1 + 2`
* multiple declarators in one statement

Pros:

* `static` provides a narrow boundary that does not immediately blur into
  exported variables
* one-declarator statements make stable identity straightforward
* literal-only values stay deterministic without semantic evaluation
* the ontology mapping can remain analyzer-specific and explicit

Cons:

* pointer declarators still require careful syntactic filtering
* some user-meaningful constants remain excluded
* initializer classification would need a dedicated parser-side rule rather
  than reuse of the current generic declaration path

Assessment:

* this is the narrowest plausible implementation perimeter that still adds new
  value without violating `ADR-016`

### Option 3 — Accept a broader literal-initialized subset

Examples:

```c
const int LIMIT = 3;
const char *TITLE = "codira";
```

Pros:

* covers more real-world declarations immediately
* reduces user-visible inconsistency between internal and exported constants

Cons:

* exported `const` declarations are much closer to ordinary variables
* linkage and header-level declaration forms become harder to model without
  noise
* the accepted boundary would drift toward generic variable support too early

Assessment:

* too broad for the current repository boundary

## Recommendation

Do **not** broaden C constant support beyond the current macro slice in the
same feature family.

If the repository later chooses one follow-up implementation slice, the only
acceptable first perimeter is:

* `static const` declarations only
* exactly one declarator per declaration statement
* required initializer
* initializer must be a direct literal node, not a computed expression
* default plain-text `sym` behavior must remain unchanged unless exact lookup
  is requested

The following remain explicitly out of scope:

* non-`static` `const` declarations
* `extern const` declarations
* declaration-only `const` rows without initializer evidence
* multiple declarators in one statement
* aggregate initializers, computed expressions, and macro-expanded values
* any treatment of generic variables as first-level symbols

## Implementation Perimeter for a Future Slice

If implementation is approved later, the design-to-code plan should start with
these required rules:

1. classify accepted rows under one explicit analyzer-owned declaration kind
   rather than overloading the generic variable surface
2. derive one stable ID per accepted declaration name using the existing
   owner-scoped declaration identity model
3. map the accepted kind explicitly to the canonical `constant` ontology
4. add regression tests proving excluded forms stay excluded
5. bump only the touched analyzer and bundle versions at the end of the slice

## Outcome

Issue `#25` resolves to a bounded design decision, not an immediate runtime
feature:

* reject broader C `const` support now
* keep the current runtime boundary unchanged
* allow only the narrow `static const` / one-declarator / literal-only
  perimeter as a possible future implementation candidate
