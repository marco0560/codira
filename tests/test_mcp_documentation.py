"""Tests for standalone MCP quickstart command routing.

Responsibilities
----------------
- Keep target-repository MCP instructions bound to the installed host runtime.
- Preserve an explicit, separate workflow for a Codira development checkout.

Architectural role
------------------
This module belongs to the documentation verification layer guarding the
host-target runtime boundary.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_GUIDE = REPO_ROOT / "docs" / "mcp.md"


def test_mcp_quickstart_distinguishes_host_and_checkout_commands() -> None:
    """Keep standalone MCP commands independent of the target UV project.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts host commands and the checkout-only ``uv run`` block.
    """
    guide = MCP_GUIDE.read_text(encoding="utf-8")

    assert 'codira index\ncodira-mcp-config codex --root "$PWD"' in guide
    assert "codira-mcp-config claude-desktop" in guide
    assert 'codira-mcp --root "$PWD"' in guide
    assert "### Codira development checkout" in guide
    assert "uv run codira-mcp-config codex --root /path/to/repository" in guide
