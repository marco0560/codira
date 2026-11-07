# C++ constructor argument calls — 2026-10-20

## Shared parser cause and bounded fix

Actual LLVM `vsscanf.cpp` constructs a local `StringReader` with `buffer` and `cpp::numeric_limits<size_t>::max()` as arguments. Tree-sitter represents the ambiguous initializer as a function declarator, so ordinary call-expression traversal omits `max()`. Independent native controls reproduce the missing call and distinguish a valid local function declaration of the same syntactic shape.

The analyzer now reparses initializer arguments only when an explicit value parameter proves that the first argument cannot be a type in the function's outermost block. It excludes nested scopes, where a type could shadow that parameter. The declared variable and synthetic wrapper acquire no call records. Existing extraction handles nested calls and named casts; recovered calls retain original UTF-8/CRLF byte positions and surrounding order, without duplicating existing calls. Unproven ambiguities retain the previous conservative behavior.

C++ logical analyzer version advances to 25, distribution to 2.0.25 and the official bundle to 2.0.51. Root pins and contract expectations follow. Installer catalog regeneration makes no change; core logical schema 24, backend physical schemas 28 and provenance format 1 remain unchanged.

## Validation and qualification

The focused initializer/template/dependent-construction tests pass all 39 cases. The C++ and bundle package suite passes 666 tests. `cpp-constructor-argument-call-controls-after-r1/` matches the independent native source sites, preserves the valid declaration case and original positions, and introduces no file admissions. All nine workflow preflight checks pass, including Semgrep outside the sandbox.

The first full gate completes with 2,696 passes, three skips and one stale root bundle-pin assertion. Its log/session/exit evidence is retained. The corrected full gate passes **2,697 tests, three skipped, 88% coverage**, zero Semgrep findings, 900 indexed files, zero index failures and zero coverage issues. `cpp-initializer-gate-r2-result.json` binds the tested staged tree and source; `cpp-initializer-validation-receipt-r1.json` binds the committed implementation and frozen generated runtime separately.

`cpp-initializer-prior-1184-regression-r1/` reanalyzes every earlier macro admission under its original configurations: **all 2,368 profile cases are byte-identical**, complete and exception-free, with unchanged source hashes. The broad 650-original readiness run completes 497 originals under both modes, with zero exceptions. `cpp-initializer-650-artifact-grading-r1/` compares all 1,300 cases, passes 949 cases and 450 originals under both profiles, and loses no earlier pass.

The new passes are `vsscanf.cpp`, `socketpair.cpp` and `pipe2.cpp`. The first qualifies the production parser fix. The latter two qualify the previously added original-parameter proof together with six new native preprocessing captures for their source macro hints; all 156 earlier preprocessing captures are reused unchanged. No helper or clean parse counts as a fixed original.

`cpp-initializer-3-cli-index-r1/` completes both production indexes without failures. `cpp-initializer-3-index-verification-r1/` passes all six persisted comparisons and six actual CLI probes, including the recovered `max()` source call. Classification v49 admits only those three, checking six definitions, three prototypes, three aliases and 18 source-call records, including four native-proven macro hints. The independent audit preserves every original identity, all prior fixed/separated rows and all 25,759 other v48 rows.

The authoritative ledger is **3,973 verified fixes, 453 separated inputs and 21,336 open originals** (C 5,611; C++ 15,725). The wrapper inventory has **420 open originals**. Implementation commit: `fd8b796a4d42357ae93475548b51750c1653da86`.

## Next shared throughput cause

A read-only CPU profile on actual LLVM `ceil.cpp` attributes substantial work to repeated header parsing for class-owner discovery, although source namespace evidence already excludes the requested owners. The isolated `cpp-known-namespace-owner-experiment-r1/` uses the existing exclusion rule before header parsing: actual metadata remains byte-identical under both profiles, and a genuine header-defined class method still resolves correctly. Observed single-file times improve from 3.79 to 2.21 seconds and 5.09 to 3.53 seconds under concurrent load; these are exploratory observations, not controlled benchmark claims or a production optimization. Production source was unchanged by that experiment.

The full remediation objective remains active across all original languages and repositories. The separate custom-prefix syntax-intent screen changes no dispositions until its controls and source-profile evidence are admitted.
