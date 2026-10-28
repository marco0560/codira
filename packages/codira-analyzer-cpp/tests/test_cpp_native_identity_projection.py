"""Projection identity regressions from retained Clang native records."""

from __future__ import annotations

from pathlib import Path

from codira_clang_frontend.contracts import (
    FrontendCallable,
    FrontendDeclaration,
    FrontendPreprocessorEvent,
    FrontendResult,
    SourcePoint,
    SourcePosition,
    SourceSpan,
)

from codira_analyzer_cpp import _analysis_from_clang_result


def _point(source: Path, content: bytes, offset: int) -> SourcePoint:
    """Build matching physical spelling and expansion coordinates.

    Parameters
    ----------
    source : pathlib.Path
        Source file represented by the coordinate.
    content : bytes
        Exact UTF-8 source bytes used to calculate line and column.
    offset : int
        Byte offset in ``content``.

    Returns
    -------
    codira_clang_frontend.SourcePoint
        Non-macro coordinate bound to the source file.
    """
    prefix = content[:offset]
    line = prefix.count(b"\n") + 1
    column = offset - prefix.rfind(b"\n")
    position = SourcePosition(path=str(source), line=line, column=column, offset=offset)
    return SourcePoint(spelling=position, expansion=position, is_macro=False)


def _result(
    *,
    declarations: tuple[FrontendDeclaration, ...] = (),
    callables: tuple[FrontendCallable, ...] = (),
    preprocessing: tuple[FrontendPreprocessorEvent, ...] = (),
) -> FrontendResult:
    """Build a complete frontend result for deterministic projection tests.

    Parameters
    ----------
    declarations : tuple[FrontendDeclaration, ...], optional
        Compiler declaration rows for the test source.
    callables : tuple[FrontendCallable, ...], optional
        Compiler callable rows for the test source.
    preprocessing : tuple[FrontendPreprocessorEvent, ...], optional
        Macro events with native source anchors.

    Returns
    -------
    codira_clang_frontend.FrontendResult
        Complete parse result with no external dependency requirements.
    """
    return FrontendResult(
        status="parsed",
        coverage_state="complete",
        reasons=(),
        diagnostics=(),
        declarations=declarations,
        callables=callables,
        dependency_closure=None,
        profile_identity="native-identity-test-profile",
        toolchain_identity=None,
        cache_fingerprint="native-identity-test-fingerprint",
        stdout_path=None,
        stdout_sha256=None,
        stderr_path=None,
        stderr_sha256=None,
        preprocessing=preprocessing,
    )


def test_cpp_clang_projection_coalesces_compatible_usr_definition(
    tmp_path: Path,
) -> None:
    """Coalesce one same-USR declaration/definition and its repeated comment.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing the source declaration and definition.

    Returns
    -------
    None
        The result keeps one definition-anchored artifact and one comment.
    """
    source = tmp_path / "pass_id.cpp"
    text = (
        "struct Owner {\n"
        "  /// Unique ID.\n"
        "  static const char ID;\n"
        "};\n"
        "const char Owner::ID = 0;\n"
    )
    source.write_text(text, encoding="utf-8")
    content = source.read_bytes()
    usr = "c:@S@Owner@ID"
    owner_usr = "c:@S@Owner"
    owner_location = _point(source, content, content.index(b"struct Owner"))
    comment_start = content.index(b"/// Unique ID.")
    comment_location = _point(source, content, comment_start)
    comment_span = SourceSpan(
        begin=comment_location,
        end=_point(source, content, comment_start + len(b"/// Unique ID.")),
    )
    declaration_location = _point(source, content, content.index(b"ID;"))
    definition_location = _point(source, content, content.index(b"Owner::ID"))
    owner = FrontendDeclaration(
        usr=owner_usr,
        kind="class",
        name="Owner",
        qualified_name="Owner",
        decl_kind="CXXRecord",
        signature="struct Owner",
        type_text=None,
        parameters=(),
        has_prototype=None,
        is_definition=True,
        provenance="source_written",
        location=owner_location,
        span=None,
    )

    def pass_id_row(is_definition: bool, location: SourcePoint) -> FrontendDeclaration:
        """Construct one compiler row in the redeclaration chain.

        Parameters
        ----------
        is_definition : bool
            Whether the row is the unique definition.
        location : codira_clang_frontend.SourcePoint
            Physical compiler coordinate of the declaration.

        Returns
        -------
        codira_clang_frontend.FrontendDeclaration
            Source-written variable declaration with shared semantic identity.
        """
        return FrontendDeclaration(
            usr=usr,
            kind="constant",
            name="ID",
            qualified_name="Owner::ID",
            decl_kind="Var",
            signature="const char ID",
            type_text="const char",
            parameters=(),
            has_prototype=None,
            is_definition=is_definition,
            provenance="source_written",
            location=location,
            span=None,
            owner_usr=owner_usr,
            owner_name="Owner",
            owner_location=owner_location,
            owner_kind="CXXRecord",
            access="public",
            documentation="Unique ID.",
            documentation_location=comment_location,
            documentation_span=comment_span,
        )

    declaration = pass_id_row(False, declaration_location)
    definition = pass_id_row(True, definition_location)

    analysis = _analysis_from_clang_result(
        source,
        tmp_path,
        _result(declarations=(owner, declaration, definition)),
    )

    assert analysis is not None
    ids = [item for item in analysis.declarations if item.name == "Owner::ID"]
    assert len(ids) == 1
    assert ids[0].lineno == 5
    docs = [
        item
        for item in analysis.documentation
        if item.owner_stable_id == ids[0].stable_id
    ]
    assert len(docs) == 1
    assert docs[0].lineno == 2


