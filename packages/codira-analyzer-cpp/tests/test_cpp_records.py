"""Verify C++ record methods and declarator binding without flattening scopes.

Parameters
----------
None

Returns
-------
None
    Defines source-level regressions for record traversal and callable ownership.
"""

from __future__ import annotations

from pathlib import Path

from codira_analyzer_cpp import CppAnalyzer


def test_struct_union_methods_preserve_type_declarations_and_access(
    tmp_path: Path,
) -> None:
    """Keep record declaration kinds alongside method owners with correct access.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Data-only records remain declarations; method-bearing records own methods.
    """
    path = tmp_path / "records.cpp"
    path.write_text(
        "namespace demo {\n"
        "struct Plain { int value; };\n"
        "struct Widget {\n"
        "  int run(int value);\n"
        "private: int secret() { return 1; }\n"
        "};\n"
        "union Value { int number; int read() { return number; } };\n"
        "int Widget::run(int value) { return callee(value); }\n"
        "}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    declarations = {(item.kind, item.name) for item in result.declarations}
    assert {
        ("struct", "demo::Plain"),
        ("struct", "demo::Widget"),
        ("union", "demo::Value"),
    } <= declarations
    classes = {item.name: item for item in result.classes}
    assert set(classes) == {"demo::Widget", "demo::Value"}
    methods = {item.name: item for item in classes["demo::Widget"].methods}
    assert set(methods) == {"run", "secret"}
    assert methods["run"].is_public == 1
    assert methods["run"].end_lineno == 8
    assert methods["run"].calls[0].target == "callee"
    assert methods["secret"].is_public == 0
    assert classes["demo::Value"].methods[0].is_public == 1
    assert result.functions == ()


def test_records_declared_with_variables_and_nested_records_survive(
    tmp_path: Path,
) -> None:
    """Find record specifiers inside declarations and preserve nested ownership.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Record variables are not methods and nested types retain qualified names.
    """
    path = tmp_path / "nested_records.cpp"
    path.write_text(
        "struct S { int run() { return 1; } } instance;\n"
        "class Outer { public:\n"
        "  struct Inner { int read(); } inner;\n"
        "  template<class T> struct Box { T get() { return T(); } };\n"
        "  enum Mode { Fast, Slow } mode;\n"
        "};\n"
        "int Outer::Inner::read() { return 2; }\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    classes = {item.name: item for item in result.classes}
    assert set(classes) == {"S", "Outer", "Outer::Inner", "Outer::Box"}
    assert classes["Outer"].methods == ()
    assert [item.name for item in classes["S"].methods] == ["run"]
    assert [item.name for item in classes["Outer::Inner"].methods] == ["read"]
    assert classes["Outer::Inner"].methods[0].end_lineno == 7
    assert [item.name for item in classes["Outer::Box"].methods] == ["get"]
    assert ("enum", "Outer::Mode") in {
        (item.kind, item.name) for item in result.declarations
    }


def test_pointer_variables_are_not_functions_but_callable_returns_are(
    tmp_path: Path,
) -> None:
    """Distinguish the declared name's binding from an embedded function type.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Function pointers and references remain data; real functions keep parameters.
    """
    path = tmp_path / "pointers.cpp"
    path.write_text(
        "int (*callback)(int);\n"
        "int (&callback_ref)(int) = *callback;\n"
        "int *create(int count);\n"
        "int &read(int index);\n"
        "int (*factory(int value))(double);\n"
        "int value = create(1) != nullptr;\n"
        "struct Widget { int (*callback)(int); int &read(int index); };\n"
        "struct CallbacksOnly { int (*callback)(int); };\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    functions = {item.name: item for item in result.functions}
    assert set(functions) == {"create", "read", "factory"}
    assert functions["create"].parameters == ("count",)
    assert functions["read"].parameters == ("index",)
    assert functions["factory"].parameters == ("value",)
    assert [cls.name for cls in result.classes] == ["Widget"]
    assert [item.name for item in result.classes[0].methods] == ["read"]


def test_template_specializations_keep_separate_method_owners(tmp_path: Path) -> None:
    """Extract explicit specialization bodies rather than merging their owners.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Specialized class/record names and method identities remain distinct.
    """
    path = tmp_path / "specializations.cpp"
    path.write_text(
        "template<class T, int N> struct Box { int get() { return N; } };\n"
        "template<class T> struct Box<T, 0> { int get() { return 0; } };\n"
        "template<> class Box<int, 1> { public: int get() { return 1; } };\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    classes = {cls.name: cls for cls in result.classes}
    assert set(classes) == {"Box", "Box<T,0>", "Box<int,1>"}
    assert all(
        [method.name for method in cls.methods] == ["get"] for cls in classes.values()
    )
    assert len({cls.methods[0].stable_id for cls in classes.values()}) == 3
    assert ("struct", "Box<T,0>") in {
        (item.kind, item.name) for item in result.declarations
    }


def test_allocation_operator_names_retain_keyword_spacing(tmp_path: Path) -> None:
    """Preserve allocation-operator names in normalized callable identities.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        New/delete and their array forms are exposed with valid C++ spellings.
    """
    path = tmp_path / "allocation.cpp"
    path.write_text(
        "struct Allocator {\n"
        "static void *operator new(unsigned long size);\n"
        "static void operator delete(void *ptr);\n"
        "static void *operator new[](unsigned long size);\n"
        "static void operator delete[](void *ptr);\n"
        "};\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [method.name for method in result.classes[0].methods] == [
        "operator new",
        "operator delete",
        "operator new[]",
        "operator delete[]",
    ]


def test_overloads_merge_redeclarations_without_losing_types_or_qualifiers(
    tmp_path: Path,
) -> None:
    """Preserve source overloads while merging names/defaults of redeclarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Typed overloads and const/ref variants retain distinct callable identities.
    """
    path = tmp_path / "overloads.cpp"
    path.write_text(
        "int convert(int value = 1);\n"
        "int convert(int renamed) { return renamed; }\n"
        "double convert(double renamed) { return renamed; }\n"
        "class Widget { public:\n"
        "  int &operator[](unsigned index);\n"
        "  const int &operator[](unsigned index) const;\n"
        "  int read() &;\n"
        "  int read() &&;\n"
        "};\n"
        "int &Widget::operator[](unsigned renamed) { static int v; return v; }\n"
        "const int &Widget::operator[](unsigned renamed) const { static int v; return v; }\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert len(result.functions) == 2
    assert {function.end_lineno for function in result.functions} == {2, 3}
    assert len({function.stable_id for function in result.functions}) == 2
    methods = result.classes[0].methods
    assert len(methods) == 4
    assert len({method.stable_id for method in methods}) == 4
    operators = [method for method in methods if method.name == "operator[]"]
    assert {method.end_lineno for method in operators} == {10, 11}


def test_conditional_definitions_keep_both_source_variants(tmp_path: Path) -> None:
    """Avoid choosing one configuration when duplicate bindings occupy branches.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Both source definitions survive without evaluating build configuration.
    """
    path = tmp_path / "branches.cpp"
    path.write_text(
        "#if FEATURE\nint run(int value) { return first(value); }\n"
        "#else\nint run(int value) { return second(value); }\n#endif\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [function.name for function in result.functions] == ["run", "run"]
    assert len({function.stable_id for function in result.functions}) == 2
    assert [function.calls[0].target for function in result.functions] == [
        "first",
        "second",
    ]


def test_variadic_slots_and_callback_parameter_redeclarations(tmp_path: Path) -> None:
    """Keep ellipsis overloads and merge callbacks with renamed nested parameters.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Variadic syntax distinguishes slots while nested parameter names do not.
    """
    path = tmp_path / "callback_parameters.cpp"
    path.write_text(
        "void log(int level);\n"
        "void log(int level, ...);\n"
        "void invoke(void (*callback)(int old_name));\n"
        "void invoke(void(*renamed)(int other_name)) {}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert len(result.functions) == 3
    assert len({item.stable_id for item in result.functions}) == 3
    callback = next(item for item in result.functions if item.name == "invoke")
    assert callback.parameters == ("renamed",)
    assert callback.end_lineno == 4


def test_type_tokens_keep_word_boundaries_and_literal_contents(tmp_path: Path) -> None:
    """Keep distinct source types distinct when normalizing callable slots.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Multiword type tokens and spaces inside literals do not collapse overloads.
    """
    path = tmp_path / "type_tokens.cpp"
    path.write_text(
        "struct unsignedlong {};\n"
        "void convert(unsigned long value);\n"
        "void convert(unsignedlong value);\n"
        'void consume(decltype("a b") &value);\n'
        'void consume(decltype("ab") &value);\n'
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert len(result.functions) == 4
    assert len({function.stable_id for function in result.functions}) == 4


def test_specialization_names_ignore_comments_without_merging_words(
    tmp_path: Path,
) -> None:
    """Normalize record names using syntax tokens rather than removing all spaces.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Commented multiword specialization names remain separate from identifiers.
    """
    path = tmp_path / "type_names.cpp"
    path.write_text(
        "struct unsignedlong {};\n"
        "template<class T> struct Box { int get() { return 0; } };\n"
        "template<> struct Box<unsigned /* words */ long> { int get() { return 1; } };\n"
        "template<> struct Box<unsignedlong> { int get() { return 2; } };\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert {cls.name for cls in result.classes} == {
        "Box",
        "Box<unsigned long>",
        "Box<unsignedlong>",
    }
    assert len({cls.methods[0].stable_id for cls in result.classes}) == 3


def test_void_parameter_markers_merge_with_empty_parameter_lists(
    tmp_path: Path,
) -> None:
    """Retain C++ void/empty parameter equivalence for direct and callback slots.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Type-based merging does not duplicate ordinary void-marker redeclarations.
    """
    path = tmp_path / "void_parameters.cpp"
    path.write_text(
        "int read(void);\nint read() { return 0; }\n"
        "void invoke(void (*callback)(void));\n"
        "void invoke(void(*renamed)()) {}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert len(result.functions) == 2
    assert {function.name for function in result.functions} == {"read", "invoke"}
    assert all(function.end_lineno is not None for function in result.functions)


def test_nested_template_specialization_keeps_explicit_class_owner(
    tmp_path: Path,
) -> None:
    """Traverse successive template wrappers on an explicit member specialization.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        The primary member and explicitly specialized source definition survive.
    """
    path = tmp_path / "member_specialization.cpp"
    path.write_text(
        "template<class T> struct Holder {\n"
        "template<class U> int read() { return 0; }\n};\n"
        "template<> template<> int Holder<int>::read<int>() { return 1; }\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    classes = {cls.name: cls for cls in result.classes}
    assert set(classes) == {"Holder", "Holder<int>"}
    assert [method.name for method in classes["Holder"].methods] == ["read"]
    specialized = classes["Holder<int>"].methods[0]
    assert specialized.name == "read<int>"
    assert specialized.is_method == 1
    assert specialized.end_lineno == 4
    assert specialized.signature.startswith("template<> template<>")
    assert result.functions == ()
