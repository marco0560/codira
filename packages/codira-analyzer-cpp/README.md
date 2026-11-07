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

## Call targets

Explicit template calls retain their argument spelling in the target. Namespace
separators inside an argument do not split the surrounding call: for example,
`api::f<api::Box<int>>(value)` has base `api` and target
`f<api::Box<int>>`. Named C++ casts are conversions; their operand calls are
retained without recording an additional call for the cast keyword.

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

## Explicit include search roots

The analyzer can read contained headers through explicitly configured search roots:

```toml
[plugins.analyzer-cpp]
include_search_paths = ["include", "llvm/include"]
```

Use the paths declared by the repository's build or test configuration. Paths are
ordered and relative to the indexed repository; absolute paths inside that
repository are also accepted. Quoted includes search their own directory first;
angle includes search the configured roots. No external system headers are read.
The default is an empty list, and no build flags or ancestor roots are inferred.

`include_search_paths` resolves header dependencies. The separate `include_paths`
and `exclude_paths` options filter which source files the plugin analyzes.
Header contents, failed lookups, root order and symlink targets participate in
incremental invalidation. Missing headers remain explicit unresolved inputs.

Annotation definitions can come from resolved headers as well as the source file.
This does not expand general function macros or select conditional compilation.

## Source-defined annotation and specifier macros

When an initial parse has errors, the analyzer can recover object macros defined
in that file or resolved contained headers whose replacements are empty or consist
of GNU, Microsoft or C++ attributes, `inline`, `constexpr`, or combinations of
these. Aliases are resolved from the same captured inputs. Replacements that
change types or linkage remain unsupported. All definitions
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

Repeated record declarations share a semantic identity. A complete definition
supplies the record's source range, written body and attached documentation;
earlier or later forward declarations do not replace that definition. Types
without a definition retain their first declaration. Source movement preserves
record and method identities.

Nested records and template specializations keep distinct source names. Callable
slots use parameter syntax and cv/ref qualifiers, preserving overloads with
identical parameter names while merging renamed/defaulted redeclarations.
Lexical conditional branches remain separate source variants. No build
configuration is selected, and aliases or compiler-dependent type equivalence
are not resolved. Function-pointer fields remain data rather than functions.

## Source-defined namespace macros

When parsing remains partial, object macros may expand to complete namespace
openings or closings. Literal namespace names, nested inline scopes and aliases
are supported when every captured replacement resolves identically. A source map
retains original byte offsets, lines, columns, function signatures and calls even
when an expansion is longer than its invocation. Namespace identities use the
expanded names; declaration snippets retain the original source.

Function macros, undefinitions, conflicting alternatives, unresolved uppercase
namespace names and expansions over 4096 bytes remain unsupported. A recovered
tree must be wholly clean. This does not infer a generated ABI configuration,
select a compilation branch or add a compiler dependency.

An explicit namespace name normally supplied through compiler definitions can be
provided for namespace declarations:

```toml
[plugins.analyzer-cpp]
include_search_paths = ["libc"]
namespace_macro_definitions = { LIBC_NAMESPACE = "__llvm_libc" }
```

Use a binding declared by the repository's build configuration. Names and values
must be single identifiers; provider keyword tokens are rejected. Captured object
aliases may add namespace attributes when every alternative resolves to the same
name. Source overrides and ambiguous reaching aliases fail explicitly. The profile
participates in incremental reuse identity. Definitions do not select compilation
branches or substitute general expressions. Combining namespace-name bindings with
an already expanded variable-width scope wrapper remains unsupported.

## Explicit declaration-macro profiles

The optional `preprocessor_definitions` mapping enables bounded declaration-macro
analysis under an explicit initial preprocessing profile. Each value is a string
object replacement, `true` for replacement `1`, `false` for explicitly undefined,
or `{ defined = true }` for known-defined with an unavailable replacement. Missing
states remain unknown; an empty mapping enables analysis without assuming that
unlisted macros are undefined. Omitting the mapping preserves ordinary analysis.

For example, a repository that supplies the following build facts can express
them without a compiler dependency during indexing:

```toml
[plugins.analyzer-cpp.preprocessor_definitions]
PROJECT_FEATURE = "1"
PROJECT_DISABLED_FEATURE = false
OPAQUE_COMPILER_MACRO = { defined = true }
```

The analyzer follows captured include and directive order, source overrides,
undefinitions and include guards. Selected object/function macros may use argument
substitution, prescan, stringification and token pasting within explicit bounds.
Unknown required conditions, unsupported semantics and exhausted bounds retain
partial diagnostics rather than selecting a convenient branch. A complete
project profile may require many more initial facts than the example above.

Generated free-function definitions, prototypes and aliases retain their actual
names and namespace ownership. A generated `decltype` declaration requires a
unique active, earlier source declaration with compatible source-spelled types.
Prototypes retain unnamed parameters instead of borrowing implementation names;
aliases retain their proven target without acquiring the implementation body.
Unsupported ownership or type inference remains explicit.

Generated metadata carries invocation anchors, captured macro inputs and token
derivations separately from physical spelling locations. Original body calls keep
their original coordinates. SQLite and DuckDB persist this provenance, and symbol
evidence validates its source and dependency identity before returning it.
Configuration and dependency changes invalidate incremental reuse. See
[ADR-034](../../docs/adr/ADR-034-bounded-cpp-declaration-macro-analysis.md) for the
architecture and original-file qualification requirements.
