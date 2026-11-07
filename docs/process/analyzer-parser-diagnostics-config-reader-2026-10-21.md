# Runtime configuration parsing during native qualification

The complete 25,762-original remediation remains active. Classification v60
still records 4,374 verified fixes, 680 separated inputs and 20,708 open files.
The bounded C++ SDK capacity change is committed as `a7cf821`; its full gate
passed 2,837 tests with three skips, zero Semgrep findings and a fresh index
without failures. The 122 additional native-metadata candidates are not admitted
at this code-change boundary.

## Measured execution bottleneck

Live stacks from the original SQLite/DuckDB CLI attempt first showed serial
include fingerprint capture. Later, after process workers started, a worker
remained inside `tomlkit.parse` during analyzer initialization. Parsing the
2,008,590-byte configuration constructs formatting trees and repeatedly copies
nested table arrays before actual source analysis can start.

A diagnostic native TOML read took 0.686 and 0.476 seconds for the exact two
configurations. Every value matched the complete independently reconstructed
CLI payload, including ordered original-file selection and source-bound
preprocessor query fingerprints. These measurements do not establish an
end-to-end speedup by themselves.

## Scoped change and compatibility

Read-only runtime loading now uses Python's native TOML parser. If that parser
rejects the document, the existing parser remains the compatibility path,
including its public ConfigError message and parser cause. This preserves TOML
1.1 syntax supported by the installed tomlkit, such as the escape character
spelling. Configuration editing continues through its existing separate path.
No analyzer schema, logical version, source projection or benchmark identity
changes in this performance fix.

Focused configuration tests cover a 128-element nested observation array without
formatting-tree construction, actual extended-syntax fallback, malformed input,
and the existing configuration hierarchy and editing controls. Failed fixture
construction and lint/type attempts remain retained; they are not product-file
failures or admissions.

The first owned CLI attempt was deliberately interrupted after diagnosing this
bottleneck. Its raw logs, partial index state, failed exit and explicit process
interruption receipt remain immutable. Only its verified subprocess subtree was
terminated. The already-running capacity gate completed independently. The new
CLI and storage attempts use fresh identities and the unchanged native-qualified
originals and profiles; their results must still pass before any ledger update.

## Evidence

Paths are relative to `.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `cpp32-cli-live-stacks-r1/`
- `cpp32-config-native-toml-probe-r1/`
- `cpp32-config-reader-prototype-tests-r1/`
- `cpp-native-config-reader-integration-r1/`
- `libcxx-statement-cpp32-qualified-cli-r1/interruption-receipt-r1.json`
- `libcxx-statement-cpp32-qualified-cli-r2/`
- `libcxx-statement-cpp32-index-verification-r2/`

The full performance-change gate uses
`.artifacts/validation/repo-gates/cpp-native-config-reader-r1.*`.
Admission additionally requires complete native metadata, actual SQLite and
DuckDB persisted tables and provenance, committed-source binding and an
independent audit preserving all original identities and separated inputs.
