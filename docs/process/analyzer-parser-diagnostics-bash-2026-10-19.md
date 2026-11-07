# Bash word recovery and lexical function extraction

This phase addresses the 14 remaining Bash diagnostic paths in the isolated
worktree. Their original sources pass GNU Bash 5.3.20 syntax-only parsing. They
expose bundled grammar omissions, not demonstrated future-syntax inputs.
The corpus, main checkout and original benchmark identity remain unchanged.

## Corrections

The Bash plugin creates coordinate-preserving views for parameter-word punctuation,
associative keys, variable-based slices, literal brace expansions, here-strings,
single-equals tests, scalar assignment-only redirects and template command words.
Original bytes still own every function name, signature and command name/site.
Embedded command substitutions remain executable syntax in the view; assignments
introduced only to repair the grammar do not become invented command calls.
Clean input bypasses recovery. Any remaining error discards the whole view.

These are syntax views, not word evaluation or shell rewriting. No corpus script
is executed. The plugin invokes no shell, external parser or command resolver.
Variable values, selected branches and runtime command targets are not inferred.

Extraction also retains written functions in conditional and nested scopes and
preserves the existing last-definition policy for repeated direct top-level
functions. Conditional and nested variants retain deterministic occurrence
identities. Nested
function bodies no longer donate calls to their enclosing function. The `[` and
`unset` builtin invocations are recorded. Complete command substitutions omitted
by the bundled heredoc scanner are recovered through isolated parsing, with
physical coordinates mapped back to the original source. Quoted heredoc
delimiters and escaped dollar signs stay literal; repeated sites are deduplicated.

Versions advance to Bash distribution **2.0.1**, logical analyzer **3**, and official
bundle **2.0.28**. Root pins, package assertions and the generated lockfile agree.
Other plugin versions and storage schemas remain unchanged. No release is published.

## Independent verification

The original 14-file cohort matches **78 function headers/body boundaries and 546
ordinary command names/sites** against independent shfmt ASTs. Five scripts have
no function definitions: their complete independent ASTs confirm the empty function
set and the plugin's module-only result. Top-level command sites are not part of
this plugin's mapped per-function call set.

Thirteen oracle inputs are byte-identical originals. shfmt 3.7.0 cannot parse the
official-images script's scalar associative keys. Its oracle-only input therefore
replaces strictly recognized scalar-key data with equal-width numeric data. The
key grammar excludes command/arithmetic substitutions and backticks, executable
syntax and all coordinates remain unchanged, and all names/signatures/sites are
read from original bytes at the independent AST ranges. Original-source GNU Bash
acceptance is checked separately. This validates mapped function/call artifacts,
not variable values or runtime equivalence. The first parser rejection and exact
projected input remain retained.

Another oracle correction concerns shfmt 3.7.0's function body `BinaryCmd` for a
brace function followed by `&& complete`. The native AST includes the following
list command in the body; GNU Bash associates it outside the definition. A retained
controlled synthetic script using only assignments, `:` and `printf` demonstrates
that association. The reader uses the left compound body, its closing boundary
and its lexical calls. Original ASTs and preceding comparisons remain retained.
No corpus script is executed for that probe.

The replay covers **866 shell files**. All **14 intended paths recover**, zero
exceptions and zero parsing-status regressions occur, and **749 previously clean
complete payloads remain identical**. Another **101 previously clean payloads
change** through corrected call/definition extraction. Every changed or recovered
payload is independently graded: **115 files, 888 functions and 7,268 calls**, with
zero missing/extra function records and zero call-set mismatches. All 115 original
sources additionally pass GNU Bash syntax-only checks.

The two broader replay paths still partial are PostgreSQL's AIX `mkldexport.sh`
and LLVM Polly's `isl_test.sh`; both are also rejected by GNU Bash. Their retained
diagnostics do not become false recoveries. Existing source/fixture classifications
are preserved rather than changing corpus contents.

The focused Bash/bundle checks and unchanged duplicate-definition contract pass
**32 tests**. GNU Bash independently accepts
all 12 positive grammar controls and rejects all ten malformed controls. Additional
tests cover original signatures/call positions, repeated and nested definitions,
assignment prefixes, quoted/literal boundaries, expanding heredocs and unset.
The heredoc omission has a retained minimal reproducer.

Real SQLite and DuckDB probes use four byte-identical corpus copies, including a
module without functions. Both route to Bash logical version 3, persist 50 checked
function rows, reuse all four files incrementally and preserve those rows after
a full rebuild. This checks persistence/routing, not retrieval or shell execution.

The first full gate passed 1,915 tests with three skips but failed the existing
duplicate direct-function contract. The extraction now preserves that contract
without changing its test; the 32 focused tests and fresh preflight pass. Failed
`bash-syntax-r1` gate evidence is retained. The fresh full gate passes **1,916 tests**, with three skips, **87%** coverage,
819 indexed files, zero failed files and zero coverage issues. Semgrep runs
outside the sandbox with zero findings.

## Admission, evidence and remaining work

Classification-v15 admits the 14 Bash paths only after the full gate: **660 verified
recoveries** and **24,659 original diagnostic paths still open**, with no Bash paths
remaining in the original investigate/fix cohort. C/C++, JavaScript and supported-
version Python diagnostics still require correction. The complete goal remains open.

Durable evidence is beneath
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `bash-syntax-full-replay-r4/`: complete source-bound before/after artifacts;
- `bash-independent-items-r10/`: original-cohort function/call comparisons;
- `bash-changed-independent-r7/`: all changed/recovered payload comparisons;
- `bash-shfmt-ast-r1/` and `r2/`: original ASTs, one retained scalar-key oracle input;
- `bash-changed-gnu-syntax-r1/` and `bash-native-controls-r2/`: source syntax checks;
- `bash-function-tail-oracle-r1/`: controlled native function/list association proof;
- `bash-heredoc-minimization-r1/`: original scanner omission reduced to a small source;
- `bash-broad-partials-r1/`: the two remaining broader syntax rejections;
- `bash-syntax-backend-probe-r2.json`: both current real backend checks;
- `bash-syntax-quality-r3.log`: final inexpensive checks, Semgrep outside the sandbox;
- `classification-v15.jsonl`, CSV and summary, and
  `bash-syntax-validation-receipt-r1.json`: final admission and examined full gate.

Earlier replay/comparison identities remain intact, including failed controls or
initial oracle discrepancies. Successful temporary gate files are removed only
after their result and hashes are recorded in the durable receipt.
