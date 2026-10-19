<img src="https://raw.githubusercontent.com/marco0560/codira/main/docs/badges/cartoon_cold-2.png" alt="codira badge" width="120">

# codira-analyzer-c

First-party C-family analyzer plugin for `codira`.

Repository-local editable install:

```bash
source .venv/bin/activate
pip install -e ../codira
pip install -e ../codira/packages/codira-analyzer-c
```

After installation, verify discovery with:

```bash
codira plugins
codira cov
```

Package-local verification:

```bash
pytest -q packages/codira-analyzer-c/tests
```

## Explicit C header context

The analyzer can recover source-backed annotations and function specifiers from
contained headers, using ordered search roots:

```toml
[plugins.analyzer-c]
include_search_paths = ["include"]
```

Quoted includes search their own directory first. System includes search only
these explicit roots. No dependency outside the indexed repository is read, and
missing ordinary includes remain recorded unresolved inputs.

Headers that normally rely on a caller can declare that context explicitly. For
example, relative to a CPython checkout:

```toml
[plugins.analyzer-c]
include_search_paths = ["Include", "Include/internal"]
preinclude_headers = ["Include/Python.h"]
```

For a PostgreSQL checkout, use `include_search_paths = ["src/include"]` and
`preinclude_headers = ["src/include/postgres.h"]`. A configured context header
must exist inside that repository. Its definitions are available before the
source begins; ordinary included definitions become available at their source
include boundary. Defaults are empty; caller context is never inferred by name.
No compiler or build command runs during analysis, and conditional branches are
not selected.

Compatible object macros containing annotations, `inline` variants or `_Noreturn`
can recover declarations without changing original signatures or coordinates.
Plain data-field macros can recover record bodies: the C model does not emit data
fields, and their original written text remains available for source signatures.
Conflicting definitions, undefinitions, function-like prefixes, macro-dependent
field types, nested types, constants, arrays, function fields and expressions
remain outside this recovery. The resulting complete tree must be clean.

Header bytes, lookup outcomes, search/context order, symlink targets and
configuration participate in incremental identity. A dependency change requires
fresh analysis even when source bytes and header modification time are unchanged.
