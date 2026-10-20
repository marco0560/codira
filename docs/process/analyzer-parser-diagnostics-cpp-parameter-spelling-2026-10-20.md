# C++ original parameter forms — 2026-10-20

## Shared comparison cause

Twenty originals in the 650-file native-compatible cohort have 30 profile cases stopped by parameter-type comparison. The source metadata preserves original array forms, aliases and parameter attributes, while the native AST inventory reports adjusted types. Examples include `double []` versus `double *`, `va_list` versus `__va_list_tag *`, and a `[[maybe_unused]]` prefix absent from the native type spelling. These are distinct representation contracts, not twenty established analyzer defects.

The native probe in `cpp-native-parameter-cursors-prototype-r3/` records Clang's original parameter types, canonical function parameter types, names, linkage, expansion locations and physical attribute sources. It uses the actual compiler's full argv, the recorded resource directory and a hash-bound Clang 22 library. The first control rejects an assumption that the original type API was already adjusted; that failed control remains preserved. The final probe records the two forms separately.

`cpp_native_parameter_types_r2.py` requires the same native callable name, definition role, expansion anchor, mangled name and parameter names. Each AST inventory type must agree with the native original or canonical function parameter form. Metadata parameter types must then match the native original form, retaining array bounds and alias spelling. Only physically bound `[[maybe_unused]]` prefixes are attached; unknown attribute shapes remain holds. This introduces no generic typedef, namespace or ABI equivalence rule and does not erase array dimensions.

## Independent controls and actual originals

`cpp-native-parameter-types-controls-r2/` proves all three generated roles using an earlier declaration with array bound two and a definition with bound three. It preserves their distinct original forms despite identical adjusted pointer types. All 21 mutations reject: changed bounds, aliases, attributes, callable names, linkage, expansion anchors and native parameter types. Missing attribute source bytes also reject.

`cpp-native-parameter-types-20-capture-r2/` completes all 40 native cases and snapshots the referenced physical sources. `cpp-native-compatible-650-artifact-grading-r5/` compares 1,300 cases, passes 943 cases and 447 originals under both modes, with zero prior passes lost. All 30 original type holds are removed; subsequent call/declaration/profile holds remain visible. Only **six originals** newly pass the entire comparison under both modes. Existing artifact and macro corruption controls remain rejected.

`cpp-native-parameter-types-6-cli-index-r1/` completes both production indexes without failures. `cpp-native-parameter-types-6-index-verification-r1/` passes all 12 stored-artifact comparisons and six actual CLI commands. Classification v48 admits only these six, checking 12 definitions, six prototypes, six aliases and 14 source-call records. `cpp24-native-parameter-types-admission-v48-r1.json` binds the native proof, source, metadata, storage and unchanged repository gate. The independent audit preserves all original identities, every prior fixed/separated row and all 25,756 other v47 rows.

The authoritative ledger is **3,970 verified fixes, 453 separated inputs and 21,339 open originals** (C 5,611; C++ 15,728). The wrapper inventory has **423 open originals**. Production source/assets remain byte-identical to tested implementation `3c63c0abc6e5785c5690d62e095d66a6f7953c7c`; the existing full gate remains source-bound. Native-only and helper controls contribute no admissions.

## Exposed parser issue

The next layer includes a reproducible missing call in actual LLVM `vsscanf.cpp`: a direct local constructor initializer containing `cpp::numeric_limits<size_t>::max()`. Tree-sitter represents the ambiguous initializer as a function declarator, so call-expression traversal misses the nested `max()` call. A local value parameter supplies a potential disambiguation proof; a valid local function declaration using a type of the same spelling must remain untouched. No parser change or admission for this issue has been made yet. The complete remediation goal remains active across every original language and repository.
