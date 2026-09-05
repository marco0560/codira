# Documentation Audit Plugins

Documentation audit plugins validate documentation conventions for artifacts
already emitted by language analyzers. They do not scan files, parse languages,
or decide whether a file belongs to a language. That boundary keeps indexing
owned by analyzers and convention checks owned by audit plugins.

## Contract

A documentation audit plugin implements `DocumentationAuditPlugin` from
`codira.contracts`:

```python
class DocumentationAuditPlugin(Protocol):
    name: str
    version: str
    languages: Sequence[str]
    conventions: Sequence[str]

    def audit_documentation(
        self,
        request: DocumentationAuditRequest,
    ) -> DocumentationAuditResult: ...
```

`DocumentationAuditRequest` carries the source path, artifact owner metadata,
the documentation text, callable parameter names, and semantic flags such as
whether the artifact returns, yields, or raises. The result contains structured
diagnostics with stable codes and messages.

## Entry Point

Expose plugins through the `codira.documentation_audits` entry-point group:

```toml
[project.entry-points."codira.documentation_audits"]
numpy = "codira_documentation_audit_numpy:build_audit_plugin"
```

Enable a plugin with the usual `enabled` key:

```toml
[plugins.documentation-audit-numpy]
enabled = true
```

The entry point value must return a fresh plugin instance. Verify discovery
with:

```bash
codira plugins
codira plugins --json
codira caps --json
```

## First-Party Plugins

The first-party inventory includes:

| Package | Plugin | Languages | Conventions |
| --- | --- | --- | --- |
| `codira-documentation-audit-numpy` | `numpy` | `python` | `numpy` |
| `codira-documentation-audit-google` | `google` | `python` | `google` |
| `codira-documentation-audit-doxygen` | `doxygen` | `c`, `cpp` | `doxygen` |
| `codira-documentation-audit-rustdoc` | `rustdoc` | `rust` | `rustdoc` |
| `codira-documentation-audit-jsdoc` | `jsdoc` | `javascript` | `jsdoc` |
| `codira-documentation-audit-tsdoc` | `tsdoc` | `typescript` | `tsdoc` |
| `codira-documentation-audit-go-doc-comments` | `go-doc-comments` | `go` | Go doc comments |

These packages are included in `codira[bundle-official]` and are discovered
through entry points. The core package defines the shared contract and routing
logic; active first-party convention plugins come from the package entry
points, not from core built-ins.

## Routing

Documentation audit activation is explicit. Configure ordered routes under
`plugins.documentation_audit_routes`:

```toml
[plugins]
documentation_audit_routes = [
  { language = "python", convention = "numpy", plugin = "numpy", include_paths = ["src/**/*.py"] },
  { language = "python", convention = "google", plugin = "google", include_paths = ["tests/**/*.py"] },
  { language = "c", convention = "doxygen", plugin = "doxygen", include_paths = ["src/**/*.c", "include/**/*.h"] },
  { language = "cpp", convention = "doxygen", plugin = "doxygen", include_paths = ["src/**/*.cpp", "include/**/*.hpp"] },
  { language = "rust", convention = "rustdoc", plugin = "rustdoc", include_paths = ["src/**/*.rs"] },
  { language = "javascript", convention = "jsdoc", plugin = "jsdoc", include_paths = ["src/**/*.js", "src/**/*.jsx"] },
  { language = "typescript", convention = "tsdoc", plugin = "tsdoc", include_paths = ["src/**/*.ts", "src/**/*.tsx"] },
  { language = "go", convention = "go-doc-comments", plugin = "go-doc-comments", include_paths = ["src/**/*.go"] },
]
```

No route means no documentation audit diagnostics are emitted. More than one
matching route emits an `ambiguous_route` diagnostic instead of selecting a
convention implicitly.

`codira caps --json` exposes documentation audit as a route-selected plugin
family through `plugin_families[]`. Individual documentation-audit plugin rows
under `plugins[]` are active only when an explicit route selects that plugin
and its `[plugins.documentation-audit-*]` table does not disable it.

## JSON Output

`codira audit --json` emits persisted plugin and convention provenance for
each issue:

```json
{
  "type": "missing_parameter",
  "audit_plugin": {
    "name": "numpy",
    "version": "1"
  },
  "audit_convention": {
    "name": "numpy",
    "version": "1"
  },
  "rule_id": "missing_parameter",
  "severity": "warning",
  "audit_route": {
    "language": "python",
    "convention": "numpy",
    "plugin": "numpy"
  }
}
```

Plain audit output remains unchanged.

## Current Analyzer Scope

Documentation audit plugins are only required when an analyzer emits source
documentation that has a language-level convention worth validating. For the
current first-party analyzer set:

- `python` uses NumPy or Google-style audit plugins.
- `c` and `cpp` use the Doxygen audit plugin.
- `rust` uses the Rustdoc audit plugin.
- `javascript` uses the JSDoc audit plugin and `typescript` uses the TSDoc
  audit plugin.
- `go` uses the Go-doc-comments audit plugin.
- `json` does not require an audit plugin because standard JSON has no
  comments.
- `markdown` and `text` are documentation artifact analyzers, not source
  docstring/comment convention analyzers.
- `bash` has comment practices but no single documentation convention that is
  stable enough to audit as a first-party default.

When a future analyzer targets a language with a standard documentation
convention, add the matching documentation audit plugin and routing examples in
the same analyzer rollout.
