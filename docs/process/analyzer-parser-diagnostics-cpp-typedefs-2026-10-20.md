# C++ typedef extraction correction — 2026-10-20

## Shared cause and priority

The starting ledger was classification v35: **2,628 verified fixes, 453
separated, 22,681 open** (C 5,725; C++ 16,956). Classification v36 now has **2,669 verified fixes, 453 separated and 22,640
open** (C 5,725; C++ 16,915), or **12.12% accounted**. Source commit: `ddff8a2`.
The source gate, regression replay, native qualification and admission are complete.

A prioritized inventory found `typedef` tokens in 2,763 pending C++ originals
across seven repositories. This is a token footprint, not a recovery estimate:
LLVM 2,629; PostgreSQL 106; Redis 13; CPython seven; zlib four; fmt three;
VictoriaMetrics one. The analyzer already collected `using` aliases but omitted
ordinary typedef aliases at module and class scope. The concrete native-valid
LLVM header `llvm/include/llvm/DebugInfo/GSYM/LineTable.h` was held solely because
`llvm::gsym::LineTable::Collection` was missing. Its source uses
`typedef std::vector<gsym::LineEntry> Collection;`.

The correction enumerates every typedef declarator and follows only its
name-bearing chain, preserving pointers, references, arrays and callback forms
without leaking names from parameter or underlying-type subtrees. Module and
class typedefs become existing `typedef` declaration artifacts with qualified
names, stable identities and original declaration signatures. Declared records
remain represented; function-local aliases retain the established module-level
artifact boundary. Function typedefs do not become callable definitions.

Logical C++ analyzer version 21, distribution 2.0.17 and official bundle 2.0.42
are aligned with root pins, lock and package contracts. Main remains untouched.

## Validation in progress

Fifteen new focused cases pass, covering multiple declarators, callbacks,
function typedefs, pointer/reference/array forms, templates, named/anonymous
records, module/class ownership, local exclusions, namespace projection,
UTF-8/CRLF metadata, stable IDs and unchanged callable extraction. The broader
C++/bundle/root contract run passed 358 tests. Preflight caught one provider-node
union typing error; its failed evidence remains retained. The corrected helper
passes typing across all 12 source files and the focused tests. The second
preflight passed all eight checks, including Semgrep outside the sandbox.

Fresh independent controls qualify 42 positive native cases, retain three known
held cases and reject all 32 negative cases, including missing/extra/wrong
name/kind/line typedef artifacts. A source-bound proof checks the original
LineTable header: exactly the missing typedef is added and all existing output
fields and declarations remain unchanged. The original native context is C++17;
this does not infer the minimum language version of every affected source.

The full gate passed: **2,330 tests passed, three skipped, 87% coverage**, a
fresh 869-file index, zero index failures and zero coverage issues. Semgrep ran
outside the sandbox. `cpp21-typedef-validation-receipt-r1.json` binds the examined
result to source digests. The examined successful gate session and its three temporary validation files
were cleaned; compact receipt and all campaign/native evidence remain retained.

The fresh replay completed all 861 distinct requests. All 397 previously
admitted requests completed: 396 payloads are byte-identical; one, modern
`__optional/hash.h`, gains exactly the two omitted `argument_type`/`result_type`
typedefs and preserves every existing field/declaration. The source condition
explicitly enables these aliases for C++17 or the removed-binder compatibility
flag. Complete native comparisons qualify the updated output in C++17 mode;
the C++23 comparison remains rejected with exactly those two extra aliases.
Both modes and the explicit requalification are retained. No mismatch is waived.
The remaining 16 replay execution exceptions stay open.

Independent comparisons cover 274 legacy, 61 targeted modern and 80 LLVM header
outputs. Qualified totals are 158, 32 and 21 respectively; all prior compared
qualifications are preserved. The source21 typedef change contributes 26 new
file qualifications: 18 legacy, two targeted modern and six LLVM headers.
Another 15 LLVM headers qualify under the configured include profile with
payloads unchanged relative the retained source20 configured replay. These
profile qualifications are distinguished from new product corrections.
Overall, 41 pending originals qualify for admission, plus one existing row is
requalified against its explicit C++17 context. Classification v36 admits those 41 paths and requalifies the existing row;
all other rows are unchanged.

## Broader LLVM header context

A spread sample of 16 pending LLVM headers produced eight clean parses under
`include_search_paths = ["llvm/include"]`. Six compiled after configuring native
headers from the exact original LLVM checkout. The other two initially needed
`llvm/IR/Attributes.inc`; the retained configure plus `intrinsics_gen` build now
provides the source-generated declaration context without altering the corpus.
Six original artifact comparisons remained held, exposing metadata/evaluator
gaps rather than proving a fix from clean parsing alone.

