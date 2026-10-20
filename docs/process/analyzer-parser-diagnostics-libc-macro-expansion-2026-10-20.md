# LLVM libc declaration-macro expansion — 2026-10-20

The shared function-wrapper correction now has a tested token-expansion
foundation in the C++ plugin. This is an intermediate implementation step,
not a corpus qualification: classification v37 remains **2,672 verified fixes,
453 separated and 22,637 open**. The 1,607 pending originals containing
`LLVM_LIBC_FUNCTION` remain candidates.

`cpp_macro_expansion.py` accepts explicitly selected object/function definitions
and invocation bytes. It implements argument prescan, replacement-list rescan,
variadic dispatch, stringification, token pasting, empty arguments and recursion
suppression. Each token retains its original byte span; generated implementation
names such as `__ceil_impl__` retain the source argument's `ceil` span and a
synthetic-spelling marker. Stringification preserves preprocessing whitespace,
and variadic commas retain their original spans, including empty arguments.

Expansion has bounds on source bytes, token count, substitution count and
argument nesting. Unsupported lexical forms or operators raise an explicit
failure rather than returning partial expansion. Current holds include raw
strings, digraphs, GNU comma elision and `__VA_OPT__`. Unknown identifiers remain
tokens; this helper does not claim to resolve unknown compiler builtins.

The helper is deliberately not wired into `CppAnalyzer` yet. Selecting active
definitions in source/include order, handling unknown conditions and projecting
expanded declarations into original-source artifact coordinates remain required.
The public-packaging branch must preserve both the generated implementation and
the public alias declaration; expanding its tokens alone does not establish that
the artifact builder models its `decltype` declarations correctly. Runtime
analyzer behavior and logical version 22 are unchanged. The package distribution
is advanced to 2.0.19 and the official bundle to 2.0.44 for this plugin change.

Validation so far:

- 58 focused expansion tests pass, including provenance, empty variadic arguments,
  recursive suppression, work limits and explicit unsupported-input failures.
- All 408 C++ plugin and official-bundle tests pass.
- Focused Ruff, formatting and strict typing checks pass.
- The required quality preflight passes all eight checks, including Semgrep
  outside the sandbox and a fresh 875-file index with zero failures or coverage
  issues.
- 38 independent Clang 22 token comparisons match. Thirty cover substitution
  controls; eight use the actual captured LLVM libc `common.h` and `ceil.h`,
  crossing public packaging enabled/disabled, three/four arguments and an optional
  source-described per-function weak attribute. Active replacements are read from
  the actual compiler's macro dump, not reimplemented as the native expectation.
  Expected token spellings come from Clang's token dump, independently of the
  product tokenizer. This is a token-expansion comparison, not end-to-end analyzer
  qualification or original LLVM build-harness validation.
- A separate audit of all eight libc variants checks 60 original argument-token
  positions against Clang spelling locations and eight generated implementation
  name occurrences against the original name argument and native scratch-space
  spelling evidence. All checks pass.

The first full repository gate exposed a root package-contract expectation still
pinned to 2.0.18. The failure was reproduced directly; that expectation is now
aligned to 2.0.19 and the focused root contract passes. The first gate completed
with exactly one failure, 2,400 passing tests and three skips. Its examined log,
runner and exit status remain as failure evidence; the completed session is
closed. `cpp-macro-expansion-failed-gate-receipt-r1.json` binds those records.

The fresh corrected full gate passes: **2,401 tests, three skipped, 87% coverage**,
with a fresh **877-file index**, zero index failures and zero coverage issues.
Semgrep runs outside the sandbox. The source-bound receipt is
`cpp-macro-expansion-validation-receipt-r1.json`. The examined successful session
and its temporary runner/log/status files are cleaned up under the repository
gate-retention rule; native and failed-gate evidence remain unchanged.

Evidence is retained under the dedicated worktree's
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `libc-macro-token-native-r1/`: initial 28 comparisons and raw compiler evidence;
- `libc-macro-token-native-r2/`: expanded 38 comparisons, exact source/header/tool
  digests, commands, raw token and macro dumps, exits, product token spellings and
  `source-origin-audit.json`.

The existing [wrapper diagnosis](analyzer-parser-diagnostics-libc-wrapper-readiness-2026-10-20.md)
records the native symbol differences and why both packaging branches are
required. Integration would cross ADR-030's shared syntax-only macro policy.
The [capability proposal](analyzer-cpp-expansion-decision-proposal-2026-10-20.md)
records the unresolved operator decision: an explicit opt-in C++ expansion
capability under a new ADR, or retaining the accepted indexing boundary and
prioritizing another shared cause. No integration is authorized by this report.
