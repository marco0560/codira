<img src="https://raw.githubusercontent.com/marco0560/codira/main/docs/badges/cartoon_cold-2.png" alt="codira badge" width="120">

# codira-analyzer-cpp

First-party C++ analyzer plugin for `codira`.

Repository-local editable install:

```bash
source .venv/bin/activate
pip install -e ../codira
pip install -e ../codira/packages/codira-analyzer-cpp
```

After installation, verify discovery with:

```bash
codira plugins
codira cov
```

Package-local verification:

```bash
pytest -q packages/codira-analyzer-cpp/tests
```

## Ambiguous headers

The plugin discovers `.h` as well as C++ source and header suffixes. In automatic
mode, a C++-only same-stem `.cpp`/`.cc`/`.cxx` neighbour or parsed C++ constructs
(namespace, class, template, qualified name or reference) claims a `.h` file.
Comments and string literals do not count as evidence. Headers without such
evidence retain the C analyzer when it is installed. Shared same-stem C/C++
translation units alone are ambiguous.

Use `[plugins.analyzer-cpp] header_language = "cpp"` to explicitly claim otherwise
ambiguous headers, or `"c"` to leave all `.h` files to C. The default is `"auto"`.
Existing `include_paths` and `exclude_paths` apply before this decision, so an
explicit override can be limited to the intended header directories. The C++
plugin's optional path priority wins over an eligible generic C claim; equal
priorities preserve registration order. The core does not parse C++ to route it.
Build-system compilation flags and included-header macro definitions are not
inferred. Remaining parser recovery warnings still mean that indexed symbols
may be incomplete.

Header guards and nested conditional blocks are traversed for declarations,
class methods, documentation and includes. Both branches are retained as static
source evidence; compilation conditions are not evaluated. Function-local scopes
are not flattened into module declarations.

## Local annotation macros

When an initial parse has errors, the analyzer can recover object macros defined
in that file whose replacements are empty or consist of GNU, Microsoft or C++
attributes. Annotation aliases are resolved from the same file. All definitions
of a name must be compatible; function macros and names appearing in `#undef`
are excluded. Uses must follow their definition and the required alias definitions.

Recovery blanks eligible uses without moving byte coordinates. Definitions,
preprocessor conditions, comments and literals stay intact, and extraction reads
the original source for signatures and call positions. The recovered tree is used
only when it is wholly clean; unrelated syntax errors retain the original tree.
This does not evaluate compilation conditions or perform semantic validation.

## Linkage and record methods

Single and braced `extern "C"` / `extern "C++"` declarations retain their
written namespace and callable ownership. Record specifiers nested inside
variable declarations are visited as types. Structs and unions retain their
declaration kind; records with explicit methods also have a class-like method
container. Data-only records retain their declaration representation.

Nested records and template specializations keep distinct source names. Callable
slots use parameter syntax and cv/ref qualifiers, preserving overloads with
identical parameter names while merging renamed/defaulted redeclarations.
Lexical conditional branches remain separate source variants. No build
configuration is selected, and aliases or compiler-dependent type equivalence
are not resolved. Function-pointer fields remain data rather than functions.
