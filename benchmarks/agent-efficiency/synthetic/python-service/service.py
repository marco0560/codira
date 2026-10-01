"""Public fixture with deliberately ambiguous plugin methods."""

from typing import Protocol


class Plugin(Protocol):
    """Render a supplied text through a public plugin interface."""

    def render(self, text: str) -> str:
        """Return rendered text.

        Parameters
        ----------
        text : str
            Supplied input text.

        Returns
        -------
        str
            Rendered text from the selected implementation.
        """
        ...


class Upper:
    """Convert supplied text to upper case."""

    def render(self, text: str) -> str:
        """Return text in upper case.

        Parameters
        ----------
        text : str
            Supplied input text.

        Returns
        -------
        str
            Rendered text from the selected implementation.
        """
        return text.upper()


class Lower:
    """Convert supplied text to lower case."""

    def render(self, text: str) -> str:
        """Return text in lower case.

        Parameters
        ----------
        text : str
            Supplied input text.

        Returns
        -------
        str
            Rendered text from the selected implementation.
        """
        return text.lower()


class Adapter:
    """Dispatch through the public render interface."""

    def __init__(self, plugin: Plugin) -> None:
        """Bind a plugin supplied by the operator."""
        self.plugin = plugin

    def render(self, text: str) -> str:
        """Delegate text to the selected plugin.

        Parameters
        ----------
        text : str
            Supplied input text.

        Returns
        -------
        str
            Rendered text from the selected implementation.
        """
        return self.plugin.render(text)


def render(text: str, mode: str = "upper") -> str:
    """Select a mode and render; unsupported modes raise ValueError.

    Parameters
    ----------
    text : str
        Supplied input text.
    mode : str, optional
        Either upper or lower; defaults to upper.

    Returns
    -------
    str
        Rendered text from the selected implementation.

    Raises
    ------
    ValueError
        If the mode is unsupported.
    """
    if mode not in {"upper", "lower"}:
        detail = "unsupported mode"
        raise ValueError(detail)
    return Adapter(Upper() if mode == "upper" else Lower()).render(text)
