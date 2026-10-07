# CPython Failure Classification

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-05-11-cpython-failures-classification.md`
(SHA-256 `4676e65d94378a1f0323b316a0ba725fe3fd672ad1a76bf6e2648dd7d75f2238`).

The explicit artifact/input paths were checked in this checkout. Availability
does not establish that old measurements apply to the current version.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/analysis/cython_failures.txt` | available |


## Scope

Input:

- `.artifacts/analysis/cython_failures.txt`

Target repository:

- `local corpus/cpython`

Goal:

- separate failures that are source-side syntax or intentionally invalid source
- identify Codira-side failures or unexpected cases worth fixing
- outline a fix plan for the Codira-side buckets only

## Summary

Total failures: `66`

- repo-side syntax or intentionally invalid source: `53`
- Codira-side duplicate stable-id failures: `11`
- Codira-side Python source decoding failures: `2`

## Repo-Side Syntax Or Intentionally Invalid Source

These are not worth spending time on for Codira right now.

They include:

- newer Python syntax not accepted by the runtime/parser Codira is currently using
- intentionally invalid syntax fixtures in the CPython test tree
- older-style syntax that is invalid for the interpreter parsing the file

Examples:

- t-string syntax in annotationlib.py (`cpython/Lib/annotationlib.py:347`, historical source)
- `lazy import` syntax in ast.py (`cpython/Lib/ast.py:24`, historical source)
- intentionally invalid lazy-import fixture in lazy_future_import.py (`cpython/Lib/test/test_lazy_import/data/badsyntax/lazy_future_import.py:1`, historical source)
- intentionally invalid tokenization fixture in badsyntax_3131.py (`cpython/Lib/test/tokenizedata/badsyntax_3131.py:2`, historical source)
- old exception syntax in site.py (`cpython/Lib/site.py:582`, historical source)

## Codira-Side Bucket 1: Source Decoding Failures

Affected files:

- module_iso_8859_1.py (`cpython/Lib/test/encoded_modules/module_iso_8859_1.py:1`, historical source)
- module_koi8_r.py (`cpython/Lib/test/encoded_modules/module_koi8_r.py:1`, historical source)

Why this is on Codira:

- the Python parser currently does a hardcoded UTF-8 text read in parser_ast.py (`src/codira/parser_ast.py:979`, historical source)
- both failing files carry explicit encoding cookies and are valid Python source in those encodings

Fix plan:

1. Move Python source decoding ownership into the Python analyzer package rather than adding more Python-specific reading logic to core.
2. Replace the hardcoded UTF-8 read used by the Python analysis path with an analyzer-local helper that honors PEP 263 encoding cookies.
3. Keep the fix package-scoped inside `codira_analyzer_python`, either by introducing a local source-reading helper or by moving `parse_file()` ownership into the analyzer package.
4. Add targeted tests with non-UTF-8 fixture files that assert indexing succeeds and does not downgrade them to file failures.

Recommended implementation direction:

- use `tokenize.open()` or `tokenize.detect_encoding()` rather than a custom cookie parser
- do not introduce a shared Python-source reader in `src/codira/` unless a separate contract change explicitly justifies that coupling

## Codira-Side Bucket 2: Duplicate Stable IDs

Affected files:

- Lib/importlib/resources/_common.py (`cpython/Lib/importlib/resources/_common.py:47`, historical source)
- Lib/test/test_dynamicclassattribute.py (`cpython/Lib/test/test_dynamicclassattribute.py:75`, historical source)
- Lib/test/test_importlib/metadata/_path.py (`cpython/Lib/test/test_importlib/metadata/_path.py:77`, historical source)
- Lib/test/test_importlib/resources/_path.py (`cpython/Lib/test/test_importlib/resources/_path.py:75`, historical source)
- Lib/test/test_importlib/test_abc.py (`cpython/Lib/test/test_importlib/test_abc.py:54`, historical source)
- Lib/test/test_importlib/test_util.py (`cpython/Lib/test/test_importlib/test_util.py:309`, historical source)
- Lib/test/test_property.py (`cpython/Lib/test/test_property.py:70`, historical source)
- Lib/test/test_tools/i18n_data/messages.py (`cpython/Lib/test/test_tools/i18n_data/messages.py:80`, historical source)
- Lib/tkinter/messagebox.py (`cpython/Lib/tkinter/messagebox.py:42`, historical source)
- Modules/_decimal/libmpdec/literature/fnt.py (`cpython/Modules/_decimal/libmpdec/literature/fnt.py:95`, historical source)
- Tools/c-analyzer/c_parser/parser/_func_body.py (`cpython/Tools/c-analyzer/c_parser/parser/_func_body.py:41`, historical source)

