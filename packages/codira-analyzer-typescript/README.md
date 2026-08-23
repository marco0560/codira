# codira-analyzer-typescript

First-party, syntax-only TypeScript and TSX analyzer plugin for `codira`.

It supports `.ts`, `.tsx`, `.mts`, and `.cts`. The plugin will extract
TypeScript declarations, call and reference relations, and explicitly attached
TSDoc blocks while remaining independent of compiler, package-manager, and
framework runtime behavior. Type checking and TypeScript compiler emulation are
outside this plugin's contract.
