# C++ generated source projection — 2026-10-20

Following the [controlling-guard repair](analyzer-parser-diagnostics-cpp-guard-budget-2026-10-20.md),
the next [ADR-034](../adr/ADR-034-bounded-cpp-declaration-macro-analysis.md) integration
layer renders already selected macro tokens into a parser buffer. It retains
the exact original bytes and maps unchanged source intervals separately from
generated intervals. This is an internal projection layer; `CppAnalyzer` is
still not connected to declaration expansion, and no preprocessing profile is
exposed in configuration yet.

`cpp_macro_projection.py` accepts bounded, ordered, nonoverlapping complete
declaration invocations. It preserves preprocessing token identity, inherited
whitespace and attribute bracket adjacency. Additional separators prevent
accidentally creating operators, comments, identifiers, numeric tokens or
literal suffixes. Replacement boundary padding isolates generated tokens from
surrounding original bytes. Unsupported lexical forms remain explicit failures.
Limits cover source/output bytes, invocation count, replacement bytes and tokens.

Generated token ranges refer only to the projected buffer. Original invocation
or argument anchors remain distinct. A physical spelling range is supplied only
for a proven unmodified argument token; pasted, stringified and replacement-
template spellings have none. Spliced argument ranges preserve their physical
source bytes while retaining logical token spellings. Source-range mapping
accepts only nonempty intervals copied unchanged, so generated headers cannot
masquerade as physical declarations. Untouched bodies retain exact original
coordinates even when a multiline invocation is replaced by a different-length
single-line expansion. These records do not yet supply normalized artifact
provenance or macro derivation chains.

## Measured original-file behavior

`cpp-original-ceil-projection-r1/` reuses the independently captured native
initial states and retained native output without running a compiler during
projection. All 163 captured source/header hashes must match the preceding
readiness evidence. Both packaging modes produce a clean projected parse and
preserve the original wrapper/body preprocessing tokens. The lexical
`math::ceil(x)` body call maps to original bytes **522–535** in both modes.
This is parser, token and location evidence, not analyzer artifact qualification.

`cpp-generated-shape-readiness-r2/` measures the remaining extraction gap using
isolated exact native-preprocessed namespaces. Both parse cleanly, but public
packaging currently emits only the implementation definition; its `decltype`
prototype and alias are omitted. The earlier r1 synthetic probe inserted spaces
between all tokens and caused an attribute parser error. It remains retained
and is explicitly a renderer artifact, not proof of an original grammar defect.
Recovering callable `decltype` declarations must establish that the referenced
entity is a function; a variable's `decltype` is not sufficient.

The 29 projection controls cover lexical merging, native-shaped attributes,
UTF-8/CRLF and multiline bodies, spliced argument spelling, empty/multiple
expansions, generated versus physical locations, forged evidence and bounds.
The initial whitespace-count assertion failure is retained separately; the
corrected control checks token separation rather than a padding-space count.

Plugin distribution **2.0.22** and official bundle **2.0.48** include this layer;
logical analyzer behavior remains **22**. Classification v38 is unchanged:
**2,786 verified fixes, 453 separated inputs, 22,523 open files**. Production
configuration/context binding, explicit normalized generated provenance,
prototype/alias modeling, backend/query persistence and actual-file artifact
qualification in both packaging modes remain open.

Durable ignored evidence under
`.artifacts/analysis/parser-diagnostics-20261017-r1/` includes the original-file
projection, both shape probes, `cpp-generated-shape-findings-r1.json` and
`cpp-projection-focused-r1-failure.json`. The corrected focused package/bundle
suite passes **629 tests**. Both preflights pass all eight checks; r2 reruns
after staging to ensure fresh index and scan coverage of the new files.
The full gate exits **0** with **2,651 passed, three skipped**, **88%** coverage,
zero Semgrep findings, **891 indexed**, zero index failures and zero coverage
issues. `cpp-projection-gate-result-r1.json` retains its source-bound receipt.

## Next integrated delivery

The operator requested faster verified recovery. Further separately delivered
helper foundations are deferred in favor of a coherent production integration:
profile validation, captured context, normalized generated provenance,
prototype/alias extraction and backend/query persistence, followed by actual-file
qualification. The retained cohort check confirms all **1,607** LLVM libc
candidates remain open in v38 with zero source drift. Math contains **501 generic
files**, 42 AMDGPU files and 33 NVPTX files; the generic group is the next native
batch after the representative file passes both packaging modes.

`cpp-ceil-native-relationships-r1/` derives source-owned roles, unnamed versus
named parameters, alias linkage and physical body calls from retained native
ASTs. `cpp-ceil-filtered-native-r1/` uses Clang's qualified-name filtering and
matches the preceding full native declaration inventory. Its disabled/public
AST output is **8,771/19,443 bytes**, compared with **386,845,427/386,843,642 bytes**
for the retained unfiltered ASTs. Focused output is a measured scaling path,
not permission to omit namespace, provenance, dependency or semantic grading.
All full and filtered raw outputs remain retained.
