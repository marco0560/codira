# Source-evaluated C++ conditional visibility

The full 25,762-original remediation remains unfinished. Its immutable v38
baseline is preserved. Before this admission boundary, v61 records 4,496 verified
fixes, 680 separated inputs and 20,586 open files. The operator requested a pause
after completing and committing this conditional-visibility change, before
choosing a different remediation strategy.

## Shared cause and implementation

The ordered source-context evaluator already establishes conditional activity
under an explicit preprocessing profile. Previously, ordinary syntax and
macro-generated parser views still contained directives and inactive content in
grammar positions the provider cannot parse, including initializer lists.

The primary walk now retains bounded activity intervals without copying macro
environments. A separate projection blanks known inactive content and conditional
markers while preserving CRLF, byte offsets and original source buffers. Any
unknown root activity conservatively retains the original view. No compiler runs,
external header reads or native branch answers are added to indexing.

Coordinate intervals include licensed blanks; unchanged-spelling intervals do
not. Generated token origins and lexical macro arguments remain separate. Both
ordinary and generated analysis consume the view. Original declaration-prefix
recovery stops at preceding directives instead of treating a masked `#endif` as
part of a following template signature.

The existing static contract for a proven guarded runtime continuation retains
both statement arms, even when the inner preprocessing guard is false. Existing
ownership checks supply only these bounded retained regions; an inactive outer
region still disappears. Comment summaries and Doxygen attachment are captured
from the unmasked syntax in the same coordinate space, preserving directive
barriers and trailing comments independently of selected syntax visibility.

The C++ logical analyzer advances to 33, its distribution to 2.0.34 and the
official bundle to 2.0.60, with coordinated pins and lockfile changes.

## Verification and retained evidence

The C++ and bundle suites pass 821 tests. New controls cover ordinary and
statement-generated branches, variable-width generated namespaces, unchanged
physical calls and signatures, UTF8/CRLF mapping, unknown and unreachable
conditions, malformed active syntax, invalid or overlapping projection evidence,
default unconfigured behavior, static continuation ownership and comment/Doxygen
attachment. A formerly held known intrinsic condition now licenses root visibility;
unrelated active grammar errors remain diagnosed.

The 213 earlier admitted statement originals remain byte-identical after the
comment-ownership correction. A deterministic 108-case sample covers earlier
declaration-macro cohorts in both packaging modes; its complete retained receipt
defines the scope and is not a full 1,350-file regression.

Durable paths below are relative to
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `cpp33-package-tests-r4.log`, `cpp33-activity-preflight-r2.log`
- `cpp33-prior213-regression-r2/`
- `cpp33-prior-cohort-sample-regression-r2/`
- `libcxx-platform-cpp33-readiness-r2/`
- `libcxx-platform-cpp33-grading-r2/`
- `libcxx-platform-cpp33-qualification-controls-r1/`
- `libcxx-platform-cpp33-qualified-cli-r1/`
- `libcxx-platform-cpp33-index-verification-r1/`

The 17-file actual-original run reuses the existing exact C++26 prefix, native
ASTs, macro origins, type operands and source/dependency snapshots. It does not
recapture or overwrite them. Native metadata, source rendering classifiers,
negative controls and complete persisted SQLite/DuckDB metadata are independent
requirements. Already-fixed originals, prototypes and clean trees add no fixes.

The full outside-sandbox gate runs in named tmux session
`codira-cpp33-root-visibility-r1`, with its log, exit and launch record under
`.artifacts/validation/repo-gates/`. Final admission requires the terminal gate
result and committed-source binding, retained separately in
`cpp33-root-visibility-integration-r1/` and
`cpp33-root-visibility-commit-binding-r1.json`. All failed attempts and raw
measurements remain evidence; they are not replaced by passing attempts.
