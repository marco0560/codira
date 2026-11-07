"""Versioned JSON types shared by the pilot adapter and graders."""

from __future__ import annotations

from typing import NoReturn

SCHEMA_VERSION = "codira.clang-frontend-pilot-tu/1"
PILOT_ID = "clang-frontend-pilot-20261024-r1"
DEFAULT_CAPTURE_MODE = "source_relevant"
CAPTURE_MODES = frozenset({"source_relevant", "full"})

type JSONValue = (
    None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
)


class ClangPilotInputError(ValueError):
    """Validation failure in a Clang pilot manifest or checkpoint.

    Parameters
    ----------
    message : str
        Concrete input or identity failure description.

    Returns
    -------
    None
        The exception stores the supplied validation message.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


def raise_input_error(message: str) -> NoReturn:
    """Raise the pilot's typed input and identity exception.

    Parameters
    ----------
    message : str
        Concise validation failure explanation.

    Returns
    -------
    NoReturn
        This function always raises.

    Raises
    ------
    ClangPilotInputError
        Always, with the supplied validation message.
    """
    raise ClangPilotInputError(message)


COORDINATE_FIELDS = ("path", "line", "column", "offset")
UNMODELED_FIELDS = (
    "macro_argument_token_provenance",
    "non_function_declaration_kinds",
    "compiler_driver_version_without_execution",
    "full_template_argument_semantics",
    "system_header_function_declarations",
    "external_project_header_declarations",
    "indirect_callee_resolution",
    "macro_argument_substitution_graph",
    "macro_replacement_tokens_after_96",
    "clang_runtime_shared_library_binary_hashes",
    "caller_enclosing_callable_ownership_links",
)
