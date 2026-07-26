# Analyzer Plugins

Analyzer plugins must return an object implementing
`codira.contracts.LanguageAnalyzer`.

The smallest working example lives at
`examples/plugins/codira_demo_analyzer`.

Required attributes and methods:

- `name: str`
- `version: str`
- `discovery_globs: tuple[str, ...]`
- `supports_path(path: Path) -> bool`
- `analyze_file(path: Path, root: Path) -> AnalysisResult`

Concurrent indexing is opt-in for plugins. Implement
`analyzer_concurrency_declaration()` and return an
`AnalyzerConcurrencyDeclaration` to permit process or thread workers. Thread
support also requires `reentrant_after_configure = True`. Plugins without this
declaration remain serial in auto mode; explicit concurrent modes reject an
active undeclared plugin before backend initialization.

Minimal example:

```python
from pathlib import Path

from codira.contracts import LanguageAnalyzer
from codira.models import AnalysisResult, ModuleArtifact


class DemoAnalyzer:
    name = "demo"
    version = "1"
    discovery_globs = ("*.demo",)

    def supports_path(self, path: Path) -> bool:
        return path.suffix == ".demo"

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        relative = path.with_suffix("").relative_to(root)
        module_name = ".".join(relative.parts)
        return AnalysisResult(
            source_path=path,
            module=ModuleArtifact(
                name=module_name,
                stable_id=f"demo:module:{relative.as_posix()}",
                docstring=None,
                has_docstring=0,
            ),
            classes=(),
            functions=(),
            declarations=(),
            imports=(),
        )


def build_analyzer() -> LanguageAnalyzer:
    return DemoAnalyzer()
```

Register it in `pyproject.toml`:

```toml
[project.entry-points."codira.analyzers"]
demo = "codira_demo_analyzer:build_analyzer"
```

Rules:

- analyzer names must be unique across registered plugins
- duplicate names are rejected deterministically
- analyzers participate in deterministic discovery order
- analyzer discovery globs must be stable and sufficient for scanner
  candidate discovery
- scanner discovery confirms ownership through `supports_path(path)` before a
  file enters the indexing set, so broad globs are allowed only when
  `supports_path()` deterministically rejects unsupported files
- analyzers must emit stable IDs that are unique within one returned
  `AnalysisResult`; if a language can produce same-name collisions in one file,
  the analyzer must disambiguate them deterministically before returning
- when `[index.coverage]` does not override `roots`, the coverage audit uses
  the deterministic union of the roots declared by active analyzers; the
  first-party Python analyzer defaults to `src/`, `tests/`, and `scripts/`
- configured `roots` replace the analyzer defaults, while `roots = ["-"]`
  disables coverage auditing; see
  [Coverage roots](../configuration.md#coverage-roots)
- configured `exclude_suffixes` silence intentionally unsupported tracked file
  types after root selection, for example `.yml`, `.dot`, `.js`, or `.svg`
- `codira cov` is the operator-facing way to verify whether your
  analyzer closes those gaps
- analyzers must not own storage or query persistence
