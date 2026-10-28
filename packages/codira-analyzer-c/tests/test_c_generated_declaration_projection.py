"""Focused source-invocation evidence tests for C declaration projection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from codira.generated import (
    CompilerObservedDeclarationProvenance,
    generated_provenance_payload,
    generated_provenance_rows,
)
from codira_clang_frontend.contracts import (
    DependencyClosure,
    DependencyInput,
    FrontendDeclaration,
    FrontendPreprocessorEvent,
    FrontendResult,
    SourcePoint,
    SourcePosition,
    SourceSpan,
)
from codira_clang_frontend.frontend import _decode_entities

from codira_analyzer_c import (
    _analysis_from_clang_result,
    _clang_macro_invocation_for_declaration,
)


@pytest.mark.parametrize(("end_delta", "expected_evidence"), ((0, True), (12, False)))
def test_c_object_like_macro_declaration_uses_native_end_token_start(
    tmp_path: Path,
    end_delta: int,
    expected_evidence: bool,
) -> None:
    """Accept object-like invocation token starts and reject out-of-span ends.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root containing the source-bound object-like macro.
    end_delta : int
        Native end coordinate relative to the invocation start.
    expected_evidence : bool
        Whether the native end token start lies inside the exact invocation span.

    Returns
    -------
    None
        The declaration evidence accepts a token-start range and rejects an
        end coordinate outside the source invocation.
    """
    source = tmp_path / "object_macro.c"
    source.write_text(
        "#define OBJECT_VALUE int object_value = 5\nOBJECT_VALUE\n",
        encoding="utf-8",
    )
    source_bytes = source.read_bytes()
    invocation = "OBJECT_VALUE"
    start = source_bytes.rindex(invocation.encode("utf-8"))

    def point(offset: int) -> SourcePoint:
        """Build a physical compiler coordinate at one byte offset.

        Parameters
        ----------
        offset : int
            Byte offset in the temporary translation unit.

        Returns
        -------
        codira_clang_frontend.SourcePoint
            Coordinate with identical spelling and expansion positions.
        """
        prefix = source_bytes[:offset]
        position = SourcePosition(
            path=str(source),
            line=prefix.count(b"\n") + 1,
            column=offset - prefix.rfind(b"\n"),
            offset=offset,
        )
        return SourcePoint(spelling=position, expansion=position, is_macro=False)

    declaration = FrontendDeclaration(
        usr="c:@object_value",
        kind="variable",
        name="object_value",
        qualified_name="object_value",
        decl_kind="Var",
        signature=None,
        type_text="int",
        parameters=(),
        has_prototype=None,
        is_definition=True,
        provenance="macro_replacement",
        location=SourcePoint(
            spelling=point(source_bytes.index(b"int object_value")).spelling,
            expansion=point(start).expansion,
            is_macro=True,
        ),
        span=None,
        is_file_scope=True,
    )
    event = FrontendPreprocessorEvent(
        kind="macro_expansion",
        name=invocation,
        replacement=(),
        replacement_truncated=False,
        function_like=False,
        parameters=(),
        source_text=None,
        condition=None,
        result=None,
        macro_defined=None,
        invocation=invocation,
        location=point(start),
        span=SourceSpan(begin=point(start), end=point(start + end_delta)),
    )
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    result = FrontendResult(
        status="parsed",
        coverage_state="complete",
        reasons=(),
        diagnostics=(),
        declarations=(declaration,),
        callables=(),
        dependency_closure=DependencyClosure(
            status="complete",
            files=(DependencyInput(path=source, sha256=source_sha256),),
            sha256="c" * 64,
        ),
        profile_identity="clang-c-object-macro-r1",
        toolchain_identity=None,
        cache_fingerprint="clang-c-object-cache-r1",
        stdout_path=None,
        stdout_sha256="d" * 64,
        stderr_path=None,
        stderr_sha256="e" * 64,
        preprocessing=(event,),
    )

    evidence = _clang_macro_invocation_for_declaration(
        declaration,
        result,
        path=source,
        root=tmp_path,
        source_bytes=source_bytes,
        source_sha256=source_sha256,
        context_identity='{"schema":"files-input-fingerprint-v1","id":"c-object-r1"}',
    )

    assert (evidence is not None) is expected_evidence
    if evidence is not None:
        assert evidence[0].invocation.text == invocation
        assert (
            source_bytes[slice(*evidence[0].invocation.byte_range)]
            == invocation.encode()
        )


@pytest.mark.parametrize(
    ("selected_name", "is_file_scope", "owner_kind", "expected_projection"),
    (
        ("global_count", True, None, True),
        ("local_count", False, "Function", False),
    ),
)
def test_c_macro_variable_projection_is_scope_bounded_and_evidenced(
    tmp_path: Path,
    selected_name: str,
    is_file_scope: bool,
    owner_kind: str | None,
    expected_projection: bool,
) -> None:
    """Attach native evidence to eligible variables and ignore macro locals.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing the C translation unit.
    selected_name : str
        Name of the declaration row represented by the native response.
    is_file_scope : bool
        Compiler-reported translation-unit scope of the declaration.
    owner_kind : str or None
        Compiler-reported owner kind for a local declaration.
    expected_projection : bool
        Whether the existing C scope contract projects this row.

    Returns
    -------
    None
        The eligible declaration retains a bounded receipt; the local remains
        absent without creating a generated-declaration coverage hold.
    """
    source = tmp_path / "macro_variable.c"
    source.write_text(
        "#define C_DECL(name) int name = 7\n"
        "C_DECL(global_count)\n"
        "void local(void) { C_DECL(local_count); }\n",
        encoding="utf-8",
    )
    source_bytes = source.read_bytes()
    invocation = f"C_DECL({selected_name})"
    invocation_bytes = invocation.encode("utf-8")
    start = source_bytes.index(invocation_bytes)
    end = start + len(invocation_bytes) - 1
    argument = source_bytes.index(selected_name.encode("utf-8"), start)

    def point(offset: int, *, is_macro: bool) -> SourcePoint:
        """Create a compiler source point at a known fixture byte offset.

        Parameters
        ----------
        offset : int
            Zero-based offset into the fixture source.
        is_macro : bool
            Whether Clang marked the point as macro-derived.

        Returns
        -------
        codira_clang_frontend.SourcePoint
            Spelling and expansion coordinates at the requested offset.
        """
        prefix = source_bytes[:offset]
        position = SourcePosition(
            path=str(source),
            line=prefix.count(b"\n") + 1,
            column=offset - prefix.rfind(b"\n"),
            offset=offset,
        )
        return SourcePoint(spelling=position, expansion=position, is_macro=is_macro)

    invocation_point = point(start, is_macro=False)
    declaration_location = SourcePoint(
        spelling=point(argument, is_macro=False).spelling,
        expansion=point(start, is_macro=False).expansion,
        is_macro=True,
    )
    event = FrontendPreprocessorEvent(
        kind="macro_expansion",
        name="C_DECL",
        replacement=(),
        replacement_truncated=False,
        function_like=True,
        parameters=("name",),
        source_text=None,
        condition=None,
        result=None,
        macro_defined=None,
        invocation=invocation,
        location=invocation_point,
        span=SourceSpan(
            begin=point(start, is_macro=False), end=point(end, is_macro=False)
        ),
    )
    native_declaration = {
        "identity": {
            "usr": f"c:@{selected_name}",
            "kind": "macro_argument",
            "provenance": "macro_argument",
        },
        "entity_kind": "variable",
        "name": selected_name,
        "qualified_name": selected_name,
        "decl_kind": "Var",
        "type": "int",
        "is_definition": True,
        "is_file_scope": is_file_scope,
        "location": asdict(declaration_location),
        "owner_kind": owner_kind,
        "owner_name": "local" if owner_kind else None,
        "owner_usr": "c:@F@local" if owner_kind else None,
    }
    declarations, _, _ = _decode_entities(
        {"non_function_declarations": [native_declaration]}
    )
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    result = FrontendResult(
        status="parsed",
        coverage_state="complete",
        reasons=(),
        diagnostics=(),
        declarations=declarations,
        callables=(),
        dependency_closure=DependencyClosure(
            status="complete",
            files=(DependencyInput(path=source, sha256=source_sha256),),
            sha256="f" * 64,
        ),
        profile_identity="clang-declaration-profile-r1",
        toolchain_identity=None,
        cache_fingerprint="clang-declaration-cache-r1",
        stdout_path=None,
        stdout_sha256="a" * 64,
        stderr_path=None,
        stderr_sha256="b" * 64,
        preprocessing=(event,),
    )
    context_identity = '{"schema":"files-input-fingerprint-v1","id":"c-r1"}'

    analysis = _analysis_from_clang_result(
        source, tmp_path, result, context_identity=context_identity
    )

    assert analysis is not None
    assert analysis.status is not None
    assert analysis.status.coverage_state == "complete"
    assert "generated_declaration" not in analysis.status.omitted_categories
    if not expected_projection:
        assert all(item.name != selected_name for item in analysis.declarations)
        assert not generated_provenance_rows(analysis)
        return

    declaration = next(
        item for item in analysis.declarations if item.name == selected_name
    )
    assert declaration.lineno == 2
    assert declaration.type_text == "int"
    assert isinstance(declaration.generated, CompilerObservedDeclarationProvenance)
    assert declaration.generated.declaration_kind == "variable"
    assert declaration.generated.source_sha256 == source_sha256
    assert declaration.generated.context_identity == context_identity
    assert declaration.generated.invocation.text == invocation
    assert declaration.generated.receipt_namespace == (
        "clang.frontend.declaration-observation.v1"
    )
    receipt = json.loads(declaration.generated.receipt_json)
    assert receipt["declaration"]["usr"] == f"c:@{selected_name}"
    assert receipt["declaration"]["type_text"] == "int"
    assert receipt["context"]["stdout_sha256"] == "a" * 64
    rows = generated_provenance_rows(analysis)
    assert len(rows) == 1
    assert generated_provenance_payload(rows[0][1])["variant"] == (
        "compiler_observed_declaration"
    )


def test_c_owned_macro_field_uses_variable_artifact_and_keeps_bad_owner_held(
    tmp_path: Path,
) -> None:
    """Project compiler-observed C fields only with their existing record owner.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing a record and macro field.

    Returns
    -------
    None
        An owned field retains type, owner, and evidence; an unknown-origin field
        stays held and a field without owner identity is not projected.
    """
    source = tmp_path / "macro_field.c"
    source.write_text(
        "#define C_FIELD(name) int name;\n"
        "struct Owner {\n"
        "  C_FIELD(value)\n"
        "  C_FIELD(orphan)\n"
        "  C_FIELD(unknown)\n"
        "};\n",
        encoding="utf-8",
    )
    source_bytes = source.read_bytes()

    def point(offset: int, *, is_macro: bool = False) -> SourcePoint:
        """Create a compiler coordinate at one source byte offset.

        Parameters
        ----------
        offset : int
            Zero-based offset in the fixture source.
        is_macro : bool, optional
            Whether the native frontend marked the point as macro-derived.

        Returns
        -------
        codira_clang_frontend.SourcePoint
            Point with matching spelling and expansion positions.
        """
        prefix = source_bytes[:offset]
        position = SourcePosition(
            path=str(source),
            line=prefix.count(b"\n") + 1,
            column=offset - prefix.rfind(b"\n"),
            offset=offset,
        )
        return SourcePoint(spelling=position, expansion=position, is_macro=is_macro)

    def macro_location(name: str) -> SourcePoint:
        """Build native spelling and expansion coordinates for a field name.

        Parameters
        ----------
        name : str
            Field argument passed to the source macro invocation.

        Returns
        -------
        codira_clang_frontend.SourcePoint
            Location with argument spelling and invocation expansion.
        """
        invocation = f"C_FIELD({name})".encode("utf-8")
        start = source_bytes.index(invocation)
        argument = source_bytes.index(name.encode("utf-8"), start)
        return SourcePoint(
            spelling=point(argument).spelling,
            expansion=point(start).expansion,
            is_macro=True,
        )

    def event(name: str, origin: str) -> FrontendPreprocessorEvent:
        """Build a byte-exact source macro event for one field.

        Parameters
        ----------
        name : str
            Field name passed to the macro invocation.
        origin : str
            Macro name emitted by the preprocessor.

        Returns
        -------
        codira_clang_frontend.FrontendPreprocessorEvent
            Native callback fact bound to the exact source invocation.
        """
        invocation = f"C_FIELD({name})"
        invocation_bytes = invocation.encode("utf-8")
        start = source_bytes.index(invocation_bytes)
        end = start + len(invocation_bytes) - 1
        return FrontendPreprocessorEvent(
            kind="macro_expansion",
            name=origin,
            replacement=(),
            replacement_truncated=False,
            function_like=True,
            parameters=("name",),
            source_text=None,
            condition=None,
            result=None,
            macro_defined=None,
            invocation=invocation,
            location=point(start),
            span=SourceSpan(begin=point(start), end=point(end)),
        )

    owner_usr = "c:@S@Owner"
    rows = [
        {
            "identity": {"usr": owner_usr, "provenance": "source_written"},
            "entity_kind": "struct",
            "name": "Owner",
            "qualified_name": "Owner",
            "decl_kind": "Record",
            "is_definition": True,
            "is_file_scope": True,
            "location": asdict(point(source_bytes.index(b"Owner"))),
        },
    ]
    for name, provenance, include_owner in (
        ("value", "macro_argument", True),
        ("orphan", "macro_argument", False),
        ("unknown", "unknown", True),
    ):
        row = {
            "identity": {
                "usr": f"c:@S@Owner@FI@{name}",
                "kind": provenance,
                "provenance": provenance,
            },
            "entity_kind": "variable",
            "name": name,
            "qualified_name": f"Owner::{name}",
            "decl_kind": "Field",
            "type": "int",
            "is_definition": True,
            "is_file_scope": False,
            "location": asdict(macro_location(name)),
        }
        if include_owner:
            row.update(
                {
                    "owner_usr": owner_usr,
                    "owner_name": "Owner",
                    "owner_kind": "Record",
                    "owner_location": asdict(point(source_bytes.index(b"Owner"))),
                    "access": None,
                }
            )
        rows.append(row)
    declarations, _, _ = _decode_entities({"non_function_declarations": rows})
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    result = FrontendResult(
        status="parsed",
        coverage_state="complete",
        reasons=(),
        diagnostics=(),
        declarations=declarations,
        callables=(),
        dependency_closure=DependencyClosure(
            status="complete",
            files=(DependencyInput(path=source, sha256=source_sha256),),
            sha256="e" * 64,
        ),
        profile_identity="clang-c-field-profile-r1",
        toolchain_identity=None,
        cache_fingerprint="clang-c-field-cache-r1",
        stdout_path=None,
        stdout_sha256="f" * 64,
        stderr_path=None,
        stderr_sha256="a" * 64,
        preprocessing=(
            event("value", "C_FIELD"),
            event("orphan", "C_FIELD"),
            event("unknown", "C_FIELD"),
        ),
    )
    context_identity = '{"schema":"files-input-fingerprint-v1","id":"c-field-r1"}'

    analysis = _analysis_from_clang_result(
        source, tmp_path, result, context_identity=context_identity
    )

    assert analysis is not None
    assert analysis.status is not None
    assert analysis.status.coverage_state == "partial"
    assert "generated_declaration" in analysis.status.omitted_categories
    value = next(item for item in analysis.declarations if item.name == "Owner::value")
    assert value.kind == "variable"
    assert value.type_text == "int"
    assert value.owner_name == "Owner"
    assert value.owner_stable_id is not None
    assert isinstance(value.generated, CompilerObservedDeclarationProvenance)
    assert value.generated.declaration_kind == "variable"
    assert json.loads(value.generated.receipt_json)["declaration"]["decl_kind"] == (
        "Field"
    )
    assert all(item.name != "Owner::orphan" for item in analysis.declarations)
    assert all(item.name != "Owner::unknown" for item in analysis.declarations)
