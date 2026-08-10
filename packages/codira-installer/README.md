# codira-installer

`codira-installer` is Codira's first-party setup distribution. It owns the
installer engine and Textual user interface; the core `codira` distribution
does not depend on Textual.

The package resolves versioned, JSON-exportable installation plans before it
executes anything. A plan may target the current environment, an existing
environment, or a new environment. PyPI installs support `uv` and bounded
`pip`; local-checkout installs use `uv` and the cloned Codira root explicitly.

The engine never emits shell strings, never uninstalls deselected packages, and
persists only a credential-free journal for fail-fast resume. Running
`codira-installer` (or `codira setup`) opens the Textual workflow. The same
request and plan engine also supports deterministic automation:

```bash
codira-installer --source local-checkout --checkout . --target existing \
  --environment /path/to/other-repo/.venv --plan codira-plan.json
codira-installer --apply codira-plan.json --journal .codira-installer-journal.json
codira-installer --resume codira-plan.json --journal .codira-installer-journal.json
```

The default local-checkout source is the current directory, so a user who has
cloned Codira can install that checkout into its own, a new, or another
repository's existing environment. The UI validates the complete plan before
enabling Apply; cancellation is cooperative between steps, preserving the
journal and never interrupting an atomic replacement.

Optional model provisioning runs inside the selected target environment. Hardware
inspection yields a reviewable recommendation, while calibration changes require
a separate confirmation. Indexing and query daemon service actions are explicit,
repository-scoped, and never elevate privileges.
