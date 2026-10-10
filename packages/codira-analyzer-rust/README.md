# codira-analyzer-rust

First-party Rust analyzer plugin for `codira`.

The analyzer records `macro_rules!` definitions as macro declarations and
macro invocations as unresolved `rust_macro` call sites. It does not expand
macros or emulate Cargo feature, build-script, or conditional-compilation
configuration. Set `emit_macros = false` under `[plugins.analyzer-rust]` to
omit macro declarations while retaining syntax analysis.

Repository-local editable install:

```bash
uv run python scripts/install_first_party_packages.py --include-core --include-bundle
```

Verify discovery and coverage:

```bash
uv run codira plugins
uv run codira cov
```

All source variants of conditional declarations remain available. Repeated
function, macro, namespace, type, and implementation identities include a
source line and occurrence suffix; moving a repeated declaration can change
its identity. Separate `impl` blocks retain their methods and Rustdoc owners.
Nested functions include their enclosing callable names in their identities.
Anonymous `const _` declarations are not indexed as named symbols.