def test_cpp_clang_projection_holds_redeclarations_without_type_proof(
    tmp_path: Path,
) -> None:
    """Hold a same-USR pair when the compiler type is unknown.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing one declaration and one definition.

    Returns
    -------
    None
        The adapter declines to coalesce incomplete identity facts.
    """
    source = tmp_path / "unknown_type.cpp"
    source.write_text("struct Owner { static int value; };\nint Owner::value = 1;\n")
    content = source.read_bytes()
    owner_location = _point(source, content, content.index(b"struct Owner"))

    def unknown_type_row(
        is_definition: bool, location: SourcePoint
    ) -> FrontendDeclaration:
        """Construct one redeclaration without canonical type evidence.

        Parameters
        ----------
        is_definition : bool
            Whether this row is the definition.
        location : codira_clang_frontend.SourcePoint
            Physical compiler coordinate of the declaration.

        Returns
        -------
        codira_clang_frontend.FrontendDeclaration
            Incomplete same-USR variable row.
        """
        return FrontendDeclaration(
            usr="c:@S@Owner@value",
            kind="variable",
            name="value",
            qualified_name="Owner::value",
            decl_kind="Var",
            signature="int value",
            type_text=None,
            parameters=(),
            has_prototype=None,
            is_definition=is_definition,
            provenance="source_written",
            location=location,
            span=None,
            owner_usr="c:@S@Owner",
            owner_name="Owner",
            owner_location=owner_location,
            owner_kind="CXXRecord",
            access="public",
        )

    declarations = (
        unknown_type_row(False, _point(source, content, content.index(b"value;"))),
        unknown_type_row(True, _point(source, content, content.index(b"Owner::value"))),
    )

    analysis = _analysis_from_clang_result(
        source, tmp_path, _result(declarations=declarations)
    )

    assert analysis is None


def test_cpp_clang_projection_holds_nonunique_definition_chains(
    tmp_path: Path,
) -> None:
    """Hold same-USR chains with zero or multiple definitions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing compatible declaration coordinates.

    Returns
    -------
    None
        Neither ambiguous definition cardinality is coalesced.
    """
    source = tmp_path / "definition_cardinality.cpp"
    source.write_text("struct Owner { static int value; };\nint Owner::value = 1;\n")
    content = source.read_bytes()
    owner_location = _point(source, content, content.index(b"struct Owner"))
    declaration_location = _point(source, content, content.index(b"value;"))
    definition_location = _point(source, content, content.index(b"Owner::value"))

    for definition_flags in ((False, False), (True, True)):
        declarations = tuple(
            FrontendDeclaration(
                usr="c:@S@Owner@value",
                kind="variable",
                name="value",
                qualified_name="Owner::value",
                decl_kind="Var",
                signature="int value",
                type_text="int",
                parameters=(),
                has_prototype=None,
                is_definition=is_definition,
                provenance="source_written",
                location=location,
                span=None,
                owner_usr="c:@S@Owner",
                owner_name="Owner",
                owner_location=owner_location,
                owner_kind="CXXRecord",
                access="public",
            )
            for is_definition, location in zip(
                definition_flags,
                (declaration_location, definition_location),
                strict=True,
            )
        )
        analysis = _analysis_from_clang_result(
            source, tmp_path, _result(declarations=declarations)
        )
        assert analysis is None


