# codira-analyzer-typescript

First-party, syntax-only TypeScript and TSX analyzer plugin for `codira`.

It supports `.ts`, `.tsx`, `.mts`, and `.cts`. The plugin will extract
TypeScript declarations, call and reference relations, and explicitly attached
TSDoc blocks while remaining independent of compiler, package-manager, and
framework runtime behavior. Type checking and TypeScript compiler emulation are
outside this plugin's contract.

Getter and setter identities include `:get` and `:set` suffixes. Static members
include `:static`, keeping them distinct from instance members with the same
name, including accessors and overload declarations. Ordinary instance method
identities are unchanged. Each member retains its own TSDoc and call sites.
