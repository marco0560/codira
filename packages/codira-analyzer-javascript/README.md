# codira-analyzer-javascript

First-party syntax-only JavaScript and JSX analyzer plugin for `codira`.

It supports `.js`, `.jsx`, `.mjs`, and `.cjs` files. The analyzer extracts
modules, imports, exports, classes, methods, functions, arrow functions,
module variables, call sites, callable-object references, and explicitly
attached JSDoc blocks. It does not claim TypeScript syntax, execute JavaScript,
resolve packages, or infer framework-specific semantics.

Enable or restrict it under `[plugins.analyzer-javascript]`; `emit_variables`
and `emit_jsdoc_documentation` are both enabled by default.

```bash
uv run codira plugins
uv run codira cov
```
