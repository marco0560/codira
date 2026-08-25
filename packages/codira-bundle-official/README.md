<img src="https://raw.githubusercontent.com/marco0560/codira/main/docs/badges/cartoon_cold-2.png" alt="codira badge" width="120">

# codira-bundle-official

Curated first-party plugin bundle for `codira`, including the optional
`codira-installer` guided setup interface.

This meta-package establishes the accepted umbrella name for the official
plugin set introduced by ADR-007.

When the first-party distributions are published normally, this package will be
the user-facing install target for the curated bundle.

Install it with `python -m pip install codira-bundle-official`, then run
`codira-installer` for guided setup. The installer is documented in the
[installer guide](https://marco0560.github.io/codira/installer/).

The optional `faiss` extra installs the first-party FAISS similarity-index
plugin: `python -m pip install "codira-bundle-official[faiss]"`. Exact core
similarity is installed in every bundle and remains the default.

Package-local verification:

```bash
pytest -q packages/codira-bundle-official/tests
```
