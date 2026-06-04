"""Tests for hardware-aware embeddings calibration.

Responsibilities
----------------
- Verify deterministic calibration candidate selection and fallback behavior.
- Exercise calibration TOML output and CLI write modes without hardware
  dependencies.
- Ensure user config mutation occurs only through explicit calibration writes.

Design principles
-----------------
Tests use fake benchmark runners and temporary config paths so results are
deterministic on CPU-only, GPU-enabled, and dependency-limited hosts.

Architectural role
------------------
This module belongs to the **configuration tooling verification layer**.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import tomlkit

from codira import cli as cli_module, config as config_module
from codira.calibration import (
    BenchmarkMeasurement,
    CalibrationBenchmarkError,
    CalibrationCandidate,
    CalibrationOptions,
    CalibrationResult,
    HardwareInfo,
    calibrate_embeddings,
    calibration_candidates,
    embeddings_config_update,
    render_embeddings_calibration_toml,
)
from codira.cli import main
from codira.config import config_to_mapping, load_effective_config

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import pytest


class _ThroughputRunner:
    """
    Deterministic fake benchmark runner.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Test helper instances are callable and return synthetic measurements.
    """

    def __call__(
        self,
        candidate: CalibrationCandidate,
        texts: Sequence[str],
        *,
        warmup_iterations: int,
        measured_iterations: int,
    ) -> BenchmarkMeasurement:
        """
        Return throughput proportional to batch size and thread count.

        Parameters
        ----------
        candidate : CalibrationCandidate
            Candidate under test.
        texts : collections.abc.Sequence[str]
            Deterministic text payloads.
        warmup_iterations : int
            Unused warmup count.
        measured_iterations : int
            Unused measured iteration count.

        Returns
        -------
        BenchmarkMeasurement
            Synthetic successful measurement.
        """

        del texts, warmup_iterations, measured_iterations
        thread_factor = candidate.torch_num_threads or 1
        device_factor = 2 if candidate.device == "cuda" else 1
        throughput = float(candidate.batch_size * thread_factor * device_factor)
        return BenchmarkMeasurement(
            candidate=candidate,
            status="ok",
            throughput_texts_per_second=throughput,
            latency_seconds=1.0 / throughput,
            memory_peak_mb=4.0,
        )


class _FailingRunner:
    """
    Deterministic fake runner that rejects every candidate.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Test helper instances are callable and always raise.
    """

    def __call__(
        self,
        candidate: CalibrationCandidate,
        texts: Sequence[str],
        *,
        warmup_iterations: int,
        measured_iterations: int,
    ) -> BenchmarkMeasurement:
        """
        Reject one candidate as an out-of-memory failure.

        Parameters
        ----------
        candidate : CalibrationCandidate
            Candidate under test.
        texts : collections.abc.Sequence[str]
            Unused text payloads.
        warmup_iterations : int
            Unused warmup count.
        measured_iterations : int
            Unused measured iteration count.

        Returns
        -------
        BenchmarkMeasurement
            Never returned.

        Raises
        ------
        CalibrationBenchmarkError
            Always raised to simulate rejected candidates.
        """

        del candidate, texts, warmup_iterations, measured_iterations
        msg = "out of memory"
        raise CalibrationBenchmarkError(msg)


def _isolate_config_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    """
    Redirect user config writes into a temporary directory.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch path providers.
    tmp_path : pathlib.Path
        Temporary directory for test-owned config files.

    Returns
    -------
    pathlib.Path
        Temporary user config file path.
    """

    user_path = tmp_path / "user-config" / "config.toml"
    system_path = tmp_path / "system-config" / "config.toml"
    monkeypatch.setattr(config_module, "user_config_path", lambda: user_path)
    monkeypatch.setattr(cli_module, "user_config_path", lambda: user_path)
    monkeypatch.setattr(config_module, "system_config_path", lambda: system_path)
    return user_path


def test_cpu_calibration_candidates_are_deterministic() -> None:
    """
    Build CPU-only candidate search space in stable order.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts thread and batch candidates are ordered.
    """

    candidates = calibration_candidates(
        HardwareInfo(cpu_count=4, gpu_available=False),
    )

    assert candidates[0] == CalibrationCandidate(
        device="cpu",
        batch_size=8,
        torch_num_threads=1,
    )
    assert candidates[-1] == CalibrationCandidate(
        device="cpu",
        batch_size=128,
        torch_num_threads=0,
    )
    assert len(candidates) == 20


def test_calibration_selects_highest_throughput_gpu_candidate() -> None:
    """
    Select the candidate with highest deterministic throughput.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts GPU metadata is retained in the selected candidate.
    """

    result = calibrate_embeddings(
        options=CalibrationOptions(sample_count=4, max_duration_seconds=60.0),
        runner=_ThroughputRunner(),
        hardware=HardwareInfo(
            cpu_count=8,
            gpu_available=True,
            gpu_device_id=0,
            gpu_memory_mb=8192,
        ),
    )

    assert result.fallback_used is False
    assert result.selected.device == "cuda"
    assert result.selected.batch_size == 128
    assert result.selected.torch_num_threads == 8
    assert result.selected.gpu_memory_limit_mb == 6144


def test_calibration_uses_safe_fallback_when_all_candidates_fail() -> None:
    """
    Fall back to safe CPU defaults when no benchmark succeeds.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts failures are captured without raising.
    """

    result = calibrate_embeddings(
        options=CalibrationOptions(sample_count=2, max_duration_seconds=60.0),
        runner=_FailingRunner(),
        hardware=HardwareInfo(cpu_count=2, gpu_available=False),
    )

    assert result.fallback_used is True
    assert result.selected == CalibrationCandidate(
        device="cpu",
        batch_size=32,
        torch_num_threads=0,
    )
    assert {measurement.status for measurement in result.measurements} == {"failed"}


def test_calibration_toml_is_config_compatible() -> None:
    """
    Render a calibration result as valid config TOML.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the TOML parses into the expected config update.
    """

    result = CalibrationResult(
        selected=CalibrationCandidate(
            device="cuda",
            batch_size=64,
            torch_num_threads=8,
            gpu_device_id=0,
            gpu_memory_limit_mb=6144,
        ),
        measurements=(),
        fallback_used=False,
        hardware=HardwareInfo(cpu_count=8, gpu_available=True),
    )

    rendered = render_embeddings_calibration_toml(result)
    parsed = tomlkit.parse(rendered)

    assert "[embeddings.gpu]" in rendered
    assert parsed["embeddings"]["model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert parsed["embeddings"]["version"] == "1"
    assert parsed["embeddings"]["dimension"] == 384
    assert parsed["embeddings"]["device"] == "cuda"
    assert parsed["embeddings"]["gpu"]["memory_limit_mb"] == 6144
    assert embeddings_config_update(result) == {
        "embeddings": {
            "enabled": True,
            "model": "sentence-transformers/all-MiniLM-L6-v2",
            "version": "1",
            "dimension": 384,
            "device": "cuda",
            "batch_size": 64,
            "torch_num_threads": 8,
            "torch_num_interop_threads": 0,
            "gpu": {"device_id": 0, "memory_limit_mb": 6144},
        }
    }


def test_calibration_cli_prints_toml_without_user_config_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Print calibration output without creating a user config file.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv, calibration, and config paths.
    tmp_path : pathlib.Path
        Temporary config directory.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture command output.

    Returns
    -------
    None
        The test asserts default calibration mode writes stdout only.
    """

    user_path = _isolate_config_paths(monkeypatch, tmp_path)
    result = CalibrationResult(
        selected=CalibrationCandidate(
            device="cpu",
            batch_size=16,
            torch_num_threads=2,
        ),
        measurements=(),
        fallback_used=False,
        hardware=HardwareInfo(cpu_count=2, gpu_available=False),
    )
    monkeypatch.setattr(cli_module, "calibrate_embeddings", lambda: result)
    monkeypatch.setattr(sys, "argv", ["codira", "calibrate", "embeddings"])

    assert main() == 0

    captured = capsys.readouterr()
    assert "[embeddings]" in captured.out
    assert 'model = "sentence-transformers/all-MiniLM-L6-v2"' in captured.out
    assert "dimension = 384" in captured.out
    assert "batch_size = 16" in captured.out
    assert not user_path.exists()


