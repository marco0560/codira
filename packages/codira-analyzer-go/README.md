# Codira Go analyzer

Syntax-only first-party Go analysis for packages, imports, declarations, calls,
references, and explicitly attached Go documentation comments.

Blank identifiers are not indexed as symbols. Package initialization functions
retain separate declaration identities, documentation, and calls, including
multiple `init` functions in the same file. Their IDs include the declaration
line and column; moving an initialization function changes that identity.
