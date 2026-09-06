"""C++ parser setup, durable identities, and text normalization.

Responsibilities
----------------
- Configure the package-local tree-sitter C++ parser.
- Derive deterministic artifact identities and normalized source text.

Architectural role
------------------
This module contains syntax primitives shared by higher-level C++ tree
traversal and artifact extraction routines.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from tree_sitter import Language, Node, Parser
from tree_sitter_cpp import language

from codira.models import DeclarationKind

_LANGUAGE = Language(language())

_CPP_SYSTEM_FUNCTIONS = frozenset(
    {
        "begin",
        "emplace_back",
        "end",
        "make_pair",
        "make_shared",
        "move",
        "printf",
        "push_back",
        "size",
        "sort",
        "swap",
    }
)
_CPP_MACROS = frozenset(
    {
        "ASSERT_EQ",
        "ASSERT_FALSE",
        "ASSERT_TRUE",
        "EXPECT_EQ",
        "EXPECT_FALSE",
        "EXPECT_TRUE",
        "Py_DECREF",
        "Py_INCREF",
    }
)


def _new_parser() -> Parser:
    """
    Create a parser configured for the C++ grammar.

    Parameters
    ----------
    None

    Returns
    -------
    tree_sitter.Parser
        Parser configured for ``tree-sitter-cpp``.
    """
    return Parser(_LANGUAGE)


def _decode_source_text(source: bytes) -> str:
    """
    Decode one source fragment with a deterministic legacy fallback.

    Parameters
    ----------
    source : bytes
        Raw source bytes to decode.

    Returns
    -------
    str
        Text decoded as UTF-8 when possible, otherwise Latin-1.
    """
    try:
        return source.decode("utf-8")
    except UnicodeDecodeError:
        return source.decode("latin-1")


def _module_name_for_path(path: Path, root: Path) -> str:
    """
    Derive the logical module name for one C++ source path.

    Parameters
    ----------
    path : pathlib.Path
        Source file being analyzed.
    root : pathlib.Path
        Repository root used for relative module naming.

    Returns
    -------
    str
        Dotted module identity derived from the relative file path.
    """
    relative = path.relative_to(root).with_suffix("")
    return ".".join(relative.parts)


def _module_stable_id(path: Path, root: Path) -> str:
    """
    Build the durable identity for one C++ module.

    Parameters
    ----------
    path : pathlib.Path
        Source path being analyzed.
    root : pathlib.Path
        Repository root used for relative identity derivation.

    Returns
    -------
    str
        Durable C++ module identity.
    """
    return f"cpp:module:{path.relative_to(root).as_posix()}"


def _symbol_owner_id(path: Path, root: Path) -> str:
    """
    Build the file-scoped owner identity for C++ symbols.

    Parameters
    ----------
    path : pathlib.Path
        Source path being analyzed.
    root : pathlib.Path
        Repository root used for relative identity derivation.

    Returns
    -------
    str
        Repo-relative owner identity that preserves the source suffix.
    """
    return path.relative_to(root).as_posix()


def _class_stable_id(owner_id: str, class_name: str) -> str:
    """
    Build the durable identity for one C++ class.

    Parameters
    ----------
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    class_name : str
        Qualified class name.

    Returns
    -------
    str
        Durable C++ class identity.
    """
    return f"cpp:class:{owner_id}:{class_name}"


def _function_stable_id(
    owner_id: str,
    function_name: str,
    *,
    class_name: str | None = None,
) -> str:
    """
    Build the durable identity for one C++ callable.

    Parameters
    ----------
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    function_name : str
        Callable name to persist.
    class_name : str | None, optional
        Owning class name for method artifacts.

    Returns
    -------
    str
        Durable C++ function or method identity.
    """
    if class_name is None:
        return f"cpp:function:{owner_id}:{function_name}"
    return f"cpp:method:{owner_id}:{class_name}.{function_name}"


def _declaration_stable_id(
    owner_id: str,
    kind: DeclarationKind,
    declaration_name: str,
) -> str:
    """
    Build the durable identity for one C++ declaration artifact.

    Parameters
    ----------
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    kind : codira.models.DeclarationKind
        Stable declaration classifier.
    declaration_name : str
        Exposed declaration name.

    Returns
    -------
    str
        Durable C++ declaration identity.
    """
    return f"cpp:{kind}:{owner_id}:{declaration_name}"


def _enum_member_stable_id(
    owner_id: str,
    enum_name: str,
    ordinal: int,
) -> str:
    """
    Build the durable identity for one C++ enum member declaration.

    Parameters
    ----------
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    enum_name : str
        Owning enum declaration name.
    ordinal : int
        Deterministic declaration order among members for the enum.

    Returns
    -------
    str
        Durable C++ enum-member identity.
    """
    return f"cpp:enum_member:{owner_id}:{enum_name}:{ordinal}"


def _node_text(node: Node, source: bytes) -> str:
    """
    Decode the source text owned by one syntax node.

    Parameters
    ----------
    node : tree_sitter.Node
        Syntax node whose text should be decoded.
    source : bytes
        Full source buffer.

    Returns
    -------
    str
        Decoded node text with a deterministic legacy fallback.
    """
    return _decode_source_text(source[node.start_byte : node.end_byte])


def _normalize_signature(text: str) -> str:
    """
    Collapse one signature or declaration snippet into stable whitespace.

    Parameters
    ----------
    text : str
        Raw source text snippet.

    Returns
    -------
    str
        Whitespace-normalized text.
    """
    return " ".join(text.split())


def _qualified_name(parts: Sequence[str]) -> str:
    """
    Join one namespace or class path into C++ qualified text.

    Parameters
    ----------
    parts : collections.abc.Sequence[str]
        Qualified-name path components.

    Returns
    -------
    str
        `::`-joined qualified name.
    """
    return "::".join(part for part in parts if part)


def _split_qualified_name(text: str) -> tuple[str, ...]:
    """
    Split one C++ qualified identifier into components.

    Parameters
    ----------
    text : str
        Raw qualified identifier text.

    Returns
    -------
    tuple[str, ...]
        Non-empty qualified-name components.
    """
    normalized = text.replace(" ", "")
    return tuple(part for part in normalized.split("::") if part)


def _cpp_external_target_kind(base: str, target: str) -> str:
    """
    Classify one C++ call target for unresolved graph rendering.

    Parameters
    ----------
    base : str
        Static receiver or namespace qualifier.
    target : str
        Call target token.

    Returns
    -------
    str
        Analyzer-owned external target classifier.
    """
    if target in _CPP_MACROS or target.isupper():
        return "C++:<macro>"
    if base == "std" or base.startswith("std::") or target in _CPP_SYSTEM_FUNCTIONS:
        return "C++:<system-header>"
    return "C++:<external>"


def _comment_to_summary(text: str) -> str | None:
    """
    Normalize one raw C++ comment block into summary text.

    Parameters
    ----------
    text : str
        Raw comment text including delimiters.

    Returns
    -------
    str | None
        Normalized summary text, or ``None`` when no content remains.
    """
    stripped = text.strip()
    if stripped.startswith("/*"):
        body = stripped.removeprefix("/*").removesuffix("*/")
        lines = [line.strip().lstrip("*").strip() for line in body.splitlines()]
    else:
        lines = [
            line.strip().removeprefix("//").strip() for line in stripped.splitlines()
        ]
    normalized_lines = [line for line in lines if line]
    if not normalized_lines:
        return None
    return "\n".join(normalized_lines)


def _comment_to_doxygen_text(text: str) -> str | None:
    """
    Normalize one raw Doxygen comment block into documentation text.

    Parameters
    ----------
    text : str
        Raw comment text including delimiters.

    Returns
    -------
    str | None
        Normalized Doxygen text, or ``None`` when the comment is not Doxygen.
    """
    stripped = text.strip()
    if stripped.startswith(("/**", "/*!")):
        body = stripped[3:].removesuffix("*/")
        lines = [line.strip().lstrip("*").strip() for line in body.splitlines()]
    elif stripped.startswith(("///", "//!")):
        lines = []
        for line in stripped.splitlines():
            normalized = line.strip()
            if normalized.startswith(("///", "//!")):
                lines.append(normalized[3:].strip())
            else:
                return None
    else:
        return None

    normalized_lines = [line for line in lines if line]
    if not normalized_lines:
        return None
    return "\n".join(normalized_lines)


__all__ = ("_new_parser",)
