# C statement-prefix recovery — 2026-10-20

The dedicated worktree implements the shared PostgreSQL loop-prefix correction
identified in the [diagnosis](analyzer-parser-diagnostics-c-loop-prefix-diagnosis-2026-10-20.md).
The source batch is validated; cohort measurements and admission remain pending.

## Behavior

`c_statement_macros.py` recognizes fixed-arity function macros supplying literal,
balanced `for` headers before a written statement, including fixed-arity
forwarding aliases and nested header sequences. Every captured alternative must
have a compatible statement role and arity. Reaching source/header availability
is checked, and undefinitions, object/function conflicts and keyword overrides
invalidate the proof. No compiler conditions are selected or replacement bodies
expanded.

The grammar buffer substitutes an equal-width loop keyword at eligible call
nodes with a missing statement terminator. The artifact builder separately
retains the original macro name as a written call, alongside original argument
and body calls. Original source bytes, signatures and call coordinates remain
unchanged. Replacement-body locals and helper calls are not generated.

Only an entirely clean recovered tree is accepted. A negative control exposed
the provider treating an orphan `else` as a type name; loop recovery now holds
that case. A single bare-identifier macro argument followed by a block can
already parse as a nested function in the original provider. That baseline
behavior is not presented as an arity recovery; the wrong-arity rejection test
uses an invocation with an existing parser error instead.

Current conservative limits are names at least five bytes long, non-variadic
parameters, at most eight loop headers per replacement and 64 alias-resolution
passes. Unsupported shapes and unrelated parser errors remain held.

Logical C analyzer version **18**, distribution **2.0.8** and official bundle
**2.0.45** are aligned, including root dependency assertions and lockfile. The
C++ helper remains isolated from indexing pending its separate capability
decision.

## Verification so far

- 29 focused tests pass: UTF-8/CRLF positions, source calls and signatures,
  contained-header availability/invalidation, nested and unbraced statements,
  compatible conditional alternatives, bounds and conservative rejection cases.
- The initial C/bundle/root-contract batch passes 205 tests; four subsequent
  availability/bound controls are included in the 29-test focused result.
- All eight required preflight checks pass, including outside-sandbox Semgrep,
  typing and docstring audit. The fresh index has 880 files, zero failures and
  zero coverage issues.
- Actual public-analyzer controls recover four original files against the
  independently retained Clang AST/preprocessor evidence. The unchanged R9
  comparator fully matches the represented metadata in two cases and retains
  the other two for their existing limitations. Four missing-call/wrong-column
  counterfactuals are rejected. These are controls, not ledger admissions.

All **360 previously qualified C files preserve exact canonical artifact
equality and clean status**, under their recorded product profiles: 188 defaults
and 172 explicit header contexts. The source-bound receipt is
`c18-loop-prefix-prior-regression-receipt-r1.json`.

The complete 294-file recognized loop cohort is still being measured with
checkpoint/resume. Measurements compare the frozen analyzer v17 from commit
`2c517bf` with v18; candidate default and configured results are kept separate.
Canonical equality and parser cleanliness do not replace independent native
qualification.

One additional native-profile contrast checks PostgreSQL's source-declared
assertion-enabled mode. `configure.ac` defines `USE_ASSERT_CHECKING=1` for
`--enable-cassert`; disabled assertions otherwise erase argument calls such as
`get_ENR(...)`. Under that explicit validation mode, the unchanged
`queryenvironment.c` product artifact fully matches the unchanged R9 reference,
without issues or limitations. This single contrast is retained in
`c18-loop-prefix-assert-native-control-r1/`; it does not establish a population
gain or original project-harness equivalence.

The full repository gate passes: **2,430 tests, three skipped, 88% coverage**,
with a fresh **880-file index**, zero index failures and zero coverage issues.
Semgrep runs outside the sandbox. The source-bound result is retained in
`c18-loop-prefix-validation-receipt-r1.json`. After examination and reporting,
the successful named session and its temporary runner/log/status files were
cleaned under the repository's gate-retention rule. Corpus/native evidence is
unchanged; no new ledger admission follows from this gate alone.

## Evidence

Under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `c18-loop-prefix-native-controls-r1/`: retained QA assertion failure caused by
  comparing a tuple-valued new reference key with a previously serialized JSON
  list. No product mismatch was involved; its rejection receipt explains this.
- `c18-loop-prefix-native-controls-r2/`: JSON-normalized positive/held controls;
- `c18-loop-prefix-native-controls-r3/`: final source-bound controls and four
  explicit missing-call/wrong-column rejection controls;
- `c18-loop-prefix-c17-baseline-r1/`: immutable baseline package source;
- `c18-loop-prefix-production-r1/`: full input manifest, original source hashes,
  actual baseline/current artifacts, dependency identities and resumable records;
- `c18-loop-prefix-native-cohort-r1/run.py`: prepared resumable capture/comparison
  stage for every actual current-clean candidate. Baseline and source-declared
  assertion-enabled native modes are separate; a complete match is required
  within one mode, with no union of reference results;
- `c18-loop-prefix-gate-launch-r1.json`: exact full-gate session and file paths.

The ledger remains v37: **2,672 verified fixes, 453 separated and 22,637 open**.
