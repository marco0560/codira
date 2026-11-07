# Namespace macro expansion: portable source mapping

The selected implementation is **A: portable tree-sitter expansion with original
source mapping**. Native Clang remains an independent validation tool. The
dedicated fix branch adds no compiler dependency to runtime analysis.

The first implementation recovers source-proven object macros opening or closing
namespaces, including nested inline namespaces and aliases. All captured
alternatives must resolve identically. The parser sees expanded bytes; extraction
retains original function signatures, byte columns, line numbers and following
global scopes. Namespace identities use the expanded names. Directives, comments
and literals remain protected, and uses cannot precede reaching definitions.

Undefinitions, function macros, conflicting alternatives, unresolved uppercase
namespace names and expansions over 4096 bytes remain held. Recovery requires a
wholly clean final tree. Logical C++ analyzer version advances from 16 to 17;
distribution 2.0.13 and official bundle 2.0.36 invalidate stale analysis and keep
installation pins aligned. Installer 2.0.4 distributes the updated schema/catalog;
the bundle now pins that installer version as well.

The same implementation adds explicit `namespace_macro_definitions` for namespace
declaration names. The source-supported LLVM libc profile is:

```toml
[plugins.analyzer-cpp]
include_search_paths = ["libc"]
namespace_macro_definitions = { LIBC_NAMESPACE = "__llvm_libc" }
```

This matches the explicit override retained in the independent native profile.
`libc/CMakeLists.txt` declares the configurable namespace and
`libc/src/__support/macros/config.h` supplies attribute-compatible
`LIBC_NAMESPACE_DECL` aliases. Binding names and values are single identifiers;
source conflicts and ambiguous aliases fail explicitly. Configuration and header
contents participate in reuse identity. This binds namespace declaration names;
it does not evaluate branches or expand arbitrary expressions. Composing it with
an already expanded variable-width scope wrapper remains held.

## Evidence and limits

Twelve new regression cases cover original positions with UTF-8 and CRLF input,
namespace and ABI ownership, aliases supplied by headers, compatible branches,
late definitions, undefinitions, keyword overrides, malformed bodies and invalid
mapping ranges. The initial scope-wrapper suite passes **210 tests**. Three independent native
controls agree on qualified function identities, lines and parameter names;
call columns also point at the original source tokens.

Sixteen namespace-profile tests cover configuration validation, source overrides,
alias availability, ambiguous branches and cache identity. The C++ package suite
passes **226 tests**; the combined C++, bundle, installer, contract and runner
surface passes **317**. A 12-original public-analyzer probe resolves every tested
libc namespace alias and agrees with the retained native namespace expansion
locations and names. The complete 928-original production replay now has
**928 clean parses, 928 expected namespaces, no unresolved aliases and no
exceptions**. Complete native artifact grading qualifies **279**, holding **649**.
The reference R2 comparison qualifies zero of these new artifacts because it
cannot map the macro namespace identity. The R3 comparison extends only this
coverage: it requires the explicit compiler definition, command-line spelling
origin, exact source invocation and original namespace range. All callable,
parameter, lexical-call, prototype and other type checks remain in force. Three
actual native controls and seven deliberately wrong-artifact controls all pass;
wrong namespace identities, lines, parameters and extra calls remain rejected.
The other three earlier specifier-qualified originals retain exact complete
artifact equality under version 17. These 282 files await separate ledger admission.

The remaining ledger contains **1,439 paths** whose source mentions
`_LIBCPP_BEGIN_NAMESPACE_STD`. This is token overlap, not a causal fix count. A
spread probe of **16 originals**, with explicit `libcxx/include` and
`libcxx/test/support` roots, recovers **0**. Their include graphs retain missing
`__config_site` lookups. The generated ABI namespace and function-like pragma
helpers require further source/context handling; this implementation does not
invent a namespace or choose a conditional branch. No broad replay is justified
until those shared blockers are resolved.

The independent native capture of the earlier **2,054 specifier-macro recoveries**
has also finished: **1,824 compile**, **230 reject**, and **0 time out**. Unchanged
strict comparisons process all 1,824 without exceptions and qualify only **3**.
Held records include lexical-call mismatches (1,436), named-type identity
mismatches (1,004), macro/type mapping limits and other identity differences.
These groups overlap. Source constructor/unevaluated-expression coverage and
unresolved namespace aliases need cause-specific review; compiler acceptance
does not establish artifact correctness, and held records do not establish
malformed source. The three records have not been admitted to the global ledger.

At this feature-validation boundary, the authoritative ledger remains **v22: 1,444 verified fixes, 453 separated,
23,865 open, 7.36% accounted**. The 282 newly qualified originals await source-bound admission;
the 928 clean parses are not a 928-file fix claim. The full parser-diagnostic goal remains open.

The complete repository gate passes **2,161 tests with 3 skipped**, 87% aggregate
coverage, and a fresh 845-file index with no failures or coverage issues. The
final inexpensive preflight passes all eight checks; Semgrep runs outside the
sandbox. An actual registry/configuration/SQLite smoke check indexes both source
and header, reuses both unchanged, then rebuilds both when the namespace binding
changes; the old qualified name disappears and the new one is queryable. Its
first fixture location under ignored `.artifacts` was excluded by the scanner;
the corrected disposable fixture uses the prescribed temporary directory and
retains results in durable analysis storage.

The first full gate failed one resume-identity unit test because a preceding
production version-provenance guard rejected the setup before the intended
identity check. Commit `de3a365` isolates that unit test's provenance precondition;
the production guard and its dedicated mismatch test remain unchanged. The
failed gate is retained, and the second complete gate above passes. The transient
version discrepancy's specific cause has not been established.

Evidence is retained under
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `cpp-macro-context-decision-r1.json`: user choice A.
- `namespace-projection-prototype-r1/`: variable-width mapping probe.
- `namespace-native-controls-r2/`: three native comparison controls. The failed
  r1 record is retained; it incorrectly compared analyzer prototypes against a
  definitions-only native selection, corrected in r2 by comparing both.
- `namespace-originals-probe-r1/`: source-bound 16-file original probe.
- `specifier-original-native-r2/`: complete 2,054-file native capture.
- `specifier-original-grading-r1/`: unchanged strict comparisons and held groups.
- `namespace-macros-quality-r1.log`: initial successful inexpensive preflight;
  the final gate receipt records validation of the complete staged change.

- `namespace-macros-validation-receipt-r1.json`: complete gate/source binding.
- `namespace-profile-production-r1/`: all 928 current production artifacts.
- `include-search-qualified-cpp17-r2/`: 685 complete artifacts unchanged.
- `specifier-qualified-cpp17-r1/`: three earlier native-qualified artifacts unchanged.
- `namespace-profile-index-smoke-r2/`: actual SQLite configuration/invalidation check.
- `namespace-profile-grading-r1/`: all 928 comparisons with retained R2 reference grades.
- `namespace-oracle-controls-r2/` and `namespace-oracle-review-r1.json`: bounded namespace-proof extension controls.