The larger source20 diagnostic replay was deliberately stopped at its retained
checkpoint after this shared typedef cause was confirmed: 144 completed requests,
77 clean, 67 partial, no execution exceptions. Its operator-stop record and raw
outputs remain intact. The initial source21 replay was likewise stopped before
the preflight typing correction; corrected runs use fresh immutable identities.
Neither interruption is classified as a product failure or a completed replay.

## Evidence

All records are under the dedicated worktree's
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `cpp-typedef-prioritization-r1.json`, `cpp21-prioritization-r1.json`;
- `cpp-llvm-header-profile-probe-r1/`, `cpp-llvm-header-native-probe-r1/`,
  `cpp-llvm-header-native-reference-r1/`, `cpp-llvm-header-grading-probe-r1/`;
- `cpp-llvm-header-partial-errors-r1/`, including generated-include and annotation
  failures that remain open;
- `native-llvm-header-build-context-r1/`, with exact configure/build commands,
  native logs and generated-header hash receipt;
- `cpp-llvm-header-profile-replay-r1/operator-stop-r1.json`;
- `cpp21-typedef-focused-r1.log/.exit`;
- `cpp21-typedef-preflight-r1.log/.exit` (failed typing) and `r2` (all checks pass);
- `cpp21-typedef-native-controls-r1/` and `r2/`,
  `cpp21-typedef-negative-controls-r1/` and `r2/`;
- `cpp21-typedef-original-proof-r1/`, `cpp21-typedef-original-grading-r1/`;
- `cpp21-typedef-production-r1/` (stopped before typing edit), and fresh `r2/`;
- `cpp21-typedef-gate-launch-r1.json` (source-bound running gate).

## Completed native context replay

All 83 clean LLVM outputs from the 157 measured LLVM-header requests received a
native capture attempt against the original source-generated C++17 context.
Eighty have complete AST/preprocessing/written-call evidence; 21 pass the full
comparison. The other 59 retain metadata/evidence mismatches. Three native
failures are `Analysis/MLInlineAdvisor.h`, `Analysis/ReplayInlineAdvisor.h` and
`Analysis/TargetLibraryInfo.h`: all need generated
`llvm/Analysis/TargetLibraryInfo.inc`. They remain open as context gaps, not
malformed or future-syntax classifications.

Additional durable evidence: `cpp21-typedef-production-r2/summary.json`,
`cpp21-typedef-{legacy,modern,llvm}-native-r1/` and corresponding grading dirs,
`cpp21-llvm-header-native-r1/`, `cpp21-llvm-header-grading-r1/`,
`cpp21-llvm-header-before-after-r1.json`,
`cpp21-typedef-prior-qualification-review-r1.json`,
`cpp21-optional-hash-delta-r1.json`, both
`cpp21-optional-hash-{cpp17,cpp23}-r2/` native captures and matching grading dirs,
and the examined source-bound validation receipt.

## Final admission and retained limits

`cpp21-typedef-admission-r1.json` binds all new qualifications to `ddff8a2`,
source/header/native/tool hashes and the successful full gate. The explicit
ledger audit in `cpp21-typedef-ledger-invariants-r1.json` proves that exactly 41
open rows become verified fixes, one existing row changes its measured context
and evidence, and all other 25,720 rows remain unchanged. No malformed/future
classification changes in this batch. The [complete separated population by
language, version and repository](analyzer-parser-diagnostics-verify-prefixes-2026-10-19.md#complete-separated-population-by-language-version-and-repository)
still contains 453 files; current complete totals/groups are in
`classification-v36.jsonl/.csv` and `classification-summary-v36.json`.

| Language | Measured native context | Repository | New typedef fixes | New include-profile qualifications |
| --- | --- | --- | ---: | ---: |
| C++ | C++03, explicit legacy libc++/ABI profile | LLVM | 18 | 0 |
| C++ | C++23, explicit modern libc++/ABI profile | LLVM | 2 | 0 |
| C++ | C++17, LLVM source/generated configuration | LLVM | 6 | 15 |

The separately requalified existing `__optional/hash.h` row uses C++17 with its
libc++/ABI profile; it does not add another fixed-file count. These contexts
state what was independently measured, not inferred minimum language versions.
Full native signatures/attributes, data fields, ABI/runtime behavior and original
project-harness equivalence remain outside this artifact comparison.

The 2,763-file typedef footprint remains a prioritization aid. Files containing
a typedef are not counted as corrected unless their complete output qualifies.
Remaining gaps include generated native dependencies, template/call metadata,
conditional declarations and parser adaptation. The retained
`cpp-defaulted-callable-reproduction-r1/` is a concrete next candidate: native-valid
defaulted/deleted methods are represented without definition end positions;
no correction for that separate issue is claimed here.