Why this is on Codira:

- Codira currently builds Python stable IDs from only module name plus symbol name or declaration kind in normalization.py (`src/codira/normalization.py:43`, historical source)
- index-time duplicate detection then rejects any repeated stable IDs in one analyzed file in indexer.py (`src/codira/indexer.py:643`, historical source)
- the duplicate check is downstream of analysis; the analyzer is effectively stateless here and does not keep a running set of seen IDs while walking the AST

Observed collision shapes:

- multiple singledispatch registrations all named `_`
- repeated class names in one module
- repeated constants in one module
- repeated top-level function names in one module
- repeated method names within one class

### About Special-Casing `_`

Treating `_` as a special case in the Python analyzer could reduce a subset of the failures:

- it would help the singledispatch-style duplicates in `_common.py`, `_path.py`, and `messages.py`

But it is not sufficient as the main fix.

It would not address:

- repeated class names in `test_abc.py` and `test_util.py`
- repeated constants in `messagebox.py` and `fnt.py`
- repeated named methods in `test_property.py` and `test_dynamicclassattribute.py`
- repeated named functions in `_func_body.py`

Conclusion:

- `_` can be treated as one test case
- `_` should not be the core heuristic
- the real fix should be generic duplicate disambiguation for Python artifacts

Fix plan:

1. Add characterization tests covering each observed collision shape from the CPython sample:
   - duplicate `_` functions
   - duplicate named top-level functions
   - duplicate class names
   - duplicate constant names
   - duplicate method names in one class
2. Keep the existing stable ID format unchanged for non-colliding symbols.
3. Add analyzer-side duplicate detection and deterministic disambiguation before the Python analyzer returns its `AnalysisResult`.
4. Apply the same policy across Python classes, functions, methods, and declarations so collision handling is uniform.
5. Preserve the existing special handling for property setter and deleter stable IDs.
6. Keep overload stable IDs as-is because they already have explicit ordinals in normalization.py (`src/codira/normalization.py:116`, historical source).
7. Treat `_` as one regression case, not as the main heuristic.

Recommended implementation direction:

- build base stable IDs exactly as today
- perform a post-normalization duplicate pass over Python artifacts within one `AnalysisResult`, inside the analyzer-owned normalization/output assembly path
- append deterministic suffixes only to colliding artifacts, for example by ordinal in declaration order
- document the invariant generically for all analyzers, then implement code changes only in analyzers that show real collisions

Why this direction is safer than `_` special-casing:

- it solves all observed collision shapes
- it keeps singleton stable IDs stable
- it avoids one-off name heuristics that would need to expand again later

Contract conclusion:

- the uniqueness invariant belongs to the analyzer contract, not to Python alone
- the indexer should keep enforcing that invariant, but analyzers should emit internally unique stable IDs before persistence
- immediate implementation work is required only where observed collisions exist; the contract itself should apply to all analyzers, including third-party analyzers

## Recommended Next Work Order

1. Fix Python source decoding with encoding-cookie-aware reads.
2. Add CPython-derived regression fixtures for duplicate stable-ID shapes.
3. Implement generic duplicate disambiguation for Python artifacts.
4. Re-run the CPython trial index and confirm the remaining failures are only the repo-side syntax or intentionally invalid source cases.