def test_cpp_clang_projection_preserves_same_name_scoped_aliases(
    tmp_path: Path,
) -> None:
    """Keep distinct Clang USRs for same-name aliases in separate owners.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing two scoped aliases.

    Returns
    -------
    None
        The aliases retain distinct rows and stable IDs.
    """
    source = tmp_path / "scoped_alias.cpp"
    text = "void first() { using InsertPointTy = int; }\nvoid second() { using InsertPointTy = long; }\n"
    source.write_text(text, encoding="utf-8")
    content = source.read_bytes()
    declarations = tuple(
        FrontendDeclaration(
            usr=usr,
            kind="type_alias",
            name="InsertPointTy",
            qualified_name="InsertPointTy",
            decl_kind="TypeAlias",
            signature=signature,
            type_text="",
            parameters=(),
            has_prototype=None,
            is_definition=True,
            provenance="source_written",
            location=_point(source, content, content.index(b"InsertPointTy", start)),
            span=None,
            owner_usr=owner_usr,
            owner_name=owner_name,
            owner_kind="CXXMethod",
            is_file_scope=False,
        )
        for usr, owner_usr, owner_name, signature, start in (
            (
                "c:@F@first#@InsertPointTy",
                "c:@F@first#",
                "first",
                "using InsertPointTy = int",
                0,
            ),
            (
                "c:@F@second#@InsertPointTy",
                "c:@F@second#",
                "second",
                "using InsertPointTy = long",
                content.index(b"void second"),
            ),
        )
    )

    analysis = _analysis_from_clang_result(
        source, tmp_path, _result(declarations=declarations)
    )

    assert analysis is not None
    aliases = [item for item in analysis.declarations if item.name == "InsertPointTy"]
    assert len(aliases) == 2
    assert len({item.stable_id for item in aliases}) == 2
    assert {item.signature for item in aliases} == {
        "using InsertPointTy = int",
        "using InsertPointTy = long",
    }


def test_cpp_clang_projection_anchors_repeated_macro_definitions(
    tmp_path: Path,
) -> None:
    """Give repeated macro names distinct physical identities.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing two definitions of one macro.

    Returns
    -------
    None
        The macro rows retain their source order and unique stable IDs.
    """
    source = tmp_path / "repeated_macro.cpp"
    text = "#define VALUE(x) (x)\n#undef VALUE\n#define VALUE(x) ((x) + 1)\n"
    source.write_text(text, encoding="utf-8")
    content = source.read_bytes()
    events = tuple(
        FrontendPreprocessorEvent(
            kind="macro_definition",
            name="VALUE",
            replacement=replacement,
            replacement_truncated=False,
            function_like=True,
            parameters=("x",),
            source_text=source_text,
            condition=None,
            result=None,
            macro_defined=None,
            invocation=None,
            location=_point(source, content, offset),
            span=None,
        )
        for offset, source_text, replacement in (
            (content.index(b"#define VALUE"), "#define VALUE(x) (x)", ("(", "x", ")")),
            (
                content.rindex(b"#define VALUE"),
                "#define VALUE(x) ((x) + 1)",
                ("(", "(", "x", ")", "+", "1", ")"),
            ),
        )
    )

    analysis = _analysis_from_clang_result(
        source, tmp_path, _result(preprocessing=events)
    )

    assert analysis is not None
    macros = [item for item in analysis.declarations if item.kind == "macro"]
    assert len(macros) == 2
    assert len({item.stable_id for item in macros}) == 2
    assert [item.lineno for item in macros] == [1, 3]


