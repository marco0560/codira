"""Report physical Python line categories for selected repository roots.

Parameters
----------
None

Returns
-------
None
    The module exposes a command-line inventory utility.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

DEFAULT_ROOTS = ("src", "packages", "tests", "scripts")
OutputFormat = Literal["text", "json"]


@dataclass(frozen=True)
class PythonLineInventory:
    """Describe physical lines for one Python source file.

    Parameters
    ----------
    root : str
        Requested repository root containing the file.
    path : str
        Repository-relative Python file path.
    total_lines : int
        Total physical lines.
    code_lines : int
        Nonblank, non-comment-only physical lines.
    comment_lines : int
        Comment-only lines and lines occupied by Python docstrings.
    blank_lines : int
        Whitespace-only physical lines.

    Returns
    -------
    None
        Instances hold one deterministic inventory record.
    """

    root: str
    path: str
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the Python line inventory.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser configured with roots, threshold, and output-format options.
    """
    parser = argparse.ArgumentParser(
        description="List Python files over a physical-line threshold."
    )
    parser.add_argument(
        "roots",
        nargs="*",
        default=DEFAULT_ROOTS,
        help="Repository-relative roots to inspect (default: src packages tests scripts).",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=1500,
        help="Strictly greater-than total-line threshold (default: 1500).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output representation (default: text).",
    )
    return parser


def inventory_file(root: str, path: Path, repository_root: Path) -> PythonLineInventory:
    """Count physical Python line categories for one file.

    Parameters
    ----------
    root : str
        Requested repository-relative source root.
    path : pathlib.Path
        Python source file to classify.
    repository_root : pathlib.Path
        Repository root used to render a stable relative path.

    Returns
    -------
    PythonLineInventory
        Deterministic physical line counts for ``path``.
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    blank_lines = sum(not line.strip() for line in lines)
    docstring_lines = _docstring_line_numbers(source)
    comment_lines = sum(
        line.lstrip().startswith("#") or line_number in docstring_lines
        for line_number, line in enumerate(lines, start=1)
    )
    total_lines = len(lines)
    return PythonLineInventory(
        root=root,
        path=path.relative_to(repository_root).as_posix(),
        total_lines=total_lines,
        code_lines=total_lines - blank_lines - comment_lines,
        comment_lines=comment_lines,
        blank_lines=blank_lines,
    )


def _docstring_line_numbers(source: str) -> set[int]:
    """Return physical line numbers occupied by Python docstrings.

    Parameters
    ----------
    source : str
        Complete decoded Python source text.

    Returns
    -------
    set[int]
        One-based line numbers in module, class, and function docstrings.
    """
    result: set[int] = set()

    def collect(body: list[ast.stmt]) -> None:
        """Collect leading string expressions from one AST body.

        Parameters
        ----------
        body : list[ast.stmt]
            Statements belonging to a module, class, or function body.

        Returns
        -------
        None
            Docstring line numbers are added to the enclosing result set.
        """
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            end_lineno = body[0].end_lineno or body[0].lineno
            result.update(range(body[0].lineno, end_lineno + 1))
        for statement in body:
            if isinstance(
                statement, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)
            ):
                collect(statement.body)

    tree = ast.parse(source)
    collect(tree.body)
    return result


def inventory_roots(
    roots: tuple[str, ...], threshold: int, repository_root: Path
) -> list[PythonLineInventory]:
    """Inventory Python files exceeding a total-line threshold by root.

    Parameters
    ----------
    roots : tuple[str, ...]
        Repository-relative directories to search.
    threshold : int
        Strictly greater-than total physical-line threshold.
    repository_root : pathlib.Path
        Repository root containing all requested roots.

    Returns
    -------
    list[PythonLineInventory]
        Matching files, sorted first by requested root then descending size.

    Raises
    ------
    ValueError
        If a root is missing, not a directory, or the threshold is negative.
    """
    if threshold < 0:
        msg = "threshold must be non-negative"
        raise ValueError(msg)

    records: list[PythonLineInventory] = []
    for root in roots:
        root_path = repository_root / root
        if not root_path.is_dir():
            msg = f"root is not a directory: {root}"
            raise ValueError(msg)
        for path in root_path.rglob("*.py"):
            record = inventory_file(root, path, repository_root)
            if record.total_lines > threshold:
                records.append(record)
    return sorted(
        records, key=lambda record: (record.root, -record.total_lines, record.path)
    )


def render_text(records: list[PythonLineInventory], roots: tuple[str, ...]) -> str:
    """Render one tabular result list for each requested root.

    Parameters
    ----------
    records : list[PythonLineInventory]
        Matching inventory records.
    roots : tuple[str, ...]
        Requested roots in display order.

    Returns
    -------
    str
        Stable, newline-delimited root sections and line-count tables.
    """
    lines: list[str] = []
    for root in roots:
        lines.append(f"{root}:")
        matching = [record for record in records if record.root == root]
        if not matching:
            lines.append("  (none)")
            continue
        headers = ("path", "total", "code", "comment", "blank")
        rows = [
            (
                record.path,
                str(record.total_lines),
                str(record.code_lines),
                str(record.comment_lines),
                str(record.blank_lines),
            )
            for record in matching
        ]
        widths = tuple(
            max(len(value) for value in column)
            for column in zip(headers, *rows, strict=True)
        )
        lines.append(
            "  "
            + "  ".join(
                value.ljust(width) if index == 0 else value.rjust(width)
                for index, (value, width) in enumerate(
                    zip(headers, widths, strict=True)
                )
            )
        )
        lines.extend(
            "  "
            + "  ".join(
                value.ljust(width) if index == 0 else value.rjust(width)
                for index, (value, width) in enumerate(zip(row, widths, strict=True))
            )
            for row in rows
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the Python line inventory command.

    Parameters
    ----------
    argv : list[str] | None, optional
        Explicit command-line arguments. ``None`` reads process arguments.

    Returns
    -------
    int
        Zero after rendering a complete inventory.
    """
    args = build_parser().parse_args(argv)
    roots = tuple(args.roots)
    records = inventory_roots(roots, args.threshold, Path.cwd())
    if args.format == "json":
        print(json.dumps([asdict(record) for record in records], indent=2))
    else:
        print(render_text(records, roots))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
