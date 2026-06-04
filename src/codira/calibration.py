"""Hardware-aware embedding calibration for Codira.

Responsibilities
----------------
- Detect local CPU and GPU embedding calibration targets.
- Benchmark deterministic embedding workloads without network access.
- Produce configuration-compatible TOML snippets for calibrated parameters.

Design principles
-----------------
Calibration is optional, bounded, and isolated from normal indexing and query
paths. Missing optional semantic dependencies or local model artifacts produce
safe configuration fallback output instead of failing the command.

Architectural role
------------------
This module belongs to the **configuration tooling layer**. It consumes the
embedding backend contract and emits config-system-compatible values.
"""

from __future__ import annotations

import contextlib
import io
import os
import time
import tracemalloc
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

import tomlkit

from codira.config import (
    DEFAULT_EMBEDDING_BATCH_SIZE,
    DEFAULT_EMBEDDING_DEVICE,
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_GPU_DEVICE_ID,
    DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_VERSION,
    validate_config_mapping,
)
from codira.semantic.embeddings import (
    EmbeddingBackendError,
    get_embedding_backend,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    class _SentenceTransformerFactory(Protocol):
        """
        Constructor protocol for sentence-transformers models.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Protocol definitions are only evaluated by type checkers.
        """

        def __call__(
            self,
            model_name: str,
            *,
            device: str,
            local_files_only: bool,
        ) -> object: ...

    class _SentenceTransformerModel(Protocol):
        """
        Minimal model protocol used by calibration.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Protocol definitions are only evaluated by type checkers.
        """

        def encode(
            self,
            sentences: Sequence[str],
            *,
            batch_size: int,
            convert_to_numpy: bool,
            normalize_embeddings: bool,
            show_progress_bar: bool,
        ) -> object: ...


THREAD_CANDIDATES = (1, 2, 4, 8, 0)
BATCH_SIZE_CANDIDATES = (8, 16, 32, 64, 128)
DEFAULT_SAMPLE_COUNT = 32
DEFAULT_WARMUP_ITERATIONS = 1
DEFAULT_MEASURED_ITERATIONS = 2
DEFAULT_MAX_DURATION_SECONDS = 60.0
GPU_MEMORY_LIMIT_RATIO = 0.75


class CalibrationBenchmarkError(RuntimeError):
    """
    Stable failure raised for one rejected benchmark candidate.

    Parameters
    ----------
    message : str
        Human-readable benchmark rejection reason.
    """


@dataclass(frozen=True)
class HardwareInfo:
    """
    Detected embedding-relevant hardware facts.

    Parameters
    ----------
    cpu_count : int
        Detected CPU count, with ``1`` as the minimum fallback.
    gpu_available : bool
        Whether a CUDA GPU is available through Torch.
    gpu_device_id : int
        Selected GPU device identifier.
    gpu_memory_mb : int
        Total selected GPU memory in MiB, or ``0`` when unavailable.
    """

    cpu_count: int
    gpu_available: bool
    gpu_device_id: int = DEFAULT_EMBEDDING_GPU_DEVICE_ID
    gpu_memory_mb: int = DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB


@dataclass(frozen=True)
class CalibrationOptions:
    """
    Bounded calibration workload options.

    Parameters
    ----------
    sample_count : int
        Number of deterministic text payloads generated for each benchmark.
    warmup_iterations : int
        Number of unmeasured encode calls before timing.
    measured_iterations : int
        Number of measured encode calls.
    max_duration_seconds : float
        Maximum wall-clock duration for the candidate search loop.
    """

    sample_count: int = DEFAULT_SAMPLE_COUNT
    warmup_iterations: int = DEFAULT_WARMUP_ITERATIONS
    measured_iterations: int = DEFAULT_MEASURED_ITERATIONS
    max_duration_seconds: float = DEFAULT_MAX_DURATION_SECONDS


@dataclass(frozen=True)
class CalibrationCandidate:
    """
    One candidate embeddings runtime configuration.

    Parameters
    ----------
    device : str
        Sentence-transformers device string, usually ``"cpu"`` or ``"cuda"``.
    batch_size : int
        Candidate encode batch size.
    torch_num_threads : int
        Candidate Torch intra-op thread setting, or ``0`` for default.
    gpu_device_id : int
        Candidate GPU device identifier.
    gpu_memory_limit_mb : int
        Candidate GPU memory limit in MiB, or ``0`` when not configured.
    """

    device: str
    batch_size: int
    torch_num_threads: int
    gpu_device_id: int = DEFAULT_EMBEDDING_GPU_DEVICE_ID
    gpu_memory_limit_mb: int = DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB


@dataclass(frozen=True)
class BenchmarkMeasurement:
    """
    Measured outcome for one calibration candidate.

    Parameters
    ----------
    candidate : CalibrationCandidate
        Candidate that was benchmarked.
    status : str
        Stable status code: ``"ok"``, ``"failed"``, or ``"skipped"``.
    throughput_texts_per_second : float
        Measured throughput, or ``0.0`` for failed candidates.
    latency_seconds : float
        Mean measured encode-call latency, or ``0.0`` for failed candidates.
    memory_peak_mb : float
        Measured Python/GPU peak memory signal in MiB when available.
    detail : str
        Human-readable diagnostic detail.
    """

    candidate: CalibrationCandidate
    status: str
    throughput_texts_per_second: float
    latency_seconds: float
    memory_peak_mb: float
    detail: str = ""


@dataclass(frozen=True)
class CalibrationResult:
    """
    Final calibration selection and benchmark ledger.

    Parameters
    ----------
    selected : CalibrationCandidate
        Candidate selected for config output.
    measurements : tuple[BenchmarkMeasurement, ...]
        Candidate benchmark outcomes in execution order.
    fallback_used : bool
        Whether the selected candidate is the safe fallback.
    hardware : HardwareInfo
        Hardware facts used to build the candidate set.
    """

    selected: CalibrationCandidate
    measurements: tuple[BenchmarkMeasurement, ...]
    fallback_used: bool
    hardware: HardwareInfo


class EmbeddingBenchmarkRunner(Protocol):
    """
    Benchmark runner protocol used by calibration and tests.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Protocol definitions are only evaluated by type checkers.
    """

    def __call__(
        self,
        candidate: CalibrationCandidate,
        texts: Sequence[str],
        *,
        warmup_iterations: int,
        measured_iterations: int,
    ) -> BenchmarkMeasurement: ...


def detect_hardware() -> HardwareInfo:
    """
    Detect embedding-relevant local hardware.

    Parameters
    ----------
    None

    Returns
    -------
    HardwareInfo
        CPU count and best-effort CUDA device metadata.
    """

    cpu_count = max(1, os.cpu_count() or 1)
    try:
        torch = import_module("torch")
        cuda = getattr(torch, "cuda", None)
        if cuda is None or not bool(cuda.is_available()):
            return HardwareInfo(cpu_count=cpu_count, gpu_available=False)
        device_id = int(cuda.current_device())
        properties = cuda.get_device_properties(device_id)
        total_memory = int(getattr(properties, "total_memory", 0))
        return HardwareInfo(
            cpu_count=cpu_count,
            gpu_available=True,
            gpu_device_id=device_id,
            gpu_memory_mb=total_memory // (1024 * 1024),
        )
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return HardwareInfo(cpu_count=cpu_count, gpu_available=False)


def deterministic_embedding_samples(count: int) -> tuple[str, ...]:
    """
    Generate deterministic text payloads for calibration.

    Parameters
    ----------
    count : int
        Number of payloads to generate.

    Returns
    -------
    tuple[str, ...]
        Stable sample texts.
    """

    return tuple(
        (
            f"codira calibration sample {index:03d}: "
            "configuration schema, embedding retrieval, plugin runtime, "
            "static analysis, and deterministic repository context."
        )
        for index in range(count)
    )


def calibration_candidates(hardware: HardwareInfo) -> tuple[CalibrationCandidate, ...]:
    """
    Build the deterministic calibration search space.

    Parameters
    ----------
    hardware : HardwareInfo
        Detected hardware metadata.

    Returns
    -------
    tuple[CalibrationCandidate, ...]
        Candidate configurations in deterministic execution order.
    """

    threads = tuple(
        dict.fromkeys(
            thread
            for thread in THREAD_CANDIDATES
            if thread == 0 or thread <= hardware.cpu_count
        )
    )
    if 0 not in threads:
        threads = (*threads, 0)

    devices = ("cpu", "cuda") if hardware.gpu_available else ("cpu",)
    gpu_memory_limit_mb = (
        int(hardware.gpu_memory_mb * GPU_MEMORY_LIMIT_RATIO)
        if hardware.gpu_memory_mb > 0
        else DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB
    )
    candidates: list[CalibrationCandidate] = []
    for device in devices:
        for thread_count in threads:
            for batch_size in BATCH_SIZE_CANDIDATES:
                candidates.append(
                    CalibrationCandidate(
                        device=device,
                        batch_size=batch_size,
                        torch_num_threads=thread_count,
                        gpu_device_id=(
                            hardware.gpu_device_id
                            if device == "cuda"
                            else DEFAULT_EMBEDDING_GPU_DEVICE_ID
                        ),
                        gpu_memory_limit_mb=(
                            gpu_memory_limit_mb
                            if device == "cuda"
                            else DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB
                        ),
                    )
                )
    return tuple(candidates)


def safe_fallback_candidate() -> CalibrationCandidate:
    """
    Return the safe CPU fallback candidate.

    Parameters
    ----------
    None

    Returns
    -------
    CalibrationCandidate
        Conservative config-compatible embedding parameters.
    """

    return CalibrationCandidate(
        device=DEFAULT_EMBEDDING_DEVICE,
        batch_size=DEFAULT_EMBEDDING_BATCH_SIZE,
        torch_num_threads=0,
    )


def _is_oom_error(exc: BaseException) -> bool:
    """
    Return whether an exception looks like an out-of-memory failure.

    Parameters
    ----------
    exc : BaseException
        Exception raised by the benchmark runner.

    Returns
    -------
    bool
        ``True`` when the message contains stable OOM indicators.
    """

    message = str(exc).lower()
    return "out of memory" in message or "oom" in message


def _configure_torch_threads(thread_count: int) -> None:
    """
    Apply candidate Torch thread settings when Torch is available.

    Parameters
    ----------
    thread_count : int
        Torch intra-op thread count, or ``0`` to leave defaults unchanged.

    Returns
    -------
    None
        Torch is updated only when a positive override is requested.

    Raises
    ------
    CalibrationBenchmarkError
        If Torch is installed but rejects the requested thread setting.
    """

    if thread_count < 1:
        return
    try:
        torch = import_module("torch")
        set_num_threads = getattr(torch, "set_num_threads", None)
        if set_num_threads is not None:
            set_num_threads(thread_count)
    except (ImportError, RuntimeError, TypeError, ValueError) as exc:
        msg = f"failed to set torch threads: {exc}"
        raise CalibrationBenchmarkError(msg) from exc


class SentenceTransformerBenchmarkRunner:
    """
    Offline sentence-transformers benchmark runner.

    Parameters
    ----------
    None

    Notes
    -----
    Model loading uses local files only. Missing dependencies or model artifacts
    reject candidates so calibration can fall back without network access.
    """

    def __init__(self) -> None:
        self._models: dict[str, object] = {}

    def __call__(
        self,
        candidate: CalibrationCandidate,
        texts: Sequence[str],
        *,
        warmup_iterations: int,
        measured_iterations: int,
    ) -> BenchmarkMeasurement:
        """
        Benchmark one candidate with the configured embedding model.

        Parameters
        ----------
        candidate : CalibrationCandidate
            Candidate runtime settings.
        texts : collections.abc.Sequence[str]
            Deterministic text payloads.
        warmup_iterations : int
            Number of unmeasured encode calls.
        measured_iterations : int
            Number of measured encode calls.

        Returns
        -------
        BenchmarkMeasurement
            Successful benchmark measurement.

        Raises
        ------
        CalibrationBenchmarkError
            If dependencies, local artifacts, or runtime execution fail.
        """

        try:
            model = self._model_for_device(candidate.device)
            _configure_torch_threads(candidate.torch_num_threads)
            for _index in range(warmup_iterations):
                self._encode(model, texts, candidate.batch_size)
            tracemalloc.start()
            started = time.perf_counter()
            for _index in range(measured_iterations):
                self._encode(model, texts, candidate.batch_size)
            elapsed = max(time.perf_counter() - started, 1e-9)
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        except (OSError, RuntimeError, EmbeddingBackendError) as exc:
            if tracemalloc.is_tracing():
                tracemalloc.stop()
            detail = "out of memory" if _is_oom_error(exc) else str(exc)
            raise CalibrationBenchmarkError(detail) from exc

        total_texts = len(texts) * measured_iterations
        return BenchmarkMeasurement(
            candidate=candidate,
            status="ok",
            throughput_texts_per_second=total_texts / elapsed,
            latency_seconds=elapsed / max(measured_iterations, 1),
            memory_peak_mb=peak / (1024 * 1024),
        )

    def _model_for_device(self, device: str) -> object:
        """
        Return a cached local sentence-transformers model for one device.

        Parameters
        ----------
        device : str
            Sentence-transformers device string.

        Returns
        -------
        object
            Loaded model instance.

        Raises
        ------
        CalibrationBenchmarkError
            If optional dependencies or local model artifacts are unavailable.
        """

        cached = self._models.get(device)
        if cached is not None:
            return cached
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        try:
            module = import_module("sentence_transformers")
            factory_obj = module.__dict__.get("SentenceTransformer")
            if factory_obj is None:
                msg = "sentence_transformers.SentenceTransformer is unavailable"
                raise CalibrationBenchmarkError(msg)
            factory = cast("_SentenceTransformerFactory", factory_obj)
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                model = factory(
                    get_embedding_backend().name,
                    device=device,
                    local_files_only=True,
                )
        except (ImportError, AttributeError, OSError, RuntimeError) as exc:
            msg = f"local embedding backend unavailable: {exc}"
            raise CalibrationBenchmarkError(msg) from exc
        self._models[device] = model
        return model

    @staticmethod
    def _encode(model: object, texts: Sequence[str], batch_size: int) -> None:
        """
        Run one encode call on a sentence-transformers-compatible model.

        Parameters
        ----------
        model : object
            Model exposing an ``encode`` method.
        texts : collections.abc.Sequence[str]
            Text payloads to encode.
        batch_size : int
            Encode batch size.

        Returns
        -------
        None
            Encoded vectors are intentionally discarded.
        """

        model_obj = cast("_SentenceTransformerModel", model)
        model_obj.encode(
            list(texts),
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )


def calibrate_embeddings(
    *,
    options: CalibrationOptions | None = None,
    runner: EmbeddingBenchmarkRunner | None = None,
    hardware: HardwareInfo | None = None,
) -> CalibrationResult:
    """
    Calibrate embeddings parameters for the current machine.

    Parameters
    ----------
    options : CalibrationOptions | None, optional
        Bounded workload options. Defaults are used when omitted.
    runner : EmbeddingBenchmarkRunner | None, optional
        Benchmark runner. Tests can provide a deterministic fake runner.
    hardware : HardwareInfo | None, optional
        Hardware facts. Auto-detected when omitted.

    Returns
    -------
    CalibrationResult
        Selected candidate and measured candidate ledger.
    """

    calibration_options = options or CalibrationOptions()
    hardware_info = hardware or detect_hardware()
    benchmark_runner = runner or SentenceTransformerBenchmarkRunner()
    texts = deterministic_embedding_samples(calibration_options.sample_count)
    measurements: list[BenchmarkMeasurement] = []
    started = time.monotonic()

    for candidate in calibration_candidates(hardware_info):
        if time.monotonic() - started >= calibration_options.max_duration_seconds:
            measurements.append(
                BenchmarkMeasurement(
                    candidate=candidate,
                    status="skipped",
                    throughput_texts_per_second=0.0,
                    latency_seconds=0.0,
                    memory_peak_mb=0.0,
                    detail="duration limit reached",
                )
            )
            break
        try:
            measurement = benchmark_runner(
                candidate,
                texts,
                warmup_iterations=calibration_options.warmup_iterations,
                measured_iterations=calibration_options.measured_iterations,
            )
        except CalibrationBenchmarkError as exc:
            measurements.append(
                BenchmarkMeasurement(
                    candidate=candidate,
                    status="failed",
                    throughput_texts_per_second=0.0,
                    latency_seconds=0.0,
                    memory_peak_mb=0.0,
                    detail=str(exc),
                )
            )
            continue
        measurements.append(measurement)

    successful = [item for item in measurements if item.status == "ok"]
    if not successful:
        return CalibrationResult(
            selected=safe_fallback_candidate(),
            measurements=tuple(measurements),
            fallback_used=True,
            hardware=hardware_info,
        )

    selected = max(
        successful,
        key=lambda item: (
            item.throughput_texts_per_second,
            -item.latency_seconds,
            -item.candidate.batch_size,
            -item.candidate.torch_num_threads,
            1 if item.candidate.device == "cuda" else 0,
        ),
    ).candidate
    return CalibrationResult(
        selected=selected,
        measurements=tuple(measurements),
        fallback_used=False,
        hardware=hardware_info,
    )


def embeddings_config_update(result: CalibrationResult) -> dict[str, object]:
    """
    Convert a calibration result into a config update mapping.

    Parameters
    ----------
    result : CalibrationResult
        Calibration result to serialize.

    Returns
    -------
    dict[str, object]
        Partial config mapping under the ``embeddings`` section.
    """

    selected = result.selected
    update = {
        "enabled": True,
        "model": DEFAULT_EMBEDDING_MODEL,
        "version": DEFAULT_EMBEDDING_VERSION,
        "dimension": DEFAULT_EMBEDDING_DIMENSION,
        "device": selected.device,
        "batch_size": selected.batch_size,
        "torch_num_threads": selected.torch_num_threads,
        "torch_num_interop_threads": 0,
        "gpu": {
            "device_id": selected.gpu_device_id,
            "memory_limit_mb": selected.gpu_memory_limit_mb,
        },
    }
    validate_config_mapping({"embeddings": update})
    return {"embeddings": update}


def render_embeddings_calibration_toml(result: CalibrationResult) -> str:
    """
    Render calibration output as a config-compatible TOML snippet.

    Parameters
    ----------
    result : CalibrationResult
        Calibration result to render.

    Returns
    -------
    str
        TOML snippet ending in a newline.
    """

    embeddings = cast(
        "dict[str, object]",
        embeddings_config_update(result)["embeddings"],
    )
    gpu = cast("dict[str, object]", embeddings["gpu"])
    document = tomlkit.document()
    table = tomlkit.table()
    for key in (
        "enabled",
        "model",
        "version",
        "dimension",
        "device",
        "batch_size",
        "torch_num_threads",
        "torch_num_interop_threads",
    ):
        table.add(key, embeddings[key])
    gpu_table = tomlkit.table()
    for key in ("device_id", "memory_limit_mb"):
        gpu_table.add(key, gpu[key])
    table.add("gpu", gpu_table)
    document.add("embeddings", table)
    text = tomlkit.dumps(document)
    if not text.endswith("\n"):
        text += "\n"
    return text
