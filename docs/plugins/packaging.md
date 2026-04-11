# Packaging And Install

Plugin discovery uses standard Python entry points.

Current groups:

- `codira.analyzers`
- `codira.backends`

Install model:

- `codira` core stays installable on its own
- third-party plugins are separate distributions
- official first-party plugins also use separate distributions under `packages/`
- plugins are discovered from the current Python environment
- `codira plugins` reports `origin=core`, `origin=first_party`, or
  `origin=third_party` to clarify ownership

Typical local workflow:

```bash
source .venv/bin/activate
python ../codira/scripts/install_first_party_packages.py \
  --python "$VIRTUAL_ENV/bin/python" \
  --include-core
pip install -e /path/to/codira-demo-analyzer
codira plugins
```

Copyable example distributions live under:

- `examples/plugins/codira_demo_analyzer`
- `examples/plugins/codira_demo_backend`

Repository-owned first-party distributions now live under:

- `packages/codira-analyzer-python`
- `packages/codira-analyzer-json`
- `packages/codira-analyzer-c`
- `packages/codira-analyzer-bash`
- `packages/codira-backend-sqlite`
- `packages/codira-bundle-official`

The authoritative repository-local editable install set for those packages is
defined by:

```bash
python scripts/install_first_party_packages.py
```

The accepted published umbrella install name for the curated official set is
`codira[bundle-official]`. During the current monorepo phase, that umbrella
name is not a source-tree shortcut; repository contributors still install the
extracted packages from `packages/` through the helper above.

For optional dependencies inside a plugin package, declare them in the plugin's
own `pyproject.toml`. The core package should not need to know about them.

If a plugin fails to load, `codira plugins` reports the failure without
requiring you to inspect internal registry code.
