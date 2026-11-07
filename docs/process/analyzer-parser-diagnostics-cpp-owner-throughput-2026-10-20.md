# C++ source-proven owner exclusions — 2026-10-20

## Shared processing cause

Class-owner discovery reparsed every captured header even when written source namespace or alias evidence already excluded every requested owner. Header evidence can add conflicting alternatives but cannot remove the source conflicts, so these traversals could not change the result.

The caller now skips external owner discovery only when every requested owner is already in the existing conflict set. The comparison uses complete qualified owner names: a namespace `api` does not exclude a class `api::Owner`. Unqualified functions participate in the requested set, retaining discovery for mixed inputs. The existing final callable-ID disambiguation still runs. Header-defined class ownership, visibility and member-call qualification retain their fallback path.

The C++ distribution advances to **2.0.26** and the official bundle to **2.0.52**, with synchronized root pins, contracts and lockfile. C++ logical analyzer version remains **25** because metadata behavior is unchanged. Core schema, backend schemas and provenance format are unchanged. Installer catalog regeneration produces no change.

## Verification and practical effect

All 10 focused ownership controls pass. Namespace-only inputs and source aliases avoid discovery; namespace prefixes, real header classes, member calls, mixed global functions, conditional conflicts and overload identities retain their required behavior. All nine workflow preflight checks pass, including Semgrep outside the sandbox.

The full repository gate passes **2,703 tests, three skipped, 88% coverage**, with zero Semgrep findings and zero coverage issues. `cpp-owner-discovery-gate-launch-r1.json` and `cpp-owner-discovery-gate-result-r1.json` bind the tested implementation, staged paths and separately frozen generated runtime. A sandbox denial while obtaining the Git tree is retained as an execution-boundary receipt; the same check succeeds outside the sandbox without source changes.

`cpp-owner-discovery-actual-ceil-parity-r1/` executes the old caller from its frozen C++25 snapshot and the current caller on actual LLVM `libc/src/math/generic/ceil.cpp`. Complete metadata is byte-identical in both packaging modes. Each mode's redundant owner traversal drops from **162 captured header visits to zero**. Other header-analysis passes remain; this is an operation-count result, not an elapsed-time speedup claim. Earlier exploratory timings remain separately retained.

`cpp-owner-discovery-prior-1187-regression-r1/` compares every previously admitted macro original under its exact prior profile, using immutable admission receipts and retained native-qualified metadata. All **2,374 profile cases are complete and byte-identical**, with zero errors and unchanged production source hashes. No helper, clean parse or performance comparison adds a verified file fix.

## Remediation frontier

The current classification-v51 ledger and `separated-inputs-v51-r1/` export contain 3,973 verified fixes, 680 justified exclusions and 21,109 open originals. The full objective remains active; this throughput change does not claim additional fixes.

A separate native-profile investigation generated 100 public headers using LLVM's checked-in official generator and YAML specifications. All six causal checks succeed where retained mixed LLVM/glibc type definitions failed. Applying the profile to 116 affected originals produces **232 complete native inventory cases**, without exceptions. Source/generator hashes, generated headers, compiler commands, raw outputs and the earlier failures remain under `cpp-official-libc-headers-*`. These are native qualification inputs, not analyzer fixes or admissions. The next step is analyzer metadata comparison under a separately captured bounded macro profile.
