"""Verify optional measurement failure cannot mask population interruption.

Parameters
----------
None

Returns
-------
None
    These journal tests do not execute embedding models or campaigns.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codira.semantic.pending_profile import PendingEmbeddingProfile


def test_profile_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep diagnostics opt-in without writing default repository state.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Clears the explicit profile-directory control.

    Returns
    -------
    None
        A normal invocation has no diagnostic output path.
    """
    monkeypatch.delenv("CODIRA_EMBEDDING_PROFILE_DIR", raising=False)
    profile = PendingEmbeddingProfile("test")
    with profile.span("inference", rows=2):
        pass
    assert profile.path is None


def test_journal_failure_preserves_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Retain the real failure when optional profiling cannot write its journal.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned profile directory.
    monkeypatch : pytest.MonkeyPatch
        Simulates a failed diagnostic write.
    caplog : pytest.LogCaptureFixture
        Captures the explicit warning about unavailable profiling.

    Returns
    -------
    None
        The original interruption propagates and further profiling is disabled.
    """
    monkeypatch.setenv("CODIRA_EMBEDDING_PROFILE_DIR", str(tmp_path))
    profile = PendingEmbeddingProfile("test")

    def unavailable(*args: object, **kwargs: object) -> None:
        """Simulate an unavailable optional journal.

        Parameters
        ----------
        *args : object
            Unused open arguments.
        **kwargs : object
            Unused encoding options.

        Returns
        -------
        None
            Always fails.

        Raises
        ------
        OSError
            Simulates unavailable diagnostic storage.
        """
        message = "simulated diagnostic write failure"
        raise OSError(message)

    monkeypatch.setattr(Path, "open", unavailable)
    with pytest.raises(KeyboardInterrupt), profile.span("inference", rows=2):
        raise KeyboardInterrupt
    assert profile.path is None
    assert "profiling disabled" in caplog.text
