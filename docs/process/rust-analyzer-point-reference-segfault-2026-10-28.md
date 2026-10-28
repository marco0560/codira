# Rust analyzer native coordinate reference corruption

Date: 2026-10-28. Base: `91c4e07a3c25e72ee7c3346899f92e551037bf5e`.
Branch: `fix/rust-analyzer-segfault-20261028`.

## Demonstrated cause

The Rust plugin used `Node.start_point.row`, `.column`, and `end_point.row`.
In [py-tree-sitter 0.26.0 point.c](https://github.com/tree-sitter/py-tree-sitter/blob/v0.26.0/tree_sitter/binding/point.c),
`point_get_row` and `point_get_column` return `PyTuple_GetItem` directly,
without acquiring the reference required by a Python property getter.
Integers outside CPython's small-integer cache can consequently be freed while
still referenced by their Point, corrupting the heap. Tuple item access acquires
the reference correctly. A native refcount probe confirms the difference: three property reads lose
three references for either coordinate on 0.26.0, while indexing loses none;
0.25.2 loses none through either interface.
This is a binding reference-ownership defect, not evidence of an executor bug.

A read-only copy of the reported 17,007-byte Rust input reproduced SIGSEGV
with Python 3.14.10 / tree-sitter 0.26.0 / tree-sitter-rust 0.24.2. Its SHA-256
is `1133226f80556c5625cf0ef0ca97b7f35fab3bace89cab0cb13e2b0abf006e76`.
Parse-and-release alone passed. Faulthandler and GDB locate the later crash in
`_PyEval_SliceIndex`, reached from `_calls` through `_text`; that is the observed
failure site after memory corruption, not an invalid source byte range.
The root node's tree reference keeps the parsed tree alive, as the
[binding's Node constructor](https://github.com/tree-sitter/py-tree-sitter/blob/v0.26.0/tree_sitter/binding/node.c)
confirms. No dangling-tree workaround is justified by the evidence.

## Smallest scoped correction

Use the stable Point tuple interface, `[0]` for row and `[1]` for column,
throughout the Rust plugin. Keep `_text`, recursion, parsing, extraction scope,
thread/process support, and file selection unchanged. The workaround supports
both the namedtuple-based 0.25.2 binding and the 0.26.0 tuple subclass.
Advance Rust distribution 2.0.1 to 2.0.2 and logical analyzer version 3 to 4,
so a subsequent index does not reuse analysis from the affected implementation.
Advance the official bundle to 2.0.15 and align its pins and root extras.
No dependency downgrade or file exclusion is required.

## Reproduction and regression evidence

Raw evidence is retained under `.artifacts/analysis/rust-segfault-20261028-r1/`
in the dedicated worktree. Failed setup and debugger attempts remain there.
`regression-before-r1.log` records two failing subprocess regressions on the
unmodified plugin: a three-call Rust function after 300 newlines, and the same
function after 300 spaces. Each child terminated with SIGSEGV. The fixed tests
assert exact function/call coordinates and targets, repeated analysis, explicit
garbage collection, and normal process exit. No SaniKey fixture is needed.

| Python | tree-sitter | Rust grammar | Original file before | Fixed package tests |
| --- | --- | --- | --- | --- |
| 3.13.13 | 0.25.2 | 0.24.2 | pass | 9 pass |
| 3.13.13 | 0.26.0 | 0.24.2 | SIGSEGV | 9 pass |
| 3.14.10 | 0.25.2 | 0.24.0 | pass | 9 pass |
| 3.14.10 | 0.26.0 | 0.24.2 | SIGSEGV | 9 pass |

The original and reduced inputs pass after the fix in all four environments;
see `matrix-after-r1.json`. The Python 3.13 same-grammar comparison isolates the
binding change; this is not specific to Python 3.14 or to Rust grammar 0.24.2.
The checked-out lockfile actually pins Rust grammar **0.24.2**, whereas 0.24.0
is the declared minimum. Both were tested rather than silently rewriting it.

The current external checkout has 74 tracked Rust files. All pass direct
analysis with explicit collection sequentially, with two threads, and with two
spawned processes on Python 3.14.10 / binding 0.26.0 / grammar 0.24.2.
A broader read-only scan also analyzes all 134 Rust files currently on disk,
including prototypes and generated build outputs. This is a current inventory,
not a claim to reproduce the earlier 123-file snapshot. Per-file source hashes
and external Git status match before and after each run. No command imports
SaniKey modules, writes its checkout, or repairs its existing updating index.
These checks prove execution and regression behavior, not independent semantic
qualification of every extracted symbol.

A deferred-embedding public CLI smoke on four synthetic tracked Rust files also
passes with `--concurrency off`, `--concurrency thread --jobs 2`, and
`--concurrency process --jobs 2`. Reported effective strategies are respectively
off, thread, and process; every run indexes four files with zero failures.
Inputs are disposable fixtures under the designated temporary root, and each
output is a new Codira artifact directory. The isolated Python 3.14 environment
registers the embedding adapter without downloading the optional ML runtime;
these checks exercise deferred indexing, not embedding computation. Earlier
missing-plugin setup failures are retained separately from successful r4 runs.

## Validation commands

Run from the dedicated worktree with its own `uv` environment. Isolated
Python environments under the evidence directory hold the comparison bindings.
For the primary environment:

```bash
uv sync --offline --extra docs
uv run --offline --no-sync pytest -q packages/codira-analyzer-rust/tests tests/test_tree_sitter_recovery.py tests/test_capabilities.py packages/codira-bundle-official/tests tests/test_contracts.py
uv run --offline --no-sync python scripts/prepare_benchmark_history.py
uv run python scripts/check_workflow_quality.py
uv run python scripts/validate_repo.py
```

The focused cross-package run passes 44 tests. The preflight passes every
check, including Semgrep outside the sandbox and fresh-index docstring audit.
The full gate passed in named tmux session `codira-rust-segfault-gate-r1`: exit
0, 1,716 passed, 3 skipped, 86% coverage, 784 indexed files, zero index failures
and zero coverage issues. The fresh-index documentation audit also passed.
It ran from 18:06:03 to 18:16:29 UTC. The examined log, exit status, terminal
receipt and launcher are retained under `full-gate-r1/`; only their successful
repo-gate duplicates are eligible for the prescribed cleanup.
The local SaniKey index remains untouched and may still be `updating`.
No commit, installation into SaniKey, push, or publication is performed.
