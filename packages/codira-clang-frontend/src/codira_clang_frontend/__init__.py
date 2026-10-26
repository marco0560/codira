"""Optional shared Clang LibTooling frontend for C and C++ analyzer plugins.

Parameters
----------
None

Returns
-------
None
    Package namespace containing typed contracts and explicit providers.
"""

from importlib.metadata import PackageNotFoundError, version
import hashlib
from pathlib import Path

from .contracts import (
    CompilationContext,
    CompileProfile,
    DependencyClosure,
    DependencyInput,
    FrontendCall,
    FrontendCallable,
    FrontendCallableQualifiers,
    FrontendDeclaration,
    FrontendDiagnostic,
    FrontendDocumentationComment,
    FrontendInclude,
    FrontendPreprocessorEvent,
    FrontendResult,
    HeaderProjectionCandidate,
    HeaderProjectionRequest,
    HeaderProjectionResolution,
    IncludeDirectoryInput,
    SourcePoint,
    SourcePosition,
    SourceSpan,
    ToolchainIdentity,
)
from .frontend import (
    ClangFrontend,
    captured_profile_fingerprint,
    profile_toolchain_fingerprint,
)
from .profile import (
    PROFILE_SCHEMA,
    directory_membership_sha256,
    from_captured_argv,
    from_captured_profile_json,
    from_captured_profiles_json,
    from_compile_commands,
    resolve_header_projection,
    write_prepared_profile,
)

try:
    __version__ = version("codira-clang-frontend")
except PackageNotFoundError:
    __version__ = "0.3.0"


def create_frontend_profile(
    *,
    path: Path,
    root: Path,
    language: str,
    compile_commands: Path | None,
    captured_profiles: Path | None,
    helper_path: Path,
    build_receipt_path: Path,
) -> tuple[ClangFrontend, CompileProfile]:
    """Load one exact source profile and configure the optional frontend.

    Parameters
    ----------
    path : pathlib.Path
        Translation unit path.
    root : pathlib.Path
        Repository root containing the translation unit.
    language : str
        Analyzer language, ``c`` or ``cpp``.
    compile_commands : pathlib.Path or None
        Explicit compilation database path, if selected.
    captured_profiles : pathlib.Path or None
        Generic ``codira.clang-frontend-profile/2`` manifest path, if selected.
    helper_path : pathlib.Path
        Explicit native helper binary path.
    build_receipt_path : pathlib.Path
        Explicit helper build receipt path.

    Returns
    -------
    tuple[ClangFrontend, CompileProfile]
        Configured shared frontend and exact source profile.

    Raises
    ------
    ValueError
        If both or neither profile sources are selected, or the source/profile
        evidence cannot be validated.
    OSError
        If source, profile, or toolchain evidence files cannot be read.
    """
    if (compile_commands is None) == (captured_profiles is None):
        raise ValueError("select exactly one compile database or captured profile file")
    if compile_commands is not None:
        profile = from_compile_commands(
            compile_commands,
            path,
            root,
            language,
        )
    else:
        source = path.resolve()
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        profile = from_captured_profile_json(
            captured_profiles or Path(),
            source,
            root,
            digest,
        )
    frontend = ClangFrontend(
        helper_path,
        build_receipt_path,
        package_version=__version__,
    )
    return frontend, profile


def frontend_profile_fingerprint(
    frontend: ClangFrontend,
    profile: CompileProfile,
) -> str:
    """Return the stable input identity for indexer freshness checks.

    Parameters
    ----------
    frontend : ClangFrontend
        Configured optional Clang frontend.
    profile : CompileProfile
        Exact source, argv, dependency, environment, and include-root profile.

    Returns
    -------
    str
        SHA-256 fingerprint computed without running Clang.

    Raises
    ------
    OSError
        If profile or toolchain identity files cannot be read.
    ValueError
        If a source or dependency identity is stale.
    """
    return profile_toolchain_fingerprint(frontend, profile)


__all__ = [
    "PROFILE_SCHEMA",
    "ClangFrontend",
    "CompilationContext",
    "CompileProfile",
    "DependencyClosure",
    "DependencyInput",
    "FrontendCall",
    "FrontendCallable",
    "FrontendCallableQualifiers",
    "FrontendDeclaration",
    "FrontendDiagnostic",
    "FrontendDocumentationComment",
    "FrontendInclude",
    "FrontendPreprocessorEvent",
    "FrontendResult",
    "HeaderProjectionCandidate",
    "HeaderProjectionRequest",
    "HeaderProjectionResolution",
    "IncludeDirectoryInput",
    "SourcePoint",
    "SourcePosition",
    "SourceSpan",
    "ToolchainIdentity",
    "__version__",
    "directory_membership_sha256",
    "captured_profile_fingerprint",
    "from_captured_argv",
    "from_captured_profile_json",
    "from_captured_profiles_json",
    "from_compile_commands",
    "resolve_header_projection",
    "create_frontend_profile",
    "frontend_profile_fingerprint",
    "profile_toolchain_fingerprint",
    "write_prepared_profile",
]
