# codira-documentation-audit-jsdoc

First-party JSDoc documentation audit plugin for `codira` JavaScript artifacts.

The plugin audits explicit JSDoc blocks emitted by `codira-analyzer-javascript`.
It reports missing or empty documentation, missing `@param` tags, and required
`@returns` or `@throws` tags. It does not parse source files, execute examples,
type-check JSDoc, or infer documentation from ordinary comments.

Activate it with an explicit route:

```toml
[plugins]
documentation_audit_routes = [
  { language = "javascript", convention = "jsdoc", plugin = "jsdoc", include_paths = ["src/**"] },
]
```
