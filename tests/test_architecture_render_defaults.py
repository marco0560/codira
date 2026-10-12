"""Keep CLI and library Graphviz defaults aligned."""

from codira.architecture_report import ArchitectureRenderOptions
from codira.cli_parser import build_parser


def test_svg_timeout_defaults_to_three_minutes() -> None:
    """Allow three minutes of optional SVG layout through both entry points.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Defaults agree and explicit bounded or unbounded overrides survive.
    """
    parser = build_parser()
    assert ArchitectureRenderOptions().svg_timeout_seconds == 180
    assert parser.parse_args(["arch"]).svg_timeout_seconds == 180
    assert (
        parser.parse_args(["arch", "--svg-timeout-seconds", "120"]).svg_timeout_seconds
        == 120
    )
    assert (
        parser.parse_args(["arch", "--svg-timeout-seconds", "0"]).svg_timeout_seconds
        == 0
    )
