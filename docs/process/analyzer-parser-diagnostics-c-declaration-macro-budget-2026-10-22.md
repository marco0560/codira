# C declaration macro token budget — 2026-10-22

The opt-in C declaration-macro pass could raise `ExpansionRejected` while
scanning a translation unit above its token budget. The exception escaped
`CAnalyzer.analyze_file`, so the public analyzer failed instead of returning
its ordinary parse result.

The analyzer now catches only this explicit bounded rejection at the public
analysis boundary. It leaves the ordinary artifacts and parser status intact,
adds a `declaration_macro_expansion` diagnostic with the fixed rejection
reason, marks coverage partial, and sets `index_symbols` false. Backends retain
the partial-coverage status while skipping symbols from a result whose
generated declarations were not completely checked. The default analyzer
path is unchanged. The configured bounds remain unchanged. C logical analyzer
version advances from 19 to 20, the C distribution from 2.0.9 to 2.0.10, and
the official bundle from 2.0.68 to 2.0.69 with exact pins and regenerated lock
data.

The original CPython case
`Modules/_testinternalcapi/test_cases.c.h` reproduced the exception through
the public API at `_scan_invocations` tokenization. After the fix, the same
source returns without an exception; the original `grammar_error` remains,
status adds the macro-budget reason, coverage remains partial, and symbol
indexing is disabled. The dedicated public-API test forces the same bounded
rejection with a lowered private test limit and checks that the ordinary parse
artifacts remain while persistence is gated. Existing tests continue to cover
normal positive and negative declaration-macro paths.

The terminal non-LLVM inventory contained 4,446 cases and 2,228 originals. Its
41 token-bound failures were PostgreSQL 21, CPython 16, Redis 3 and zlib 1.
This is a measured error count, not a qualification or fix count. The public
API sweep returned for all 41, preserved source/parser output under matching
include context, marked each result partial with the macro-rejection diagnostic
and disabled symbol indexing. No fallback result qualifies a whole file, and
no classification ledger rows were changed. Source-bound inputs, per-case
receipts, comparison results and validation records are retained in the
immutable `CAMP/worker-deliveries/c-budget-reset-r1/` evidence directory.
