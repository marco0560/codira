# LLVM include profile: 685 independently qualified original files

The dedicated worktree now records **1,444 verified parser fixes**, **453 separated
files** and **23,865 open paths**, across the original **25,762 diagnostic paths**.
This admission adds **685 original LLVM C++ headers**. All were previously open;
none was already counted or removed as a negative fixture. The complete current
ledger is `classification-v22.jsonl`, with its CSV and grouped summary under
`.artifacts/analysis/parser-diagnostics-20261017-r1/`.

The accounted population is **7.36%**, up from **4.70%**. That combines verified
fixes and separated files. Parser recovery measurements are reported separately
below and do not inflate the verified-fix ledger.

## Correction and exact analysis profile

The source include root `llvm/include` supplies declarations of annotation macros
that the original benchmark configuration could not resolve. Commit `6bd56ee`
exposes ordered, repository-contained include roots and binds their contents,
lookup order and negative lookups to reuse identity. The following profile is
relative to the unchanged LLVM repository root:

```toml
[plugins.analyzer-cpp]
include_search_paths = ["llvm/include"]
```

The complete production replay recovers parsing in **1,376 of 1,801** formerly
partial C++ public headers, with **425 still partial** and no exceptions. The
original campaign and corpus remain unchanged. This is an explicit corrected
profile, not a claim that the original default configuration or entire benchmark
now has complete coverage.

## Independent original-source evidence

All 1,376 originals were compiled in a host **C++17** syntax/AST consumer with
Clang **22.1.8**. The first configured native context accepted **1,010**, rejected
**366**, and had zero timeouts. Of those rejections, **363** named a missing
included input. The first missing inputs for **359 files** were `Attributes.inc`
or `GenVT.inc`.

A fresh isolated CMake configuration builds only the pinned source's declared
`intrinsics_gen` and `vt_gen` targets, including their native TableGen tool
prerequisites. That accepts **339 additional original headers**; **20** still
reject, with no timeouts. The previous configuration and all its responses remain
retained. This work does not modify or build inside the original corpus.

Across both explicit native contexts, **1,349 originals compile**. The unchanged
strict artifact comparison qualifies **685**, checking source-owned callable
definition identity, method kind, physical name line, mapped parameter names,
lexical body calls, named types and prototype/redeclaration-chain coverage.
The other **664 compiler-accepted files** retain mismatches or oracle limitations;
**27 files** remain rejected or lack the required native context. These held files
are not automatically classified as malformed or future syntax.

The admitted scope contains **846 definitions**, **5,677 callable records**,
**278 lexical calls** and **3,555 named type targets**. Constants, complete
signatures/visibility/attributes, fully qualified owner resolution, ABI/runtime
behavior and implicit constructor/operator lowering are outside this qualification.
It is not an end-to-end retrieval or runtime evaluation.

The complete current **C++16 analyzer output matches the frozen C++15 output
byte for byte for all 685 admitted paths**. The first 366 checks were inherited
only after validating identical current parser source digests and canonical
payloads; the other 319 originals were replayed through the actual production
analyzer. Every source and captured header digest was revalidated at admission.
The language/source version is not inferred from a header suffix: these are C++
headers checked in the recorded C++17 native profile. The ledger preserves each
source's original language-version/harness evidence separately.

## Keeping native verification bounded without changing its checks

The original full AST responses total approximately **415 GB uncompressed** for
the 1,010 accepted originals, with a median of **412 MB per header**. A local
Clang 22 frontend now emits complete native subtrees rooted in declarations from
the original main file; it independently traverses foreign declaration contexts.
It does not select declarations using production-analyzer results. Native parsing
still processes the whole translation unit. The same 1,010 originals yield
approximately **384 MB** of retained native AST data with zero compiler rejections
or timeouts; the full original responses remain retained.

Eight diverse complete comparison results first matched, including held failures
and limitations. A broader check covers **all 862 completed full-dump references**:
**840** match every reported field exactly; **21** differ only in ordering of
unordered Counter elements in missing/extra diagnostics. Sorting preserves their
multiplicity, parameter order, call coordinates and qualification verdicts.

One additional file, `llvm/Support/VirtualOutputError.h`, reports fewer repeated
limitations at identical source sites. Its **original full-dump record is retained
unchanged as authoritative**, and it stays unqualified. No admission uses its
reduced diagnostic list. No qualification verdict changes among the 862
references. The remaining **148** originals receive the same independent field
checks against the new native data. Raw failed comparisons and the explicit
review remain retained; none is silently overwritten as a passing raw comparison.

## Validation, remaining work and retained records

The final repository gate passes **2,133 tests**, with **3 skipped**, **87%
coverage**, and a fresh **839-file index** with zero failures or coverage issues.
Semgrep runs outside the sandbox and reports zero findings. Two preceding failed
gates exposed immediate process-state assumptions in lifecycle tests; commit
`a9f131b` replaces these with a shared bounded observer, preserving the original
deadlines and artifact checks. Its focused modules pass 60 tests and 30 repeated
real-process controls. Both failed gates remain retained.

Commit `bda922f` separately implements inline/constexpr object-macro recovery.
Its complete 2,359-path production comparison recovers **2,054 additional parses**
(966 libc files and 1,088 libc++ tests), with no exceptions. Those disjoint
recoveries remain outside this 685-file admission pending independent original
artifact qualification. See the [specifier-macro report](analyzer-parser-diagnostics-specifier-macros-2026-10-19.md).

The current separated population remains grouped by language, source/harness
version and repository in the [complete separation report](analyzer-parser-diagnostics-verify-prefixes-2026-10-19.md).
Remaining historical ownership is **5,897 C paths** and **17,968 C++ paths**.
The correction goal remains open; these results do not establish a global clean bill.

Durable evidence under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `llvm-include-profile-admission-r1.json`: source-bound per-file admission receipt;
- `classification-v22.jsonl`, `.csv`, and `classification-summary-v22.json`;
- `include-search-qualified-cpp16-r2/`: all 685 current-payload proofs;
- `include-search-native-originals-r1/`: original full native responses;
- `include-search-native-generated-r1/`: native responses with generated inputs;
- `include-search-native-filtered-r1/`: corresponding source-owned native data;
- `native-source-dump-reference-review-r1/`: explicit complete-reference review;
- `include-search-grading-generated-r1/`: unchanged strict comparison results;
- `native-source-dump-tool-r2/`: native tool source, binary and build receipt;
- `llvm-native-generators-inputs-r1.json`: pinned-source generation controls;
- `specifier-macros-validation-receipt-r1.json`: examined gate/source bindings.
