# Source-defined inline and constexpr macros

## Cause and correction

LLVM libc defines `LIBC_INLINE` as `inline`; libc++ test support defines
`TEST_CONSTEXPR` and its language-version variants as `constexpr` or an empty
replacement. The source-backed recovery accepted empty or attribute replacements,
but rejected these declaration specifiers even when the defining header was
resolved. The sixteen-path diagnostic probe recovered nine files by accepting
only the parsed `inline` storage specifier and `constexpr` qualifier, leaving
other type and linkage replacements unsupported. This probe is preliminary
modified-parser evidence, not production or semantic qualification.

The production parser now accepts these two specifiers and their attribute/alias
combinations. Observed macro overrides of these keyword spellings must resolve
through compatible source-backed aliases; unresolved overrides remain diagnosed.
All observed definitions must remain compatible, function-like
macros and `#undef` still invalidate a name, and uses must follow the source or
include definition boundary. Source coordinates and original macro spellings in
signatures remain intact; unrelated syntax errors retain the original tree.
This does not select compilation branches or perform general preprocessing.

## Profiles and measurement

The explicit roots are `libc` for libc sources and `libcxx/test/support` for libc++
tests, relative to the original LLVM repository. They are declared by
`libc/cmake/modules/LLVMLibCObjectRules.cmake` and libc++ test configurations. The
original corpus and campaign remain unchanged.

The complete resumable production comparison covers **2,359 pending paths**:
**1,066 libc paths** containing `LIBC_INLINE` and **1,293 libc++ test paths**
containing `TEST_CONSTEXPR`. It runs both the unmodified committed C++15 package
snapshot and the current C++16 analyzer with identical explicit roots, retaining
complete artifacts and dependency identities. This is a token-selected cohort,
not every file in either subtree. **2,054 paths become clean**, versus zero
under the old analyzer with the same roots; **305 remain partial**, with **zero
exceptions**. These are measured production results, separate from independent
semantic qualification.

The logical C++ identity advances to **16**, its distribution to **2.0.12**, and
the official bundle to **2.0.35**. No release is published.

## Validation and evidence

Focused production tests pass **78 tests**, covering constructors, signatures,
parameters, source call coordinates, compatible alternatives, aliases, and
rejection of type/linkage changes. Initial test attempts assumed a constructor
signature omitted its initializer and that parameters were objects; these fixture
assertions were corrected to the established contracts. Two additional negative
controls exposed unresolved keyword overrides; the production guard now preserves
those diagnostics. The preliminary full measurement was deliberately stopped
(exit 143) and its partial evidence retained before this change; the corrected
measurement uses a fresh identity. No production behavior
was changed to satisfy those assumptions. The corrected preflight passes all eight
checks, including Semgrep outside the sandbox with zero findings.

Independent Clang C++17 controls pass all **15 cases**: eight recovered cases
pass the unchanged strict extraction oracle, three invalid cases stay diagnosed,
and four valid but unsupported type/linkage/override cases remain conservatively
partial. These generated controls are not original-corpus qualification. The
first control attempt omitted a required oracle metadata key; its failure and
raw evidence are retained, and the corrected control run has a fresh identity.

The first full gate passed **2,132 tests**, with **3 skipped**, but failed an
immediate renderer-descendant process-state assertion. A focused rerun passed.
A thirty-attempt reproduction then observed fifteen transient nonterminal states
among twenty-seven started fixtures; all terminated within nine milliseconds.
Three fixtures had not reached readiness before the small renderer deadline.
The test now explicitly waits for dummy-fixture readiness before starting its
original renderer deadline and observes descendant termination with a bounded
wait. All mandatory artifact checks and both 0.2/0.3-second renderer deadlines
remain intact. Production renderer code is unchanged. Its focused module passes
all **17 tests**. Repeated controls also exposed a process disappearing during
a procfs read, now handled as termination. The second full gate passed **2,132
tests**, with **3 skipped**, but found the same immediate-state assumption in
the benchmark runner test. Both now use one shared bounded observer in
`conftest.py`; the combined focused modules pass **60 tests**, and all **30**
repetitions of their exact test bodies pass. Both failed gates remain retained.
The final full gate passes **2,133 tests**, with **3 skipped**, **87% coverage**,
and a fresh index of **839 files** with zero failures or coverage issues. This
independent test correction is kept separate from the parser fix.

Evidence is retained under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `specifier-macros-probe-r1/`: preliminary sixteen-path diagnostic projection;
- `specifier-macros-focused-r1.log` through `r4.log`: focused tests and corrections;
- `specifier-macros-override-control-r1.log`: failing keyword-override controls;
- `specifier-macros-baseline-r1/`: exact committed C++15 source snapshot;
- `specifier-macros-production-r1/`: retained interrupted preliminary comparison;
- `specifier-macros-production-r2/`: corrected resumable production comparison;
- `specifier-macros-native-controls-r2/`: independent generated compiler controls;
- `renderer-kill-window-r1/`: measured transient termination window;
- `process-lifecycle-focused-r2.log` and
  `process-lifecycle-repetitions-r2/`: corrected shared real-process controls;
- `specifier-macros-quality-r5.log`: final passing preflight;
- `specifier-macros-validation-receipt-r1.json`: examined passing full gate and
  source/evidence digests.

Independent Clang checks of the preceding include-root cohort identify **685**
qualified original paths against its frozen C++15 artifacts. Their complete
current-C++16 payload replay is a separate admission requirement. Neither measurement is a qualified global
clean bill. The ledger remains **759 verified fixes**, **453 separated files**
and **24,550 pending paths** until independent source-artifact admission.

Production results by explicit root:

| Profile root | Newly clean | Still partial |
| --- | ---: | ---: |
| `libc` | 966 | 100 |
| `libcxx/test/support` | 1088 | 205 |

A focused identity test also exposed installed/generated core-version drift
(`dev26` versus `dev27`) in this worktree. Offline synchronization using the
already-installed compatible build dependencies and the docs extra reconciles
the environment; the identity guard remains intact. Its failed attempts and
resolved commands are retained as `worktree-runtime-sync-r1` through `r3`.

Later source-bound admission is recorded in the [qualified LLVM include-profile
report](analyzer-parser-diagnostics-llvm-includes-qualified-2026-10-19.md). Earlier
ledger totals above are the phase snapshot, before that admission.
