<img src="https://raw.githubusercontent.com/marco0560/codira/main/docs/badges/cartoon_cold-2.png" alt="codira badge" width="120">

# codira-bundle-official

Curated first-party plugin bundle for `codira`.

This meta-package establishes the accepted umbrella name for the official
plugin set introduced by ADR-007.

When the first-party distributions are published normally, this package will be
the user-facing install target for the curated bundle.

Package-local verification:

```bash
pytest -q packages/codira-bundle-official/tests
```