def test_cpp_clang_projection_holds_inconsistent_macro_anchor_metadata(
    tmp_path: Path,
) -> None:
    """Hold conflicting coordinates instead of dropping one macro event.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing one macro definition.

    Returns
    -------
    None
        Same-offset events with inconsistent line metadata are not coalesced.
    """
    source = tmp_path / "ambiguous_macro.cpp"
    source.write_text("#define VALUE 1\n")
    content = source.read_bytes()
    offset = content.index(b"#define VALUE")
    correct = _point(source, content, offset)
    position = SourcePosition(path=str(source), line=2, column=1, offset=offset)
    conflicting = SourcePoint(spelling=position, expansion=position, is_macro=False)

    def event(location: SourcePoint) -> FrontendPreprocessorEvent:
        """Build one same-anchor macro callback.

        Parameters
        ----------
        location : codira_clang_frontend.SourcePoint
            Native callback coordinate to preserve.

        Returns
        -------
        codira_clang_frontend.FrontendPreprocessorEvent
            Macro definition event with fixed spelling.
        """
        return FrontendPreprocessorEvent(
            kind="macro_definition",
            name="VALUE",
            replacement=("1",),
            replacement_truncated=False,
            function_like=False,
            parameters=(),
            source_text="#define VALUE 1",
            condition=None,
            result=None,
            macro_defined=None,
            invocation=None,
            location=location,
            span=None,
        )

    analysis = _analysis_from_clang_result(
        source,
        tmp_path,
        _result(preprocessing=(event(correct), event(conflicting))),
    )

    assert analysis is None


def test_cpp_clang_projection_binds_docs_to_final_callable_ids(
    tmp_path: Path,
) -> None:
    """Keep docs attached to each distinct overload after ID disambiguation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing two same-name method specializations.

    Returns
    -------
    None
        Both callables and their docs have matching unique owner identities.
    """
    source = tmp_path / "template_methods.cpp"
    text = (
        "/// First specialization.\n"
        "int Owner::parse(int value) { return value; }\n"
        "/// Second specialization.\n"
        "int Owner::parse(double value) { return 0; }\n"
    )
    source.write_text(text, encoding="utf-8")
    content = source.read_bytes()
    owner_location = _point(source, content, 0)
    callables = []
    for usr, signature, parameter, comment in (
        (
            "c:@S@Owner@F@parse#I#",
            "int parse(int)",
            ("value", "int"),
            "First specialization.",
        ),
        (
            "c:@S@Owner@F@parse#d#",
            "int parse(double)",
            ("value", "double"),
            "Second specialization.",
        ),
    ):
        comment_bytes = f"/// {comment}".encode()
        comment_offset = content.index(comment_bytes)
        definition_offset = content.index(b"Owner::parse", comment_offset)
        comment_point = _point(source, content, comment_offset)
        callables.append(
            FrontendCallable(
                usr=usr,
                kind="method",
                name="parse",
                qualified_name="Owner::parse",
                lexical_owner="Owner",
                decl_kind="CXXMethod",
                signature=signature,
                function_type=signature,
                parameters=(parameter,),
                has_prototype=True,
                is_definition=True,
                is_public=True,
                provenance="source_written",
                location=_point(source, content, definition_offset),
                span=None,
                calls=(),
                returns_value=True,
                owner_usr="c:@S@Owner",
                owner_location=owner_location,
                documentation=comment,
                documentation_location=comment_point,
                documentation_span=SourceSpan(
                    begin=comment_point,
                    end=_point(source, content, comment_offset + len(comment_bytes)),
                ),
                has_body=True,
            )
        )

    analysis = _analysis_from_clang_result(
        source,
        tmp_path,
        _result(callables=tuple(callables)),
    )

    assert analysis is not None
    assert len(analysis.functions) == 2
    assert len({item.stable_id for item in analysis.functions}) == 2
    docs = [item for item in analysis.documentation if item.title == "parse"]
    assert len(docs) == 2
    assert {item.owner_stable_id for item in docs} == {
        item.stable_id for item in analysis.functions
    }
    assert {item.text for item in docs} == {
        "First specialization.",
        "Second specialization.",
    }
