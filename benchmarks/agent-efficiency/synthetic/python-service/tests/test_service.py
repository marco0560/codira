"""Legitimate fixture tests; protected scoring assets are elsewhere."""

import unittest

from service import Adapter, Upper, render


class ServiceTests(unittest.TestCase):
    """Exercise existing public behavior."""

    def test_modes(self) -> None:
        """Verify both modes and an invalid request.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Public behavior assertions pass.
        """
        self.assertEqual(render("MiXeD"), "MIXED")
        self.assertEqual(render("MiXeD", "lower"), "mixed")
        with self.assertRaises(ValueError):
            render("text", "unknown")

    def test_adapter(self) -> None:
        """Verify public adapter delegation.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Public behavior assertions pass.
        """
        self.assertEqual(Adapter(Upper()).render("text"), "TEXT")
