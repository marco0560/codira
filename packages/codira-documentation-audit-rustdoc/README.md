# codira-documentation-audit-rustdoc

First-party Rustdoc documentation audit plugin for `codira`.

The plugin validates explicit Rustdoc attached with `//!` and `///`. It preserves
doctest fences as documentation text; compiling or executing doctests remains
the responsibility of Cargo and rustdoc.

Enable it with an explicit route:

```toml
[plugins]
documentation_audit_routes = [
  { language = "rust", convention = "rustdoc", plugin = "rustdoc", include_paths = ["src/**"] },
]
```