def test_calibration_cli_writes_user_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Merge calibrated values into user config only with ``--write``.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv, calibration, and config paths.
    tmp_path : pathlib.Path
        Temporary config directory.

    Returns
    -------
    None
        The test asserts effective config reflects calibrated values.
    """

    user_path = _isolate_config_paths(monkeypatch, tmp_path)
    result = CalibrationResult(
        selected=CalibrationCandidate(
            device="cuda",
            batch_size=64,
            torch_num_threads=8,
            gpu_device_id=0,
            gpu_memory_limit_mb=4096,
        ),
        measurements=(),
        fallback_used=False,
        hardware=HardwareInfo(cpu_count=8, gpu_available=True),
    )
    monkeypatch.setattr(cli_module, "calibrate_embeddings", lambda: result)
    monkeypatch.setattr(sys, "argv", ["codira", "calibrate", "embeddings", "--write"])

    assert main() == 0

    mapping = config_to_mapping(load_effective_config(env={}))
    embeddings = mapping["embeddings"]
    assert user_path.exists()
    assert isinstance(embeddings, dict)
    assert embeddings["device"] == "cuda"
    assert embeddings["batch_size"] == 64
    assert embeddings["gpu"] == {"device_id": 0, "memory_limit_mb": 4096}


def test_calibration_cli_writes_output_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Write calibration TOML to an explicit output file.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch argv and calibration.
    tmp_path : pathlib.Path
        Temporary output directory.

    Returns
    -------
    None
        The test asserts the output file contains the TOML snippet.
    """

    _isolate_config_paths(monkeypatch, tmp_path)
    output_path = tmp_path / "out" / "embeddings.toml"
    result = CalibrationResult(
        selected=CalibrationCandidate(
            device="cpu",
            batch_size=8,
            torch_num_threads=1,
        ),
        measurements=(),
        fallback_used=False,
        hardware=HardwareInfo(cpu_count=1, gpu_available=False),
    )
    monkeypatch.setattr(cli_module, "calibrate_embeddings", lambda: result)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "calibrate", "embeddings", "--output", str(output_path)],
    )

    assert main() == 0

    assert output_path.read_text(encoding="utf-8").startswith("[embeddings]")
