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

- analyzer names must be unique across built-ins and external plugins
- duplicate names are rejected deterministically
- analyzers participate after built-ins in deterministic discovery order
- analyzer discovery globs must be stable and sufficient for scanner
  candidate discovery
- scanner discovery confirms ownership through `supports_path(path)` before a
  file enters the indexing set, so broad globs are allowed only when
  `supports_path()` deterministically rejects unsupported files
- uncovered tracked files under `src/`, `tests/`, and `scripts/` will be
  surfaced by the index coverage audit when no analyzer claims them
- `codira cov` is the operator-facing way to verify whether your
  analyzer closes those gaps
- analyzers must not own storage or query persistence
