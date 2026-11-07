# Explicit include roots: a high-impact LLVM diagnostic cohort

The complete residual scan covers **24,550 paths**, with no exceptions. Of these,
**682 currently parse cleanly** but remain outside the qualified-fix ledger;
**23,868 remain partial**. The largest source groups include 2,418 libc++ standard
tests, 1,801 LLVM public C++ headers and 970 libc support files. These counts guide
prioritization; overlapping token hints are not root-cause verdicts.

## Measured cause and correction

The existing contained-header resolver supports explicit search roots, but the
C++ plugin did not expose or pass them. The original benchmark configuration
therefore left angle includes unresolved. LLVM's CMake declares `llvm/include`
as a source include directory. Supplying that exact directory to the existing
resolver and parser recovers **1,376 of the 1,801 C++ headers**, leaving **425**
partial, with no exceptions. This is a complete measurement, not a sample estimate.

The raw capture also included three C-dispatched headers, causing its final
fixed-count assertion to fail after all 1,804 records were written. The reviewed
summary filters by captured actual dispatch and rechecks source/header digests;
those three records remain retained and do not enter the C++ recovery count.

The plugin now exposes ordered `include_search_paths` and uses them in analysis
and dependency identity. Quoted includes search their own directory first; angle
includes search the configured roots. Roots remain inside the indexed repository.
Cache checks detect root-order changes, newly shadowing headers, equal-stat content
changes and configured symlinks retargeted to another directory. The default empty
list remains explicit; build flags and search directories are not inferred.

The C++ logical identity advances to **15**, distribution to **2.0.11**, and bundle
to **2.0.34**. No release is published. On an LLVM checkout, the relevant option is:

```toml
[plugins.analyzer-cpp]
include_search_paths = ["llvm/include"]
```

This is an explicit corrected analysis profile. The original campaign/configuration
and corpus are preserved. The 1,376 parser recoveries are not yet admitted as fully
qualified artifact fixes; original-source extraction checks remain separate.

## Validation

Focused configuration, dependency and indexing checks pass **43 tests**, including
both actual structural backends with explicit backend-name assertions. The first
test attempts exposed fixture mistakes in artifact-field names and configuration
location/required fields; their logs are retained. The final preflight passes all
checks, including Semgrep outside the sandbox with zero findings. The corrected
full gate passes **2,118 tests**, with **3 skipped**, **87% coverage**, and a fresh
index of **838 files**, with zero failures or coverage issues.

The first full gate passed 2,116 tests but failed the generated installer-catalog
freshness check and a headless navigation test (`OutOfBounds`, followed by a header
teardown error). The catalog was regenerated through its repository generator,
and the installer distribution advances to **2.0.3**. The focused catalog and TUI
checks then passed all three tests without a TUI implementation change. The failed
gate remains retained; the corrected second full gate passes. The navigation
failure did not recur; no cause is inferred from the successful rerun.

The backend tests now use the canonical `.codira/config.toml`. An audit of the
earlier header-routing probe found that its `.codira.toml` file was ignored, so its
SQLite/DuckDB labels did not establish backend selection. The earlier raw record
is retained; a corrected snapshot probe with canonical configuration and explicit
backend-name assertions now passes for both actual backends and supersedes that
claim. It loads the original committed C++13 and C++14 plugin snapshots, so the
correction is not inferred from the current plugin's behavior.

## Retained evidence and next action

Evidence is under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `remaining-impact-ranking-r1/`: complete residual scan and source bindings;
- `llvm-include-impact-probe-r1/`: twelve-path causal probe;
- `llvm-include-impact-r2/`: complete capture, raw terminal failure and reviewed
  C++ aggregate in `reviewed-summary.json`;
- `include-search-focused-r1.log`, `r2.log`, `r3.log`: focused checks and corrections;
- `include-search-quality-r1.log`: passing preflight;
- `include-search-production-cohort-r1/`: complete production replay and artifacts;
- `header-routing-backends-r2/`: corrected backend migration/reuse probe;
- `include-search-native-originals-r1/`: original-source native capture;
- `include-search-native-grading-r2/`: resumable independent comparisons;
- `include-search-oracle-structure-r2.json` and
  `include-search-oracle-equivalence-r1.json`: unchanged-comparison evidence;
- `include-search-validation-receipt-r1.json`: examined full-gate result and source
  bindings. The earlier failed gate remains under `.artifacts/validation/repo-gates/`.

The production replay now exercises the actual, unmodified `CppAnalyzer` on all
**1,376 original paths** with default and configured settings. All 1,376 become
clean with the explicit root, versus zero with default settings, with zero
exceptions. Retained canonical artifacts contain **3,346 functions**, **5,834
classes** and **6,655 declarations**. This proves production extraction and
diagnostic recovery; it is not independent semantic qualification or an end-to-end
CLI benchmark.

Independent Clang C++17 AST capture and strict source-artifact comparisons remain
in progress. Native headers are generated by configuring the unchanged LLVM
source with CMake, without building LLVM. Native rejection or comparison mismatch
keeps a path unqualified; it does not establish deliberate malformed/future syntax.
The comparison covers source identities, callable parameters, lexical body calls,
named types and prototype/redeclaration chains. Constants, complete signatures,
visibility, attributes, ABI/runtime behavior and implicit call lowering are outside
that comparison. Per-file path memoization preserves the original comparison AST;
structural equivalence and complete-output controls are retained.

Unrelated partial headers and low-return individual cases remain open. Pending
independent admission, the ledger still records **759 verified fixes**, **453
separately classified files** and **24,550 open paths**.

Later source-bound admission is recorded in the [qualified LLVM include-profile
report](analyzer-parser-diagnostics-llvm-includes-qualified-2026-10-19.md). Earlier
ledger totals above are the phase snapshot, before that admission.
