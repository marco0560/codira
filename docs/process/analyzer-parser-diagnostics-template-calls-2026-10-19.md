# C++ template-call targets and named casts

The dedicated fix branch corrects three related call-extraction errors:

| Source expression | Previous artifact | Corrected artifact |
| --- | --- | --- |
| `f<int>(value)` | Unresolved call | Named target `f<int>` |
| `api::f<api::Box<int>>(value)` | Base `api::f<api`, target `Box<int>>` | Base `api`, target `f<api::Box<int>>` |
| `static_cast<int>(get<int>(value))` | Additional unresolved cast call | Only the real operand call `get<int>` |

Qualified targets now follow the parser's scope/name fields. Namespace
separators inside template arguments remain in their owning component, including
nested template scopes, shift expressions, literal text and original whitespace.
Unqualified explicit templates follow the named-call path. The four reserved
named cast keywords are excluded from call records; body traversal still retains
calls inside their operands. Constructor-like calls and similarly named ordinary
functions remain present.

This changes extracted artifacts, so logical C++ analyzer version advances to
**18**, distribution **2.0.14**, and official bundle **2.0.37**. Root and bundle
pins and the lock are aligned. There is no new compiler runtime dependency and no
new configuration. The underlying namespace/include profile remains the explicit
source-supported profile documented in the
[namespace report](analyzer-parser-diagnostics-namespace-qualified-2026-10-19.md).
The implementation follows the already selected portable parser architecture.

## Focused and native checks

Fifteen new regression cases verify unqualified and nested-qualified template
calls, global qualification, argument expressions/literals/spacing, original
UTF-8 byte columns, CRLF lines, nested calls through mapped namespace macros,
constructor-like calls, similarly named functions, and all four named casts.
The combined C++, bundle, installer, contracts and benchmark-runner surface
passes **332 tests**. The inexpensive preflight passes all eight checks, including
fresh-index docstrings, typing and Semgrep; Semgrep runs outside the sandbox.

Five actual native template controls now qualify, including the two controls
that previously reproduced the unqualified and nested-target defects. Seven
counterfactual wrong-artifact controls continue to reject altered template
arguments, namespace bases, targets, lines, columns, missing calls and extra
calls. Four retained accepted native cast expressions independently agree with
the corrected production artifacts: all four real operand calls remain and all
four false cast-call records disappear. These checks do not substitute for the
original-file comparison below.

## Original-file measurement

The current production replay covers all **928 original files** from the preceding
namespace cohort under the same include/namespace profile. It retains complete
canonical artifacts, original source hashes, captured include identities, current
implementation hashes and exact previous-payload comparison. Four workers and
checkpoint/resume with skip-completed behavior are used. The original corpus and
all preceding run identities remain unchanged.

Independent grading uses the **unchanged native R4 reference** and retained
original-source native ASTs. This phase does not add a new reference mapping or
remove a call to fit an incomplete reference. The complete replay has **928 clean parses and zero exceptions**. The unchanged
R4 comparison qualifies **612**, including all **465** previously qualified
namespace files and **147 newly qualified originals**; **316 remain held**. There
are **zero qualification regressions**. The new subset matches **212 definitions,
213 callables, one prototype parameter list, 790 lexical calls and 319 named-type
identities**. This confirms the earlier 147-file prioritization estimate using
actual current artifacts, rather than admitting the counterfactual.

The 685 qualified LLVM include-profile headers and three qualified specifier
files retain complete canonical artifact equality. Of the 465 qualified namespace
files, **464** remain byte-identical. One changes intentionally:
`libc/src/stdlib/exit_handler.h`, function `__llvm_libc::stdc_at_exit_func`, line 45,
column 2. The previous artifact recorded two identical unresolved entries for
`reinterpret_cast<...>(callback)(param)`: the cast and the real indirect call. The
current artifact removes exactly one entry and preserves every other field. The
original native AST independently contains one cast and one real call at that
position, and the complete current native comparison qualifies the file again.

The capture script initially exited 1 because it required all 465 previous
payloads to remain identical. All 928 captures were already complete. That failed
expectation and its output are retained; a separate source-bound review proves
the sole intentional change before full native grading proceeds. The capture was
not restarted or relabeled successful. No production correction or reference
relaxation was needed.

The full repository gate passes **2,176 tests with 3 skipped**, **87%** aggregate
coverage, and a fresh **848-file index** without failures or coverage issues. The
source-bound receipt covers the unchanged runtime, package pins, lock and tests.
Commit `86836e0` records the implementation and validation. A separate
source-bound admission now records all **147** newly qualified originals in v25.
The qualification scope is unchanged from the namespace admission: checked
artifact fields and explicit native/include profiles do not establish runtime or
original test-harness equivalence, or a clean default full benchmark.

## Evidence

The durable analysis root is
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `template-calls-focused-r1.log/.exit`, `template-calls-focused-r2.log/.exit`:
  new regression cases and the complete focused surface.
- `template-calls-quality-r1.log/.exit`: successful eight-check preflight.
- `template-calls-native-controls-r1/`: five actual native template cases and
  seven wrong-artifact rejection controls.
- `named-cast-native-fixed-r1/`: four real native cast/operand comparisons.
- `template-calls-production-cpp18-r1/`: current complete production artifacts
  and previous canonical payload equality.
- `template-calls-production-review-r1.json`: exact intentional prior-artifact
  change, original failed capture status, native cast/call proof and requalification.
- `template-calls-grading-cpp18-r1/`: unchanged-R4 native comparison results.
- `template-calls-validation-receipt-r1.json`: full gate and frozen source binding.
- `include-search-qualified-cpp18-r1/`, `specifier-qualified-cpp18-r1/`:
  previous-qualification complete artifact replay.
- `template-and-cast-next-fix-impact-r1.json`: prior 147-file counterfactual.

The authoritative ledger is now **v25: 2,059 verified fixes, 453 separately
classified files, and 23,250 open paths**, or **9.75% accounted**, up from **9.18%**.
Remaining historical ownership is **5,897 C** and **17,353 C++** files. The
separated language/version/repository records remain intact. The full objective
remains open. Complete v25 JSONL/CSV and grouped summary, the generator
`admit_template_calls_cpp18_r1.py`, and `template-calls-admission-r1.json` retain
the source-bound admission evidence. The successful completed gate session and
its temporary files were cleaned after examination/reporting; its durable receipt
and all failed capture evidence remain retained.

A separate 15-file C API-macro cause probe retains two clean and thirteen partial
current artifacts. Actual error spans include record-layout macros, export
annotations, statement/loop macros and includes inside initializers. Token
frequency alone does not establish the cause: `PyAPI_FUNC` is present in some
clean files as well. The complete 5,897-file pending-C token census and this probe
are retained in `c-shared-macro-census-r1.json`, `c-shared-macros-probe-r1/` and
`c-shared-macro-error-spans-r1.json`; they do not change classification or admit
files. Further corrections should target demonstrated shared causes.

The follow-up construct census is retained in
`c-shared-constructs-census-r1.json`. It follows actual error-span mechanisms,
while keeping token overlap separate from demonstrated parser recovery.
