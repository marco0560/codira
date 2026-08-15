# Python normalized syntax layer

The Python analyzer package owns its Tree-sitter integration. Core Codira does
not depend on the Python grammar binding.

`codira_analyzer_python.syntax.parse_python_source` accepts text or UTF-8
bytes and returns a Codira-owned `SyntaxTree`. Each `SyntaxNode` has a
provider-neutral `SyntaxKind`, a half-open UTF-8 byte span, and one-based line
numbers with zero-based byte columns. Provider grammar names are adapter
implementation details and never form part of the syntax contract.

The adapter creates a new parser for each call. It therefore retains no mutable
parser state and supports the analyzer's declared thread and process worker
concurrency. Recoverable parsing faults become location-sorted `error` or
`missing` diagnostics.

The Python analyzer extracts module, class, callable, declaration, import,
documentation, call, and callable-reference records through this adapter before
passing them to Codira's unchanged artifact normalizer. Its analyzer version is
bumped with this migration, and its persisted configuration fingerprint includes
the syntax-artifact revision, so incremental indexing reprocesses previously
persisted Python results safely.

Core CLI and context rendering do not parse target Python. They consume indexed
artifact identities and source locations, using language-neutral source-text
recovery only for presentation snippets when an indexed artifact is available.
As a result, core can run without `codira-analyzer-python`; unavailable Python
files degrade through the registry's normal optional-plugin diagnostics rather
than an import-time dependency.
