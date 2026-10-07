"""Protected behavioral checks for panel-f2."""

from service import Adapter, Lower, Upper

capability_method = "capabilities"

for plugin in (Upper(), Lower()):
    assert getattr(plugin, capability_method)()["case_conversion"] is True
    assert getattr(Adapter(plugin), capability_method)()["case_conversion"] is True


class Legacy:
    """Provide render without the optional capability interface."""

    def render(self, text: str) -> str:
        """Return text unchanged.

        Parameters
        ----------
        text : str
            Supplied input.

        Returns
        -------
        str
            Unchanged input.
        """
        return text


assert getattr(Adapter(Legacy()), capability_method)()["case_conversion"] is False
assert Adapter(Legacy()).render("Mixed") == "Mixed"


class Extension:
    """Provide an independently implemented capability interface."""

    def capabilities(self) -> dict[str, bool]:
        """Declare the protected extension capability.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, bool]
            Positive case-conversion declaration for delegation checks.
        """
        return {"case_conversion": True}

    def render(self, text: str) -> str:
        """Return text unchanged.

        Parameters
        ----------
        text : str
            Supplied input.

        Returns
        -------
        str
            Unchanged input.
        """
        return text


assert getattr(Adapter(Extension()), capability_method)()["case_conversion"] is True
