"""Check source-backed parameter identities and conservative rejection cases.

Parameters
----------
None

Returns
-------
None
    Verifies metadata without rewriting written declarations or call positions.
"""

from pathlib import Path

import pytest

from codira_analyzer_c import CAnalyzer


@pytest.mark.parametrize(
    ("header", "parameter", "expected"),
    [
        ("#define ARGS Context fcinfo\n", "ARGS", ("fcinfo",)),
        (
            "#define UNUSED(name) _unused_ ## name\n",
            "int UNUSED(ignored)",
            ("_unused_ignored",),
        ),
        (
            "#if HOST\n#define UNUSED(name) _unused_ ## name __attribute__((unused))\n"
            "#elif OTHER\n#define UNUSED(name) __pragma(warning(push)) __pragma(warning(suppress:4100)) _unused_ ## name __pragma(warning(pop))\n"
            "#else\n#define UNUSED(name) _unused_ ## name\n#endif\n",
            "int UNUSED(ignored)",
            ("_unused_ignored",),
        ),
        ("#define UNUSED(name) name\n", "int UNUSED(ignored)", ("ignored",)),
        (
            "#define UNUSED(name) _unused_ ## name\n",
            "Object *UNUSED(ignored)",
            ("_unused_ignored",),
        ),
        (
            "#define UNUSED(name) _unused_ ## name\n",
            "Object **UNUSED(ignored)",
            ("_unused_ignored",),
        ),
        (
            "#define UNUSED(name) _unused_ ## name\n",
            "Object *const UNUSED(ignored)",
            ("_unused_ignored",),
        ),
        ("#define UNUSED(name) int name\n", "int UNUSED(ignored)", ("UNUSED",)),
        ("#define UNUSED(name) other(name)\n", "int UNUSED(ignored)", ("UNUSED",)),
        ("#define UNUSED(name) name + 1\n", "int UNUSED(ignored)", ("UNUSED",)),
        (
            "#define UNUSED(name) name\n#undef UNUSED\n",
            "int UNUSED(ignored)",
            ("UNUSED",),
        ),
        (
            "#if HOST\n#define UNUSED(name) a_ ## name\n#else\n#define UNUSED(name) b_ ## name\n#endif\n",
            "int UNUSED(ignored)",
            ("UNUSED",),
        ),
        ("#define ARGS Context fcinfo\n#undef ARGS\n", "ARGS", ()),
        ("#define ARGS const fcinfo\n", "ARGS", ()),
        ("#define ARGS Context fcinfo\n#undef fcinfo\n", "ARGS", ()),
        ("#define ARGS Context fcinfo\n#define fcinfo other\n", "ARGS", ()),
        ("#define ARGS Context fcinfo\n#define Context int\n", "ARGS", ()),
        (
            "#define UNUSED(name) _unused_ ## name\n#define ignored renamed\n",
            "int UNUSED(ignored)",
            ("UNUSED",),
        ),
        ("#define ARGS Context fcinfo\n#define ARGS(name) name\n", "ARGS", ()),
        ("#define UNUSED(name, extra) name\n", "int UNUSED(ignored)", ("UNUSED",)),
    ],
)
def test_parameter_macro_identity(
    tmp_path: Path, header: str, parameter: str, expected: tuple[str, ...]
) -> None:
    """Require compatible alternatives and retain original source artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned repository boundary.
    header : str
        Captured macro definitions and invalidations.
    parameter : str
        Written parameter spelling.
    expected : tuple[str, ...]
        Proven identity or unchanged fallback for rejected candidates.

    Returns
    -------
    None
        Names, raw signature and call coordinates satisfy the contract.
    """
    (tmp_path / "api.h").write_text(header)
    source = f'#include "api.h"\nint run({parameter}) {{ return callee(); }}\n'
    path = tmp_path / "main.c"
    path.write_text(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(f for f in result.functions if f.name == "run")
    assert function.parameters == expected
    assert function.signature == f"int run({parameter})"
    assert [(c.target, c.lineno, c.col_offset) for c in function.calls] == [
        ("callee", 2, source.splitlines()[1].index("callee"))
    ]


def test_parameter_definitions_are_not_available_before_include(tmp_path: Path) -> None:
    """Respect include boundaries while allowing explicit preincluded context.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source and header repository.

    Returns
    -------
    None
        Earlier prototypes retain absent names unless caller context supplies them.
    """
    (tmp_path / "api.h").write_text("#define ARGS Context fcinfo\n")
    path = tmp_path / "main.c"
    path.write_text('int first(ARGS);\n#include "api.h"\nint later(ARGS);\n')
    analyzer = CAnalyzer()
    result = analyzer.analyze_file(path, tmp_path)
    assert {f.name: f.parameters for f in result.functions} == {
        "first": (),
        "later": ("fcinfo",),
    }
    analyzer.configure({"preinclude_headers": ["api.h"]})
    result = analyzer.analyze_file(path, tmp_path)
    assert {f.name: f.parameters for f in result.functions} == {
        "first": ("fcinfo",),
        "later": ("fcinfo",),
    }
