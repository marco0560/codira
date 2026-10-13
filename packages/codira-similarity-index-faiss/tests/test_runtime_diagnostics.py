"""Verify actual SIMD facts without changing native dispatch.

Parameters
----------
None

Returns
-------
None
    Native smoke and simulated legacy API coverage.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import faiss
import pytest
import codira_similarity_index_faiss as plugin


def test_runtime_diagnostics_preserve_native_level() -> None:
    """Read actual configuration without forcing any CPU feature.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Diagnostics leave the active SIMD level unchanged.
    """
    simd = getattr(faiss, "SIMDConfig")
    before = simd.get_level_name()
    result = plugin.runtime_diagnostics()
    assert result["active_simd"] == before
    assert result["dynamic_dispatch"] == simd.has_dynamic_dispatch()
    assert result["version"] == faiss.__version__
    assert simd.get_level_name() == before


@pytest.mark.parametrize("legacy", [False, True])
def test_binding_name_does_not_imply_unoptimized_code(
    monkeypatch: pytest.MonkeyPatch, legacy: bool
) -> None:
    """Report dynamic AVX2 in a generic binding or unknown legacy capability.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Substitutes an explicit native diagnostic boundary.
    legacy : bool
        Missing optional SIMD diagnostic API.

    Returns
    -------
    None
        Missing module suffixes never determine acceleration status.
    """
    native = SimpleNamespace(
        __version__="test",
        IndexFlatIP=SimpleNamespace(__module__="faiss.swigfaiss"),
        get_compile_options=lambda: "OPTIMIZE DD AVX2",
    )
    setter = Mock()
    if not legacy:
        native.SIMDConfig = SimpleNamespace(
            has_dynamic_dispatch=lambda: True,
            get_level_name=lambda: "AVX2",
            set_level=setter,
        )
    monkeypatch.setattr(plugin, "faiss", native)
    result = plugin.runtime_diagnostics()
    assert result["binding_module"] == "faiss.swigfaiss"
    assert result["active_simd"] == (None if legacy else "AVX2")
    assert result["dynamic_dispatch"] == (None if legacy else True)
    setter.assert_not_called()
