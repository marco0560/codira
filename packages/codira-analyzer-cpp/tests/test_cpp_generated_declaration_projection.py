"""Focused source-invocation evidence tests for C++ declarations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from codira.generated import (
    CompilerObservedDeclarationProvenance,
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

from codira_analyzer_cpp import (
    _analysis_from_clang_result,
    _clang_macro_invocation_for_declaration,
    _proven_macro_static_definition_pairs,
)


@pytest.mark.parametrize(("end_delta", "expected_evidence"), ((0, True), (12, False)))
def test_cpp_object_like_macro_declaration_uses_native_end_token_start(
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
    source = tmp_path / "object_macro.cpp"
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
            sha256="f" * 64,
        ),
        profile_identity="clang-cpp-object-macro-r1",
        toolchain_identity=None,
        cache_fingerprint="clang-cpp-object-cache-r1",
        stdout_path=None,
        stdout_sha256="a" * 64,
        stderr_path=None,
        stderr_sha256="b" * 64,
        preprocessing=(event,),
    )

    evidence = _clang_macro_invocation_for_declaration(
        declaration,
        result,
        path=source,
        root=tmp_path,
        source_bytes=source_bytes,
        source_sha256=source_sha256,
        context_identity='{"schema":"files-input-fingerprint-v1","id":"cpp-object-r1"}',
    )

    assert (evidence is not None) is expected_evidence
    if evidence is not None:
        assert evidence[0].invocation.text == invocation
        assert (
            source_bytes[slice(*evidence[0].invocation.byte_range)]
            == invocation.encode()
        )


def test_cpp_namespace_macro_definition_pair_preserves_source_definition_anchor(
    tmp_path: Path,
) -> None:
    """Bind a unique macro declaration to its matching source-written definition.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing the C++ translation unit.

    Returns
    -------
    None
        The exact static-member pair carries macro evidence on the source-written
        definition anchor; unrelated ambiguous declarations remain held.
    """
    source = tmp_path / "macro_declarations.cpp"
    source.write_text(
        "#define CPP_VALUE(name) int name = 9\n"
        "#define CPP_STATIC(name) static int name;\n"
        "#define CPP_FIELD(name) int name;\n"
        "#define CPP_CONSTANT(name) constexpr unsigned name = 42\n"
        "namespace Box {\n"
        "  CPP_VALUE(value)\n"
        "  CPP_CONSTANT(answer)\n"
        "  class Owner {\n"
        "  public:\n"
        "    CPP_STATIC(member)\n"
        "    CPP_FIELD(macro_field)\n"
        "    CPP_FIELD(orphan_field)\n"
        "    CPP_FIELD(unknown_field)\n"
        "  };\n"
        "}\n"
        "int Box::Owner::member = 11;\n",
        encoding="utf-8",
    )
    source_bytes = source.read_bytes()

    def point(offset: int, *, is_macro: bool = False) -> SourcePoint:
        """Create a compiler point at one exact fixture byte offset.

        Parameters
        ----------
        offset : int
            Zero-based offset in the source file.
        is_macro : bool, optional
            Whether the compiler marked this point as macro-derived.

        Returns
        -------
        codira_clang_frontend.SourcePoint
            Point with matching spelling and expansion coordinates.
        """
        prefix = source_bytes[:offset]
        position = SourcePosition(
            path=str(source),
            line=prefix.count(b"\n") + 1,
            column=offset - prefix.rfind(b"\n"),
            offset=offset,
        )
        return SourcePoint(spelling=position, expansion=position, is_macro=is_macro)

    def macro_location(invocation: str, argument: str) -> SourcePoint:
        """Build spelling and expansion coordinates for a macro declaration.

        Parameters
        ----------
        invocation : str
            Exact invocation present in the source file.
        argument : str
            Declaration name supplied as a source macro argument.

        Returns
        -------
        codira_clang_frontend.SourcePoint
            Macro location whose expansion begins at the invocation.
        """
        invocation_offset = source_bytes.index(invocation.encode("utf-8"))
        argument_offset = source_bytes.index(
            argument.encode("utf-8"), invocation_offset
        )
        return SourcePoint(
            spelling=point(argument_offset).spelling,
            expansion=point(invocation_offset).expansion,
            is_macro=True,
        )

    def event(invocation: str, macro_name: str) -> FrontendPreprocessorEvent:
        """Build one exact native macro-expansion event for the fixture.

        Parameters
        ----------
        invocation : str
            Exact invocation bytes observed by the preprocessor.
        macro_name : str
            Native macro name.

        Returns
        -------
        codira_clang_frontend.FrontendPreprocessorEvent
            Event whose span is byte-exactly bound to the invocation.
        """
        invocation_bytes = invocation.encode("utf-8")
        start = source_bytes.index(invocation_bytes)
        end = start + len(invocation_bytes) - 1
        return FrontendPreprocessorEvent(
            kind="macro_expansion",
            name=macro_name,
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

    namespace_offset = source_bytes.index(b"Box")
    class_offset = source_bytes.index(b"Owner")
    out_of_line_offset = source_bytes.index(b"member", source_bytes.index(b"int Box"))
    value_invocation = "CPP_VALUE(value)"
    constant_invocation = "CPP_CONSTANT(answer)"
    member_invocation = "CPP_STATIC(member)"
    field_invocation = "CPP_FIELD(macro_field)"
    orphan_field_invocation = "CPP_FIELD(orphan_field)"
    unknown_field_invocation = "CPP_FIELD(unknown_field)"
    declaration_rows = [
        {
            "identity": {"usr": "c:@N@Box", "provenance": "source_written"},
            "entity_kind": "namespace",
            "name": "Box",
            "qualified_name": "Box",
            "decl_kind": "Namespace",
            "signature": "namespace Box",
            "source_text": "namespace Box {",
            "is_definition": True,
            "is_file_scope": True,
            "location": asdict(point(namespace_offset)),
        },
        {
            "identity": {
                "usr": "c:@N@Box@S@Owner",
                "provenance": "source_written",
            },
            "entity_kind": "class",
            "name": "Owner",
            "qualified_name": "Box::Owner",
            "decl_kind": "CXXRecord",
            "is_definition": True,
            "is_file_scope": False,
            "location": asdict(point(class_offset)),
        },
        {
            "identity": {
                "usr": "c:@N@Box@value",
                "kind": "macro_argument",
                "provenance": "macro_argument",
            },
            "entity_kind": "variable",
            "name": "value",
            "qualified_name": "Box::value",
            "decl_kind": "Var",
            "type": "int",
            "is_definition": True,
            "is_file_scope": False,
            "location": asdict(macro_location(value_invocation, "value")),
            "owner_usr": "c:@N@Box",
            "owner_name": "Box",
            "owner_kind": "Namespace",
            "owner_location": asdict(point(namespace_offset)),
        },
        {
            "identity": {
                "usr": "c:@N@Box@answer",
                "kind": "macro_argument",
                "provenance": "macro_argument",
            },
            "entity_kind": "constant",
            "name": "answer",
            "qualified_name": "Box::answer",
            "decl_kind": "Var",
            "type": "const unsigned int",
            "is_definition": True,
            "is_file_scope": False,
            "location": asdict(macro_location(constant_invocation, "answer")),
            "owner_usr": "c:@N@Box",
            "owner_name": "Box",
            "owner_kind": "Namespace",
            "owner_location": asdict(point(namespace_offset)),
        },
        {
            "identity": {
                "usr": "c:@N@Box@S@Owner@member",
                "kind": "macro_replacement",
                "provenance": "macro_replacement",
            },
            "entity_kind": "variable",
            "name": "member",
            "qualified_name": "Box::Owner::member",
            "decl_kind": "Var",
            "signature": "int Box::Owner::member = 11",
            "source_text": "int Box::Owner::member = 11;",
            "type": "int",
            "is_definition": False,
            "is_file_scope": False,
            "location": asdict(macro_location(member_invocation, "member")),
            "owner_usr": "c:@N@Box@S@Owner",
            "owner_name": "Box::Owner",
            "owner_kind": "CXXRecord",
            "owner_location": asdict(point(class_offset)),
            "access": "public",
        },
        {
            "identity": {
                "usr": "c:@N@Box@S@Owner@macro_field",
                "kind": "macro_argument",
                "provenance": "macro_argument",
            },
            "entity_kind": "variable",
            "name": "macro_field",
            "qualified_name": "Box::Owner::macro_field",
            "decl_kind": "Field",
            "type": "int",
            "is_definition": True,
            "is_file_scope": False,
            "location": asdict(macro_location(field_invocation, "macro_field")),
            "owner_usr": "c:@N@Box@S@Owner",
            "owner_name": "Box::Owner",
            "owner_kind": "CXXRecord",
            "owner_location": asdict(point(class_offset)),
            "access": "public",
        },
        {
            "identity": {
                "usr": "c:@N@Box@S@Owner@orphan_field",
                "kind": "macro_argument",
                "provenance": "macro_argument",
            },
            "entity_kind": "variable",
            "name": "orphan_field",
            "qualified_name": "Box::Owner::orphan_field",
            "decl_kind": "Field",
            "type": "int",
            "is_definition": True,
            "is_file_scope": False,
            "location": asdict(macro_location(orphan_field_invocation, "orphan_field")),
        },
        {
            "identity": {
                "usr": "c:@N@Box@S@Owner@unknown_field",
                "kind": "unknown",
                "provenance": "unknown",
            },
            "entity_kind": "variable",
            "name": "unknown_field",
            "qualified_name": "Box::Owner::unknown_field",
            "decl_kind": "Field",
            "type": "int",
            "is_definition": True,
            "is_file_scope": False,
            "location": asdict(
                macro_location(unknown_field_invocation, "unknown_field")
            ),
            "owner_usr": "c:@N@Box@S@Owner",
            "owner_name": "Box::Owner",
            "owner_kind": "CXXRecord",
            "owner_location": asdict(point(class_offset)),
            "access": "public",
        },
        {
            "identity": {
                "usr": "c:@N@Box@S@Owner@member",
                "provenance": "source_written",
            },
            "entity_kind": "variable",
            "name": "member",
            "qualified_name": "Box::Owner::member",
            "decl_kind": "Var",
            "type": "int",
            "is_definition": True,
            "is_file_scope": False,
            "location": asdict(point(out_of_line_offset)),
            "owner_usr": "c:@N@Box@S@Owner",
            "owner_name": "Box::Owner",
            "owner_kind": "CXXRecord",
            "owner_location": asdict(point(class_offset)),
            "access": "public",
        },
    ]
    declarations, _, _ = _decode_entities(
        {"non_function_declarations": declaration_rows}
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
        profile_identity="clang-cpp-declaration-profile-r1",
        toolchain_identity=None,
        cache_fingerprint="clang-cpp-declaration-cache-r1",
        stdout_path=None,
        stdout_sha256="c" * 64,
        stderr_path=None,
        stderr_sha256="d" * 64,
        preprocessing=(
            event(value_invocation, "CPP_VALUE"),
            event(constant_invocation, "CPP_CONSTANT"),
            event(member_invocation, "CPP_STATIC"),
            event(field_invocation, "CPP_FIELD"),
            event(orphan_field_invocation, "CPP_FIELD"),
            event(unknown_field_invocation, "CPP_FIELD"),
        ),
    )
    context_identity = '{"schema":"files-input-fingerprint-v1","id":"cpp-r1"}'

    analysis = _analysis_from_clang_result(
        source, tmp_path, result, context_identity=context_identity
    )

    assert analysis is not None
    assert analysis.status is not None
    assert analysis.status.coverage_state == "partial"
    assert "generated_declaration" in analysis.status.omitted_categories
    value = next(item for item in analysis.declarations if item.name == "Box::value")
    assert value.type_text == "int"
    assert value.owner_name == "Box"
    assert value.owner_stable_id is not None
    assert isinstance(value.generated, CompilerObservedDeclarationProvenance)
    assert value.generated.origin == "macro_argument"
    assert value.generated.declaration_kind == "variable"
    assert value.generated.source_sha256 == source_sha256
    assert value.generated.context_identity == context_identity
    assert value.generated.invocation.text == value_invocation
    assert value.generated.receipt_namespace == (
        "clang.frontend.declaration-observation.v1"
    )
    receipt = json.loads(value.generated.receipt_json)
    assert receipt["declaration"]["owner_usr"] == "c:@N@Box"
    assert receipt["declaration"]["type_text"] == "int"
    constant = next(
        item for item in analysis.declarations if item.name == "Box::answer"
    )
    assert constant.kind == "constant"
    assert constant.type_text == "const unsigned int"
    assert isinstance(constant.generated, CompilerObservedDeclarationProvenance)
    assert constant.generated.declaration_kind == "constant"
    assert constant.generated.invocation.text == constant_invocation
    macro_field = next(
        item for item in analysis.declarations if item.name == "Box::Owner::macro_field"
    )
    assert macro_field.kind == "variable"
    assert macro_field.owner_name == "Box::Owner"
    assert macro_field.owner_stable_id is not None
    assert macro_field.access == "public"
    assert isinstance(macro_field.generated, CompilerObservedDeclarationProvenance)
    assert macro_field.generated.declaration_kind == "variable"
    assert (
        json.loads(macro_field.generated.receipt_json)["declaration"]["decl_kind"]
        == "Field"
    )
    member_rows = [
        item for item in analysis.declarations if item.name == "Box::Owner::member"
    ]
    assert len(member_rows) == 1
    member = member_rows[0]
    assert member.lineno == 16
    assert isinstance(member.generated, CompilerObservedDeclarationProvenance)
    assert member.generated.invocation.text == member_invocation
    assert member.generated.source_sha256 == source_sha256
    assert all(
        item.name != "Box::Owner::orphan_field" for item in analysis.declarations
    )
    assert all(
        item.name != "Box::Owner::unknown_field" for item in analysis.declarations
    )
    generated_rows = generated_provenance_rows(analysis)
    assert {stable_id for stable_id, _ in generated_rows} == {
        value.stable_id,
        constant.stable_id,
        macro_field.stable_id,
        member.stable_id,
    }

    macro_member = next(
        item
        for item in declarations
        if item.provenance == "macro_replacement" and item.name == "member"
    )
    source_definition = next(
        item
        for item in declarations
        if item.provenance == "source_written" and item.name == "member"
    )
    assert _proven_macro_static_definition_pairs(
        declarations, source, source_bytes
    ) == {id(macro_member): id(source_definition)}


@pytest.mark.parametrize(
    "mutation",
    [
        "type",
        "access",
        "owner_usr",
        "owner_name",
        "owner_kind",
        "file_scope",
        "qualified_name",
    ],
)
def test_cpp_macro_static_definition_pair_rejects_mismatched_partner(
    mutation: str,
    tmp_path: Path,
) -> None:
    """Reject redeclaration pairs when their semantic facts disagree.

    Parameters
    ----------
    mutation : str
        Definition fact to corrupt.
    tmp_path : pathlib.Path
        Temporary repository root used by the shared fixture test.

    Returns
    -------
    None
        A nonmatching same-USR pair is not accepted as a generated declaration.
    """
    # The positive fixture builds declarations and source anchors locally, so
    # keep this negative test independent and exercise the pair proof directly.
    source = tmp_path / "pair.cpp"
    source.write_text(
        "#define CPP_STATIC(name) static int name;\n"
        "struct Owner { public: CPP_STATIC(member) };\n"
        "int Owner::member = 11;\n",
        encoding="utf-8",
    )
    source_bytes = source.read_bytes()

    def location(offset: int, *, macro: bool = False) -> SourcePoint:
        """Return a source point at ``offset`` in the test translation unit.

        Parameters
        ----------
        offset : int
            Byte offset in the source file.
        macro : bool, optional
            Whether the point represents macro expansion.

        Returns
        -------
        codira_clang_frontend.SourcePoint
            Point anchored to the test translation unit.
        """
        prefix = source_bytes[:offset]
        position = SourcePosition(
            path=str(source),
            line=prefix.count(b"\n") + 1,
            column=offset - prefix.rfind(b"\n"),
            offset=offset,
        )
        return SourcePoint(spelling=position, expansion=position, is_macro=macro)

    macro_start = source_bytes.index(b"CPP_STATIC(member)")
    definition_start = source_bytes.rindex(b"member")
    owner_start = source_bytes.index(b"Owner")
    macro = FrontendDeclaration(
        usr="c:@S@Owner@member",
        kind="variable",
        name="member",
        qualified_name="Owner::member",
        decl_kind="Var",
        type_text="int",
        signature="static int member",
        parameters=(),
        has_prototype=None,
        source_text=None,
        location=SourcePoint(
            spelling=location(macro_start + len("CPP_STATIC(")).spelling,
            expansion=location(macro_start, macro=True).expansion,
            is_macro=True,
        ),
        is_definition=False,
        is_file_scope=False,
        provenance="macro_replacement",
        span=None,
        owner_usr="c:@S@Owner",
        owner_name="Owner",
        owner_kind="CXXRecord",
        owner_location=location(owner_start),
        access="public",
    )
    definition = FrontendDeclaration(
        usr=macro.usr,
        kind="variable",
        name="member",
        qualified_name="Owner::member",
        decl_kind="Var",
        type_text="int",
        signature="int Owner::member = 11",
        parameters=(),
        has_prototype=None,
        source_text="int Owner::member = 11;",
        location=location(definition_start),
        is_definition=True,
        is_file_scope=False,
        provenance="source_written",
        span=None,
        owner_usr=macro.owner_usr,
        owner_name=macro.owner_name,
        owner_kind=macro.owner_kind,
        owner_location=macro.owner_location,
        access="public",
    )

    if mutation == "type":
        mutated_definition = replace(definition, type_text="long")
    elif mutation == "access":
        mutated_definition = replace(definition, access="private")
    elif mutation == "owner_usr":
        mutated_definition = replace(definition, owner_usr="c:@N@Box@S@Other")
    elif mutation == "owner_name":
        mutated_definition = replace(definition, owner_name="Box::Other")
    elif mutation == "owner_kind":
        mutated_definition = replace(definition, owner_kind="Namespace")
    elif mutation == "file_scope":
        mutated_definition = replace(definition, is_file_scope=True)
    else:
        mutated_definition = replace(definition, qualified_name="Box::Owner::different")
    assert (
        _proven_macro_static_definition_pairs(
            (macro, mutated_definition), source, source_bytes
        )
        == {}
    )


def test_cpp_macro_static_definition_pair_rejects_ambiguous_or_same_site_pairs(
    tmp_path: Path,
) -> None:
    """Reject extra same-USR rows and pairs that do not have distinct sites.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root used for source anchors.

    Returns
    -------
    None
        Ambiguous and same-site declaration groups remain unsupported.
    """
    source = tmp_path / "pair.cpp"
    source.write_text(
        "#define CPP_STATIC(name) static int name;\n"
        "struct Owner { public: CPP_STATIC(member) };\n"
        "int Owner::member = 11;\n",
        encoding="utf-8",
    )
    source_bytes = source.read_bytes()

    def point(offset: int, *, is_macro: bool = False) -> SourcePoint:
        """Build an exact source point for one fixture byte offset.

        Parameters
        ----------
        offset : int
            Byte offset in the fixture.
        is_macro : bool, optional
            Whether the point is macro-derived.

        Returns
        -------
        codira_clang_frontend.SourcePoint
            Source coordinates at ``offset``.
        """
        prefix = source_bytes[:offset]
        position = SourcePosition(
            path=str(source),
            line=prefix.count(b"\n") + 1,
            column=offset - prefix.rfind(b"\n"),
            offset=offset,
        )
        return SourcePoint(spelling=position, expansion=position, is_macro=is_macro)

    # Reuse a compact three-row native-shaped fixture to cover cardinality and
    # source-site uniqueness without depending on a live Clang installation.
    macro_offset = source_bytes.index(b"CPP_STATIC(member)")
    definition_offset = source_bytes.rindex(b"member")
    owner_offset = source_bytes.index(b"Owner")
    macro = FrontendDeclaration(
        usr="c:@S@Owner@member",
        kind="variable",
        name="member",
        qualified_name="Owner::member",
        decl_kind="Var",
        type_text="int",
        signature="static int member",
        parameters=(),
        has_prototype=None,
        source_text=None,
        location=SourcePoint(
            spelling=point(macro_offset + len("CPP_STATIC(")).spelling,
            expansion=point(macro_offset, is_macro=True).expansion,
            is_macro=True,
        ),
        is_definition=False,
        is_file_scope=False,
        provenance="macro_replacement",
        owner_usr="c:@S@Owner",
        span=None,
        owner_name="Owner",
        owner_kind="CXXRecord",
        owner_location=point(owner_offset),
        access="public",
    )
    definition = FrontendDeclaration(
        usr=macro.usr,
        kind="variable",
        name="member",
        qualified_name="Owner::member",
        decl_kind="Var",
        type_text="int",
        signature="int Owner::member = 11",
        parameters=(),
        has_prototype=None,
        source_text="int Owner::member = 11;",
        location=point(definition_offset),
        is_definition=True,
        is_file_scope=False,
        provenance="source_written",
        owner_usr=macro.owner_usr,
        span=None,
        owner_name=macro.owner_name,
        owner_kind=macro.owner_kind,
        owner_location=macro.owner_location,
        access="public",
    )

    assert _proven_macro_static_definition_pairs(
        (macro, definition), source, source_bytes
    ) == {id(macro): id(definition)}
    assert (
        _proven_macro_static_definition_pairs(
            (macro, definition, replace(definition)), source, source_bytes
        )
        == {}
    )
    same_site_definition = replace(definition, location=macro.location)
    assert (
        _proven_macro_static_definition_pairs(
            (macro, same_site_definition), source, source_bytes
        )
        == {}
    )
    assert (
        _proven_macro_static_definition_pairs(
            (replace(macro, location=point(macro_offset)), definition),
            source,
            source_bytes,
        )
        == {}
    )

    definition_location = definition.location
    assert definition_location is not None
    definition_position = definition_location.spelling
    assert definition_position is not None
    definition_line = definition_position.line
    definition_column = definition_position.column
    assert definition_line is not None
    assert definition_column is not None
    invalid_definition_points = (
        replace(definition_position, path=str(tmp_path / "other.cpp")),
        replace(definition_position, offset=len(source_bytes)),
        replace(definition_position, line=definition_line + 1),
        replace(definition_position, column=definition_column + 1),
        point(owner_offset).spelling,
    )
    for invalid_position in invalid_definition_points:
        invalid_definition = replace(
            definition,
            location=replace(definition_location, spelling=invalid_position),
        )
        assert (
            _proven_macro_static_definition_pairs(
                (macro, invalid_definition), source, source_bytes
            )
            == {}
        )

    declaration_bytes = b"int Owner::member = 11;"
    for continuation_byte in (b"$", b"\\"):
        malformed_source_bytes = source_bytes.replace(
            declaration_bytes,
            b"int Owner::member" + continuation_byte + b"suffix = 11;",
        )
        source.write_bytes(malformed_source_bytes)
        assert (
            _proven_macro_static_definition_pairs(
                (macro, definition), source, malformed_source_bytes
            )
            == {}
        )
