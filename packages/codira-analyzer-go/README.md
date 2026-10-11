# Codira Go analyzer

Syntax-only first-party Go analysis for packages, imports, declarations, calls,
references, and explicitly attached Go documentation comments.

Blank identifiers are not indexed as symbols. Package initialization functions
retain separate declaration identities, documentation, and calls, including
multiple `init` functions in the same file. Their IDs include the declaration
line and column; moving an initialization function changes that identity.

Package variable and constant extraction accepts identifier nodes only and does
not enter function-literal initializers. Callback-local bindings are not emitted
as package declarations. Analyzer runtime revision 3 invalidates earlier cached
facts; grouped declarations retain each named binding and its declared kind.
