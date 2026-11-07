# Bounded C++ SDK capture capacity

The full 25,762-original remediation remains active. Classification v60 is
unchanged at this code-change boundary: 4,374 verified fixes, 680 separated
inputs and 20,708 open files. The original v38 ledger remains immutable.

## Measured shared constraint

The original 278-file libc++ statement family requires static graphs of up to
1,341 headers plus the translation unit. Static capture is distinct from the
active preprocessing walk. Raising only the capture ceiling exposed a second
independent directive-event ceiling in all nine measured SDK cases. Their
successful diagnostic walks consumed 16,898–17,084 events, 837–846 visits and
approximately 3.3–3.4 MB, with 1,158–1,165 captured buffers.

The C++ analyzer now admits at most 2,048 captured buffers and 32,768 directive
events. Both public macro selection and generated analysis share the capture
ceiling. Active traversal remains bounded at 1,024 visits, 8 MiB, 64 include
levels and 4,096 bindings. No production include cache is introduced.

Logical analyzer version 32, analyzer distribution 2.0.33 and official bundle
2.0.59 identify the change. Package pins and lock data advance together.

## Qualification and limits

All 278 original files have source-bound complete SDK captures. Fresh compiler
queries cover the complete 1,907-source catalog under separate exact C++20 and
C++26 native prefixes. C++26 source ASTs, macro origins and supplemental type
operands are complete for 276 originals; two native-negative cases remain open.
No malformed or future-syntax decisions follow from those failures.

Production analysis completes for 218 of 278 originals. Independent metadata
comparison passes 145, including 122 still-open ledger rows. The other 73
metadata holds and 60 production holds are retained individually. Passing this
comparison alone does not admit a fix: actual original-file CLI indexing,
persisted metadata under SQLite and DuckDB, the full repository gate, committed
source binding and an independent admission audit are required.

The QA-only r18 native call helper distinguishes physically proven dependent
infix operators from lexical calls, preserving explicit operator calls and
nested calls. Three native positives, 18 corruptions and replays of prior
object/member/argument controls validate the oracle extension; they count as
zero file fixes. Ten further metadata corruptions are rejected through the
current full grader and rendering-policy checks.

Focused checks passed 153 tests; the C++ package passed 804 tests and workflow
preflight passed. Earlier failed boundary fixtures and diagnostic runners remain
retained. The prior 213-file regression and a 108-case cohort sample produce
identical metadata; the latter is not a full historical-cohort rerun.

The 278-case production runner failed in its reporting footer after saving every
analysis. Its exit and raw log remain failed and immutable. A separate successful
postflight verifies every output, producer hash and complete source catalog.
The grader consumes that receipt explicitly. Its first obsolete prerequisite
failure is also retained; the corrected grader has a fresh run identity.

## Durable evidence

All paths below are relative to
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `libcxx-statement-278-sdk-include-contexts-r1/`
- `cpp-sdk-capture-capacity-probe-r1/`, `r2/` and `r3/` with their full names
- `cpp-capture-capacity-integration-r1/`
- `libcxx-statement-278-cpp26-prefix-r2/` and `libcxx-statement-278-cpp20-prefix-r2/`
- `libcxx-statement-278-cpp26-query-profiles-r1/` and `r2/` with their full names
- `libcxx-statement-278-cpp26-readiness-r1/`
- `libcxx-statement-278-cpp26-readiness-postflight-r1/`
- `libcxx-statement-278-cpp26-grading-r1/` and `r2/` with their full names
- `libcxx-statement-276-cpp26-macros-r1/` and `libcxx-statement-276-cpp26-types-r1/`
- `cpp-native-dependent-infix-controls-r1/` and `cpp-native-infix-*-replay-r1/`
- `libcxx-statement-cpp32-qualified-cli-r1/`
- `libcxx-statement-cpp32-index-verification-r1/`
- `libcxx-statement-cpp32-qualification-controls-r1/`
- `cpp32-statement-278-hold-ranking-r1/`

The full gate uses `.artifacts/validation/repo-gates/cpp-capture-capacity-r1.*`.
Follow-up diagnostics already reproduce a silent declaration/initializer
ambiguity and trace platform-header context failures. These remain separate
from this bounded-capacity change. Continue the statement group, then the Rust
and TypeScript closure audits, then the largest remaining C/C++ groups.
