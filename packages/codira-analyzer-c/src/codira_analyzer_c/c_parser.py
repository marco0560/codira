"""Construct independent C grammar parsers for analysis and input discovery.

Parameters
----------
None

Returns
-------
None
    Defines the package-local parser factory.
"""

from tree_sitter import Language, Parser
from tree_sitter_c import language

_LANGUAGE = Language(language())


def _new_parser() -> Parser:
    """Create an independent C grammar parser.

    Parameters
    ----------
    None

    Returns
    -------
    tree_sitter.Parser
        Parser owned by one analysis or input-capture operation.
    """
    return Parser(_LANGUAGE)
