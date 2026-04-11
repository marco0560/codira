# Plugin Development

This section is for third-party plugin authors.

You do not need to modify the `codira` source tree to add a new analyzer or
backend. Install your plugin package into the same Python environment as
`codira`, expose an entry point, and verify discovery with:

```bash
codira plugins
codira plugins --json
```

The plugin system currently supports two extension families:

- analyzers through the `codira.analyzers` entry-point group
- backends through the `codira.backends` entry-point group

The `codira plugins` surface also classifies each discovered plugin as:

- `origin=core`
- `origin=first_party`
- `origin=third_party`

Copyable example packages live under:

- `examples/plugins/codira_demo_analyzer`
- `examples/plugins/codira_demo_backend`

Start here:

- [Quick start](getting-started.md)
- [Analyzer plugins](analyzers.md)
- [Backend plugins](backends.md)
- [Packaging and install](packaging.md)
- [Tutorial](tutorial.md)
