# Header language selection with incomplete template declarations

The C++ header selector can miss a template when external annotation or namespace
macros leave its provider tree incomplete. It then selects C for an ambiguous `.h`
file. A Clang-accepted C++03 control reproduces this with an included configuration
header. The original LLVM `libcxx/include/__cxx03/__algorithm/all_of.h` shows the
same incomplete-tree selection pattern.

The fix inspects source-coordinate tokens outside comments, literals and directives.
It isolates a balanced template parameter list and parses it with a synthetic
declaration. At least one named type parameter must be present. Locally redefined
template/type keywords suppress this fallback. This establishes a language hint;
it does not replace source bytes, expand macros or claim successful extraction.
Explicit header-language overrides, exclusions and neighboring-source rules retain
their existing precedence.

The C++ logical analyzer identity advances to **14**, its distribution to
**2.0.10**, and the official bundle to **2.0.33**. No release is published.

## Validation and remaining diagnostics

The complete pinned inventory contains **19,723 `.h` files**. The final source-bound
comparison changes **98** language claims from C to C++, with no reverse changes.
Both existing analyzers still produce partial results on those 98 files. Their
source-dependent annotation/include contexts need further work. These language
selection corrections do not admit any file as a fully fixed parser diagnostic:
the ledger remains **759 fixed**, **448 separately classified**, **24,555 open**.

The 96 earlier candidates were text-prefiltered pending files, whereas the full
inventory comparison also covers other first-parameter patterns and all retained
dispositions. Text candidates alone are not proof of source language or validity.

The final focused checks pass **184 tests**. **19 native syntax controls** compile
in strict C11, C++03 or C++11 and produce the expected selection. Clang also accepts
**93 exact source template prefixes**, exposing **147 named type parameters**, in
isolated C++23 declaration probes. Five other prefixes require unavailable type
context (`size_t`, `allocator`, `deque`, `__cxx_atomic_base_impl`). This probe does
not compile the original header or qualify its extraction.

Both SQLite and DuckDB confirm actual persisted ownership migration from C 15 to
C++ 14 on a byte-identical original header copy, followed by incremental reuse and
matching ownership after a full rebuild. Each retains the existing parser coverage
issue; process success does not establish successful symbol extraction.

The first preflight identified formatting and a test-only list type annotation,
both corrected. The final preflight passes all checks. The examined full gate
passes **2,106 tests**, with **three skips**, **87% coverage** and a fresh **835-file**
index: zero failures or coverage issues. Semgrep runs outside the sandbox and
reports zero findings on 178 files. Source and retained evidence hashes are bound
in `header-routing-validation-receipt-r1.json`; the ledger is unchanged.

## Evidence

Retained under `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `header-routing-audit-r1/`: initial bounded candidate audit;
- `header-routing-controls-r1/`, `r2/`: original failure reproduction and controls;
- `header-routing-controls-r3/`: corrected-selection native controls;
- `header-routing-full-surface-r1/`, `r2/`: complete source-bound routing comparison;
- `header-routing-native-prefixes-r1/`: isolated source-prefix compiler responses;
- `header-routing-backends-r1/`: original-plugin snapshot and backend migration;
- `header-routing-quality-r1.log`, `r2.log`: initial findings and passing preflight;
- `header-routing-focused-r2.log`: focused package and routing checks;
- `header-routing-validation-receipt-r1.json`: final source/evidence binding.

The original benchmark, corpus, main checkout and unrelated untracked files are
preserved. The overall diagnostic-resolution goal remains open.
