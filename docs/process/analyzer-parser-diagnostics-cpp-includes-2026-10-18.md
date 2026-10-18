# C++ header-input groundwork and remaining integration

The source-local annotation correction does not recover a translation unit
whose annotation definitions live only in a header. The frozen inih witness
`cpp/INIReader.cpp` includes `INIReader.h` and `../ini.h`; its `INI_API` uses
remain partial through the current public `CppAnalyzer.analyze_file` entrypoint.

This phase adds captured include context and an explicitly supplied header-input
option to the private parser. It does **not** enable header recovery in the
public analyzer yet. Incremental indexing must first retain and compare these
external inputs; otherwise changing an unchanged source file's header would
leave stale symbols reusable. No additional file is admitted to the corrected
classification ledger on the strength of this groundwork alone.

## Captured inputs

`cpp_include_context.py` captures exact source and header bytes, a dependency
fingerprint and unresolved include observations. Literal quoted includes search
the including file's directory followed by explicit ordered search roots. System
includes search only explicit roots. The implementation does not guess include
paths, read host SDK headers, invoke a compiler or choose conditional branches.
Both source branches are retained. Include-shaped comments and literal text are
excluded by syntax-node inspection.

Resolved inputs stay inside the repository, including through symlinks. Cycles
terminate; transitive headers inherit the earliest reaching source include
boundary. Negative lookups, selected paths, search order and header bytes enter
the fingerprint. Header changes with unchanged size and restored mtime still
change it; header creation, deletion and shadowing are observed on the next
snapshot. Each snapshot owns immutable bytes and uses no persistent lookup cache.

The private parser can consume these captured bytes. It considers replacement
alternatives across the source and supplied headers, excludes function macros,
undefinitions and incompatible replacements, and permits annotation uses only
after their source include boundary. Recovery still requires an entirely clean
projected tree. Header declarations are not copied into the translation unit;
original source bytes retain signatures and coordinates. This is source-backed
annotation projection, not general macro expansion or build reproduction.

## Evidence and limits

The retained inih probe uses original source hashes and compares projected
explicit callable names and physical name lines with Clang on the original
translation unit. The compiler AST and stderr are retained alongside the probe
receipt. This is a direct parser/builder probe. Public analyzer integration,
incremental index behavior, complete ownership resolution, types, call edges and
backend persistence are not established by it.

Seventeen new regression cases cover transitive cycles and availability,
dependency-byte edits, negative lookup changes, search precedence, source
branches, macro includes, explicit system search roots, repository containment,
relative paths, compatible and incompatible annotation alternatives, and uses
before an include. Focused validation passes 126 tests, including the existing
C++ package, bundle, header routing, native scanner and quality-policy checks.
The source-bound native probe matches 18 explicit callable names and physical
name lines. It still records `index_symbols = false` through the public analyzer.

The final full repository gate exits zero: 1,790 tests passed, three skipped,
87% coverage, 799 files freshly indexed, no failed files and no coverage issues.
Semgrep runs outside the sandbox with zero findings. An earlier gate stopped
on an undocumented new lint suppression; that suppression was removed by
collecting annotation state in a dataclass. Its failed attempt remains retained.

The distribution advances to C++ 2.0.4 and official bundle 2.0.20, with root pins
and the lockfile aligned. Logical analyzer version 8 stays unchanged because the
public analyzer does not yet consume external header inputs.

## Remaining work

The indexer currently compares raw source hashes and analyzer identity for
reuse. Failure reuse also compares source bytes and analysis configuration;
neither records per-file header inputs. Before enabling the new parser option:

1. Define an optional analyzer input-fingerprint contract, separate from source
   SHA-256 and analyzer version. The plugin owns include resolution semantics.
2. Persist the fingerprint observed for each analyzed or failed path, compare it
   during reuse, and retry retained failures when their inputs change.
3. Check input identity around worker analysis and preserve reader/family
   freshness. A changed dependency must never be published as a reused result.
4. Prove header edit, creation, deletion, transitive changes and unchanged-source
   behavior through serial and process indexing and both structural backends.
5. Enable the public C++ entrypoint, advance its logical version, replay the
   frozen population and admit only independently verified corrected paths.

Durable evidence is worktree-relative under
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `cpp_include_context_probe_r1.py` and `cpp-include-context-probe-r1.json` retain
  the source-bound probe and its precise verification scope.
- `cpp-include-context-native-r1.ast.json` and `.stderr` retain received native
  evidence.
- `cpp-include-context-validation-receipt-r1.json` records examined validation
  results once the gate completes.

The main checkout, original benchmark and pinned third-party corpus remain
unchanged. The wider parser goal remains open.
