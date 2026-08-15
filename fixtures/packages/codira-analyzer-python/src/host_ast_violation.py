"""Intentional host-parser violation for the Semgrep regression fixture."""

import ast


def parse_with_host_ast(source: str) -> ast.AST:
    """Return a host-parser tree solely to trigger the guardrail fixture.

    Parameters
    ----------
    source : str
        Python source supplied by the fixture scan.

    Returns
    -------
    ast.AST
        Host parser result that production analyzer code must not use.
    """
    return ast.parse(source)
