# Written calls in erased statement operands

The complete 25,762-original remediation remains active. Classification v57 is
unchanged: **4,349 verified fixes, 680 separated inputs and 20,733 open files**.
This phase adds no verified file admissions. The operator's order is to finish
the current 278-file statement family, verify and stabilize Rust and TypeScript,
then resume the largest measured C/C++ groups.

## Shared production correction

The current source-selected statement adapter rejected every call-shaped argument
that was absent from the expanded assertion. In the actual map `max_size` test,
two `LIBCPP_ASSERT` invocations reach the host-library definition in
`test_macros.h:267`, which expands to `static_assert(true, "")`. The rejection
prevented complete indexing even though the written argument calls could be
retained separately.

C++ logical version 28 now supports complete argument erasure when the selected
replacement is still exactly one static assertion. It parses the entire original
invocation as a separate lexical view, preserving byte offsets, UTF-8 columns
and CRLF lines. Only call extraction visits the detached argument tree; erased
local declarations cannot enter the selected symbol inventory. Ordinary function
and method ownership, macro hints, following declarations and mixed generated
function declarations retain the established physical mapping.

For call-shaped operands, partial erasure, transformed tokens, stringification
and token paste remain explicit holds. Uncertain definitions, malformed lexical
arguments and replacement-added real calls also remain held. No compiler is invoked during indexing. The
analyzer distribution advances to 2.0.29 and the official bundle to 2.0.55;
schema, backend and generated-provenance versions are unchanged.

## Actual 278-file measurements

The frozen selection and original source hashes are preserved. Under the same
C++20 host-library/test-support profile, complete production results increase
from **51 to 187 of 278**, with zero capture exceptions. Before the change,
185 originals reported the shared erased-or-transformed argument diagnostic.
The increase is a production measurement, not native metadata qualification.

Independent source-owned native declaration capture accepts 129 originals and
holds 149, with no timeouts or capture exceptions. Native preprocessing origins
are captured for the same 129 positives. Supplemental native type-location
capture also succeeds for all 129, with exactly matching dependencies.

Eighty-six originals have complete production and native results after the
change. The unchanged independent metadata grader passes two and holds 84.
Neither positive has yet been admitted through actual CLI/storage proof.
Erased operands have no expression nodes in the compiler AST, while the
analyzer preserves their written lexical calls. Inactive source branches,
complex source-call projections, signatures and qualified inventories also
produce retained comparison holds. No missing compiler expression is treated
as evidence that the corresponding written source call should be deleted.

## Native context and broader roots

Native first-error clustering identifies 81 failures at `_S_copy_chars`,
19 pointer-conversion failures, ten `min_pointer<char>` conversion failures
and further related standard-library cases. Six actual representatives from
the largest first-error groups all compile using the existing generated
source-libc++ context. This verifies a native library-context cause for those
representatives; it does not classify the other 149 files or prove analyzer
correctness. The existing build is reused without rebuilding or changing the
original corpus.

A separate six-file analyzer profile captures the matching source headers and
uses independently queried generated configuration as forced-prefix evidence.
All six remain held: five encounter possible active error directives and one
exceeds the existing captured-file bound. A traced string test reaches
`remove_reference.h` with unknown `__has_builtin` results, even though the real
compiler reports `__remove_reference_t` available. The first possible error
occurs after 1,589 directives and 144 visits, within the existing event budget.

Native queries record 123 exact compiler feature results from the captured
headers. Numeric feature versions are preserved as literal values rather than
collapsed to Boolean truth. The initial Boolean-only exploratory substitution
is explicitly superseded and retained with its scope limitation.

A diagnostic-only replay, using exact native literals and checking unchanged
initial operator and argument bindings, applies 50 feature observations and
advances past that error. It then reaches a separate header-search uncertainty
in `__mbstate_t.h`, after 3,510 directives and 585 visits. `__has_include` and
`__has_include_next` depend on the including header and search position; global
feature answers cannot substitute for source-bound search observations. These
probes change no production selection or configuration and admit no files.

The next context work must address compiler feature and header-search evidence
at this shared level. Repeating per-file standard-library failures or treating
possible error branches as malformed inputs would not establish their cause.

## Validation and retained evidence

Eighty-three focused statement, projection and generated-analysis controls pass.
The quality preflight passes all nine checks, including Semgrep outside the
sandbox. The complete repository gate passes **2,745 tests, three skipped, 88%
coverage**, and indexes 914 files with zero failures or coverage issues.
All 213 prior statement admissions reproduce byte-identical metadata.
The earlier 1,350-original, two-profile regression also completes: all 2,700
cases remain complete and byte-identical, with zero exceptions and unchanged
source hashes. These regressions do not add new file admissions.

All evidence remains under the dedicated worktree's
`.artifacts/analysis/parser-diagnostics-20261017-r1/` directory:

- `cpp-erased-statement-implementation-r1`,
  `cpp-erased-statement-runtime-snapshot-r1`,
  `cpp-erased-statement-prior213-regression-r1`, and
  `cpp-erased-statement-prior1350-regression-r1`.
- `libcxx-statement-278-profile-capture-r1`,
  `libcxx-statement-278-readiness-r1/r2`,
  `libcxx-statement-278-native-inventory-r1`,
  `libcxx-statement-278-macro-capture-r1`,
  `libcxx-statement-129-native-type-expressions-r1`, and
  `libcxx-statement-native-grading-r1`.
- `libcxx-statement-278-root-ranking-r1`,
  `libcxx-statement-matching-library-probe-r1`,
  `libcxx-statement-matching-library-profile-probe-r1`,
  `libcxx-statement-matching-library-readiness-probe-r1`, and
  `libcxx-statement-matching-library-context-trace-r1`.
- `libcxx-statement-native-feature-query-r1/r2` and
  `libcxx-statement-native-feature-effect-probe-r1/r2`.

The source-bound gate log, exit status and named tmux session are retained under
`.artifacts/validation/repo-gates/cpp-erased-statement-r1.*`.
All raw and failed attempts remain immutable. No branch merge, push, main-tree
change or cleanup is part of this phase.
