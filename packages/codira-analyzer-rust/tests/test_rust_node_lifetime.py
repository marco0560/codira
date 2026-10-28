"""Exercise native coordinate ownership through complete Rust analysis.

Parameters
----------
None

Returns
-------
None
    Defines subprocess regressions for non-cached coordinate integers.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("padding", ["row", "column"])
def test_rust_large_coordinates_survive_analysis_and_collection(
    tmp_path: Path, padding: str
) -> None:
    """Retain coordinates above CPython's small-integer cache through GC.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    padding : str
        Coordinate dimension moved above the small-integer cache.

    Returns
    -------
    None
        Analysis exits normally with exact source locations and call targets.

    Notes
    -----
    Tree-sitter 0.26.0's Point attribute getters return borrowed references.
    A child process contains the resulting native crash on an unfixed plugin.
    """
    prefix = "\n" * 300 if padding == "row" else " " * 300
    source = tmp_path / "coordinates.rs"
    source.write_text(
        prefix + "fn probe() { first(); second(); third(); }\n", encoding="utf-8"
    )
    program = """
import gc
import json
import sys
from pathlib import Path
from codira_analyzer_rust import build_analyzer

path = Path(sys.argv[1])
analyzer = build_analyzer()
for _ in range(20):
    result = analyzer.analyze_file(path, path.parent)
    function = result.functions[0]
    locations = [(call.target, call.lineno, call.col_offset) for call in function.calls]
    assert result.index_symbols
    gc.collect()
print(json.dumps([function.lineno, function.end_lineno, locations]), flush=True)
del result, function, analyzer
gc.collect()
"""
    completed = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", program, str(source)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    row = 301 if padding == "row" else 1
    column = 300 if padding == "column" else 0
    assert json.loads(completed.stdout) == [
        row,
        row,
        [
            ["first", row, column + 13],
            ["second", row, column + 22],
            ["third", row, column + 32],
        ],
    ]
