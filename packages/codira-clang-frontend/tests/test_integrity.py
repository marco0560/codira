"""Focused integrity checks for the optional Clang frontend package.

Parameters
----------
None

Returns
-------
None
    Test module for profile, protocol, cache, and attempt invariants.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

from codira_clang_frontend import (
    ClangFrontend,
    CompilationContext,
    CompileProfile,
    captured_profile_fingerprint,
    directory_membership_sha256,
    from_captured_argv,
    from_captured_profile_json,
    from_captured_profiles_json,
    frontend_profile_fingerprint,
    PROFILE_SCHEMA,
    resolve_header_projection,
    write_prepared_profile,
)
from codira_clang_frontend.contracts import (
    DependencyInput,
    FrontendMacroDefinitionLink,
    IncludeDirectoryInput,
    ToolchainIdentity,
)
from codira_clang_frontend.header_projection_cli import (
    _write_captured_profiles_manifest,
)
from codira_clang_frontend.frontend import (
    _decode_compilation_context,
    _decode_entities,
    _decode_preprocessing,
    _dependency_closure,
    _validate_response,
)


def sha256(path: Path) -> str:
    """Hash a fixture file for exact profile identities.

    Parameters
    ----------
    path : pathlib.Path
        File to hash.

    Returns
    -------
    str
        Lowercase SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_response(
    schema_version: str, preprocessing: list[dict[str, object]]
) -> dict[str, object]:
    """Build the minimum structurally valid response for a protocol test.

    Parameters
    ----------
    schema_version : str
        Native helper protocol schema identifier.
    preprocessing : list[dict[str, object]]
        Ordered native preprocessor event records.

    Returns
    -------
    dict[str, object]
        Minimal response accepted by the common native protocol validator.
    """
    response: dict[str, object] = {
        "schema_version": schema_version,
        "declarations": [],
        "non_function_declarations": [],
        "calls": [],
        "diagnostics": [],
        "dependency_paths": [],
        "search_directories": [],
        "includes": [],
        "preprocessing": preprocessing,
        "documentation_comments": [],
        "capture_mode": "source_relevant",
        "clang_version": "Clang protocol fixture",
        "target_triple": "x86_64-unknown-linux-gnu",
        "sysroot": "/",
        "tool_return_code": 0,
        "capture_projection": {},
    }
    if schema_version in {
        "codira.clang-frontend-native/4",
        "codira.clang-frontend-native/5",
        "codira.clang-frontend-native/6",
    }:
        response["translation_unit_file"] = "/repo/main.c"
        response["projection_file"] = None
    return response


def macro_expansion_event() -> dict[str, object]:
    """Build a valid source macro expansion for native protocol tests.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Macro expansion with a resolved physical definition link.
    """
    location = {
        "spelling": {
            "path": "/repo/include/macros.h",
            "line": 12,
            "column": 9,
            "offset": 277,
        },
        "expansion": {
            "path": "/repo/include/macros.h",
            "line": 12,
            "column": 9,
            "offset": 277,
        },
        "is_macro": False,
    }
    return {
        "kind": "macro_expansion",
        "name": "SELECT",
        "invocation": "SELECT(7)",
        "range": {},
        "location": {
            "spelling": {
                "path": "/repo/main.c",
                "line": 20,
                "column": 7,
                "offset": 355,
            },
            "expansion": {
                "path": "/repo/main.c",
                "line": 20,
                "column": 7,
                "offset": 355,
            },
            "is_macro": False,
        },
        "macro_definition_link": {
            "status": "resolved",
            "name": "SELECT",
            "name_token": "SELECT",
            "location": location,
            "function_like": True,
        },
    }


class FrontendIntegrityTests(unittest.TestCase):
    """Exercise attempt, stream, and shadowing-header identity rules.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Test case containing package integrity assertions.
    """

    def test_raw_invalid_bytes_are_retained_and_attempt_id_is_reserved(self) -> None:
        """Retain invalid helper bytes and reject reuse before another process.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_directory = root / "src"
            source_directory.mkdir()
            source = source_directory / "input.c"
            source.write_text("int f(void) { return 1; }\n", encoding="utf-8")
            profile = CompileProfile(
                source,
                sha256(source),
                root,
                root,
                ("clang", str(source), "-std=c11"),
                "c",
                "compile_commands",
                "partial",
                "fixture-profile",
            )
            helper = root / "helper"
            helper.write_bytes(b"fixture-helper")
            receipt = root / "receipt.json"
            receipt.write_text("{}", encoding="utf-8")
            frontend = ClangFrontend(helper, receipt, package_version="0.1.0")
            identity = ToolchainIdentity(
                root / "clang",
                "compiler-sha",
                "Clang fixture",
                root,
                "resource-sha",
                helper,
                sha256(helper),
                "source-sha",
                receipt,
                sha256(receipt),
                "0.1.0",
                "not_hashed",
            )
            process_result = subprocess.CompletedProcess(
                [str(helper)], 0, b"\xffnot-json", b"\xfeinvalid-stderr"
            )
            tool_failure = subprocess.CompletedProcess(
                [str(helper)],
                0,
                json.dumps(
                    {
                        "schema_version": "codira.clang-frontend-native/3",
                        "declarations": [],
                        "non_function_declarations": [],
                        "calls": [],
                        "diagnostics": [],
                        "dependency_paths": [],
                        "search_directories": [],
                        "includes": [],
                        "preprocessing": [],
                        "documentation_comments": [],
                        "capture_mode": "source_relevant",
                        "clang_version": "Clang fixture",
                        "target_triple": "x86_64-unknown-linux-gnu",
                        "sysroot": "/",
                        "tool_return_code": 7,
                        "capture_projection": {},
                    }
                ).encode(),
                b"frontend parse failed",
            )
            with (
                patch(
                    "codira_clang_frontend.frontend.subprocess.run",
                    side_effect=(process_result, tool_failure),
                ) as run,
                patch.object(
                    frontend, "toolchain_fingerprint", return_value="input-fingerprint"
                ),
                patch.object(
                    frontend, "_load_toolchain_identity", return_value=identity
                ),
            ):
                overlap = frontend.analyze(
                    profile,
                    attempt_dir=source_directory / "attempts",
                    attempt_id="overlapping-output",
                )
                self.assertEqual(overlap.status, "held")
                self.assertTrue(
                    overlap.reasons[0].startswith(
                        "attempt_directory_overlaps_include_root:"
                    )
                )
                self.assertFalse((source_directory / "attempts").exists())
                result = frontend.analyze(
                    profile,
                    attempt_dir=root / "attempts",
                    attempt_id="raw-bytes",
                )
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.reasons, ("invalid_libtooling_json",))
                assert result.stdout_path is not None
                assert result.stderr_path is not None
                self.assertEqual(result.stdout_path.read_bytes(), b"\xffnot-json")
                self.assertEqual(result.stderr_path.read_bytes(), b"\xfeinvalid-stderr")
                with self.assertRaises(FileExistsError):
                    frontend.analyze(
                        profile,
                        attempt_dir=root / "attempts",
                        attempt_id="raw-bytes",
                    )
                self.assertEqual(run.call_count, 1)
                failed = frontend.analyze(
                    profile,
                    attempt_dir=root / "attempts",
                    attempt_id="nonzero-tool-result",
                )
                self.assertEqual(failed.status, "failed")
                self.assertEqual(failed.reasons, ("clang_tool_return_code:7",))
                assert failed.stderr_path is not None
                self.assertEqual(
                    failed.stderr_path.read_bytes(), b"frontend parse failed"
                )
                self.assertEqual(run.call_count, 2)

    def test_membership_follows_symlinked_child_directories(self) -> None:
        """A new candidate header under a symlink target changes membership.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            search = root / "search"
            target = root / "headers"
            search.mkdir()
            target.mkdir()
            (target / "existing.h").write_text("#pragma once\n", encoding="utf-8")
            (search / "linked").symlink_to(target, target_is_directory=True)
            before = directory_membership_sha256(search)
            (target / "new-shadow.h").write_text("#define VALUE 2\n", encoding="utf-8")
            after = directory_membership_sha256(search)
            self.assertNotEqual(before, after)

    def test_stale_profile_fingerprint_observes_changed_dependency(self) -> None:
        """A manifest dependency mutation changes the no-Clang fallback key.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.cpp"
            source.write_text("int main() { return 0; }\n", encoding="utf-8")
            dependency = root / "header.h"
            dependency.write_text("#define VALUE 1\n", encoding="utf-8")
            search = root / "include"
            search.mkdir()
            (search / "header.h").write_text("#define VALUE 1\n", encoding="utf-8")
            helper = root / "helper"
            helper.write_bytes(b"helper-one")
            compiler = root / "clang"
            compiler.write_bytes(b"compiler-one")
            resource_probe = root / "stddef.h"
            resource_probe.write_bytes(b"resource-one")
            receipt = root / "build.json"
            receipt.write_text(
                json.dumps(
                    {
                        "compiler_path": str(compiler),
                        "helper_path": str(helper),
                        "resource_probe": str(resource_probe),
                    }
                ),
                encoding="utf-8",
            )
            profile_path = root / "profiles.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "schema_version": "codira.clang-frontend-profile/1",
                        "profiles": [
                            {
                                "source_path": str(source),
                                "source_sha256": sha256(source),
                                "dependencies": [
                                    {
                                        "path": str(dependency),
                                        "sha256": sha256(dependency),
                                    }
                                ],
                                "include_directories": [
                                    {
                                        "path": str(search),
                                        "membership_sha256": directory_membership_sha256(
                                            search
                                        ),
                                        "order": 0,
                                        "kind": "directory",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            first = captured_profile_fingerprint(
                profile_path,
                source,
                sha256(source),
                helper_path=helper,
                build_receipt_path=receipt,
            )
            (search / "new-shadow.h").write_text("#define VALUE 2\n", encoding="utf-8")
            shadow_changed = captured_profile_fingerprint(
                profile_path,
                source,
                sha256(source),
                helper_path=helper,
                build_receipt_path=receipt,
            )
            self.assertNotEqual(first, shadow_changed)
            dependency.write_text("#define VALUE 3\n", encoding="utf-8")
            second = captured_profile_fingerprint(
                profile_path,
                source,
                sha256(source),
                helper_path=helper,
                build_receipt_path=receipt,
            )
            self.assertNotEqual(shadow_changed, second)

    def test_calls_attach_to_definition_after_prototype(self) -> None:
        """A prior prototype cannot consume calls owned by its definition.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        declaration = {
            "identity": {"usr": "c:@F@f", "kind": "function", "provenance": "written"},
            "name": "f",
            "qualified_name": "f",
            "decl_kind": "function",
            "native_decl_kind": "FunctionDecl",
            "signature": "int f(void)",
            "function_type": "int (void)",
            "parameters": [],
            "has_prototype": True,
            "is_definition": False,
        }
        definition = dict(declaration, is_definition=True)
        call = {
            "caller_usr": "c:@F@f",
            "caller_name": "f",
            "caller_qualified_name": "f",
            "origin": "written",
            "callee": {"usr": "c:@F@g", "name": "g", "qualified_name": "g"},
        }
        _, callables, unowned = _decode_entities(
            {
                "declarations": [declaration, definition],
                "non_function_declarations": [],
                "calls": [call],
            }
        )
        self.assertEqual(callables[0].calls, ())
        self.assertEqual(callables[0].kind, "function")
        self.assertEqual(callables[0].decl_kind, "FunctionDecl")
        self.assertEqual(tuple(item.target for item in callables[1].calls), ("g",))
        self.assertEqual(unowned, ())

    def test_calls_without_a_matching_definition_are_unowned(self) -> None:
        """Calls for omitted declarations remain visible as unowned records.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        call = {
            "caller_usr": "c:@F@external",
            "caller_name": "external",
            "caller_qualified_name": "external",
            "origin": "written",
            "target_text": "callee",
        }
        _, callables, unowned = _decode_entities(
            {"declarations": [], "non_function_declarations": [], "calls": [call]}
        )
        self.assertEqual(callables, ())
        self.assertEqual(tuple(item.target for item in unowned), ("callee",))

    def test_template_instantiation_provenance_uses_native_semantic_kind(self) -> None:
        """A spelled instantiation does not become a source-written callable.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        _, callables, _ = _decode_entities(
            {
                "declarations": [
                    {
                        "identity": {
                            "usr": "c:@FT@template@I#I#",
                            "kind": "template_instantiation",
                            "provenance": "source_written",
                        },
                        "decl_kind": "function",
                        "native_decl_kind": "FunctionDecl",
                        "name": "identity",
                        "qualified_name": "identity<int>",
                        "signature": "int identity(int)",
                        "function_type": "int (int)",
                        "parameters": [],
                        "has_prototype": True,
                        "is_definition": True,
                    }
                ],
                "non_function_declarations": [],
                "calls": [],
            }
        )
        self.assertEqual(len(callables), 1)
        self.assertEqual(callables[0].kind, "function")
        self.assertEqual(callables[0].provenance, "template_instantiation")

    def test_native_protocol_requires_version_fields_and_successful_tool_code(
        self,
    ) -> None:
        """Reject empty JSON and require a typed tool status for caller checks.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        self.assertEqual(_validate_response({}), "unsupported_native_protocol_version")
        response: dict[str, object] = {
            "schema_version": "codira.clang-frontend-native/3",
            "declarations": [],
            "non_function_declarations": [],
            "calls": [],
            "diagnostics": [],
            "dependency_paths": [],
            "search_directories": [],
            "includes": [],
            "preprocessing": [],
            "documentation_comments": [],
            "capture_mode": "source_relevant",
            "clang_version": "Clang fixture",
            "target_triple": "x86_64-unknown-linux-gnu",
            "sysroot": "/",
            "tool_return_code": 0,
            "capture_projection": {},
        }
        self.assertIsNone(_validate_response(response))
        response["schema_version"] = "codira.clang-frontend-native/4"
        response["translation_unit_file"] = "/tmp/owner.cpp"
        response["projection_file"] = "/tmp/api.hpp"
        self.assertIsNone(_validate_response(response))
        response["tool_return_code"] = 1
        self.assertIsNone(_validate_response(response))
        response["calls"] = ["malformed-record"]
        self.assertEqual(
            _validate_response(response), "invalid_native_protocol_record_shape"
        )

    def test_native_protocol_v5_decodes_alias_and_body_distinctions(self) -> None:
        """Retain exact alias, linkage, and per-declaration body observations.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        response: dict[str, object] = {
            "schema_version": "codira.clang-frontend-native/5",
            "translation_unit_file": "/repo/main.cpp",
            "projection_file": None,
            "declarations": [
                {
                    "identity": {
                        "usr": "c:@N@ns@F@alias#",
                        "kind": "written",
                        "provenance": "macro_argument",
                    },
                    "decl_kind": "function",
                    "native_decl_kind": "FunctionDecl",
                    "name": "alias",
                    "qualified_name": "ns::alias",
                    "signature": "int ns::alias()",
                    "signature_kind": "derived_display_only",
                    "function_type": "int ()",
                    "is_definition": True,
                    "has_body": False,
                    "linkage_kind": "external",
                    "linker_symbol": "_ZN2ns5aliasEv",
                    "explicit_linkage_label": None,
                    "linkage_label_inherited": None,
                    "alias_target_symbol": "target_symbol",
                    "alias_target_usr": "c:@N@ns@F@target#",
                    "alias_binding_status": "resolved",
                    "parameters": [],
                    "location": None,
                    "range": None,
                }
            ],
            "non_function_declarations": [],
            "calls": [],
            "diagnostics": [],
            "dependency_paths": [],
            "search_directories": [],
            "includes": [],
            "preprocessing": [],
            "documentation_comments": [],
            "capture_mode": "source_relevant",
            "clang_version": "Clang fixture",
            "target_triple": "x86_64-unknown-linux-gnu",
            "sysroot": "/",
            "tool_return_code": 0,
            "capture_projection": {},
        }
        self.assertIsNone(_validate_response(response))
        _, callables, _ = _decode_entities(response)
        self.assertEqual(len(callables), 1)
        alias = callables[0]
        self.assertTrue(alias.is_definition)
        self.assertFalse(alias.has_body)
        self.assertEqual(alias.linkage_kind, "external")
        self.assertEqual(alias.alias_target_symbol, "target_symbol")
        self.assertEqual(alias.alias_target_usr, "c:@N@ns@F@target#")
        self.assertEqual(alias.alias_binding_status, "resolved")
        self.assertEqual(alias.signature_kind, "derived_display_only")
        row = cast(
            "dict[str, object]", cast("list[object]", response["declarations"])[0]
        )
        row["alias_target_usr"] = None
        self.assertEqual(
            _validate_response(response), "inconsistent_native_protocol_alias_facts"
        )
        row["alias_target_usr"] = "c:@N@ns@F@target#"
        row["alias_binding_status"] = "not_alias"
        self.assertEqual(
            _validate_response(response), "inconsistent_native_protocol_alias_facts"
        )

    def test_v5_macro_expansion_is_legacy_unlinked_and_cannot_claim_v6_link(
        self,
    ) -> None:
        """Keep v5 parsing available while making missing links explicit.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        event = macro_expansion_event()
        event.pop("macro_definition_link")
        response = native_response("codira.clang-frontend-native/5", [event])
        self.assertIsNone(_validate_response(response))
        decoded = _decode_preprocessing(
            response["preprocessing"],
            protocol_version="codira.clang-frontend-native/5",
        )
        self.assertEqual(len(decoded), 1)
        self.assertIsNone(decoded[0].macro_definition_link)
        self.assertEqual(decoded[0].macro_definition_link_status, "legacy_protocol")
        self.assertEqual(
            decoded[0].macro_definition_link_reason,
            "native_protocol_has_no_macro_definition_link",
        )

        event["macro_definition_link"] = macro_expansion_event()[
            "macro_definition_link"
        ]
        response = native_response("codira.clang-frontend-native/5", [event])
        self.assertEqual(
            _validate_response(response),
            "invalid_native_protocol_macro_definition_link_version",
        )

    def test_v6_macro_expansion_requires_and_decodes_resolved_definition_link(
        self,
    ) -> None:
        """Validate and type the exact definition selected by a v6 helper.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        event = macro_expansion_event()
        response = native_response("codira.clang-frontend-native/6", [event])
        self.assertIsNone(_validate_response(response))
        decoded = _decode_preprocessing(
            response["preprocessing"],
            protocol_version="codira.clang-frontend-native/6",
        )
        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0].macro_definition_link_status, "resolved")
        self.assertIsInstance(
            decoded[0].macro_definition_link, FrontendMacroDefinitionLink
        )
        assert decoded[0].macro_definition_link is not None
        spelling = decoded[0].macro_definition_link.location.spelling
        assert spelling is not None
        self.assertEqual(decoded[0].macro_definition_link.name, "SELECT")
        self.assertEqual(decoded[0].macro_definition_link.name_token, "SELECT")
        self.assertEqual(spelling.path, "/repo/include/macros.h")
        self.assertEqual(spelling.offset, 277)
        self.assertTrue(decoded[0].macro_definition_link.function_like)

        event.pop("macro_definition_link")
        response = native_response("codira.clang-frontend-native/6", [event])
        self.assertEqual(
            _validate_response(response),
            "invalid_native_protocol_macro_definition_link_shape",
        )

    def test_v6_macro_definition_link_unavailable_is_explicit_and_bounded(
        self,
    ) -> None:
        """Accept a known unavailable reason without fabricating a target.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        event = macro_expansion_event()
        event["macro_definition_link"] = {
            "status": "unavailable",
            "reason": "definition_record_missing",
        }
        response = native_response("codira.clang-frontend-native/6", [event])
        self.assertIsNone(_validate_response(response))
        decoded = _decode_preprocessing(
            response["preprocessing"],
            protocol_version="codira.clang-frontend-native/6",
        )
        self.assertIsNone(decoded[0].macro_definition_link)
        self.assertEqual(decoded[0].macro_definition_link_status, "unavailable")
        self.assertEqual(
            decoded[0].macro_definition_link_reason, "definition_record_missing"
        )

        event["macro_definition_link"] = {
            "status": "unavailable",
            "reason": "guessed_by_name",
        }
        response = native_response("codira.clang-frontend-native/6", [event])
        self.assertEqual(
            _validate_response(response),
            "invalid_native_protocol_macro_definition_link_unavailable",
        )

    def test_v6_macro_definition_link_rejects_name_and_physical_location_mismatch(
        self,
    ) -> None:
        """Reject a target with a different name or no physical byte anchor.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        event = macro_expansion_event()
        link = cast("dict[str, object]", event["macro_definition_link"])
        link["name"] = "OTHER"
        response = native_response("codira.clang-frontend-native/6", [event])
        self.assertEqual(
            _validate_response(response),
            "invalid_native_protocol_macro_definition_link_location",
        )

        event = macro_expansion_event()
        link = cast("dict[str, object]", event["macro_definition_link"])
        location = cast("dict[str, object]", link["location"])
        spelling = cast("dict[str, object]", location["spelling"])
        spelling["offset"] = None
        response = native_response("codira.clang-frontend-native/6", [event])
        self.assertEqual(
            _validate_response(response),
            "invalid_native_protocol_macro_definition_link_location",
        )

    def test_header_projection_uses_only_captured_dependency_owners(self) -> None:
        """Resolve one owner and hold ambiguous captured dependency contexts.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            header = root / "generated" / "api.hpp"
            header.parent.mkdir()
            header.write_text("int value();\n", encoding="utf-8")
            header_digest = sha256(header)
            translation_units = [root / "one.cpp", root / "two.cpp"]
            profiles: list[CompileProfile] = []
            for index, translation_unit in enumerate(translation_units):
                translation_unit.write_text("#include <api.hpp>\n", encoding="utf-8")
                profiles.append(
                    CompileProfile(
                        source_path=translation_unit,
                        source_sha256=sha256(translation_unit),
                        working_directory=root,
                        repository_root=root,
                        argv=("clang++", str(translation_unit)),
                        language="cpp",
                        origin="captured_argv",
                        status="complete",
                        identity=f"profile-{index}",
                        dependencies=(DependencyInput(header, header_digest),),
                        include_search_complete=True,
                    )
                )

            unique = resolve_header_projection(header, (profiles[0],))
            self.assertEqual(unique.status, "ready")
            self.assertIsNotNone(unique.request)
            assert unique.request is not None
            self.assertEqual(unique.request.owner_profile.identity, "profile-0")
            self.assertEqual(unique.request.requested_header_sha256, header_digest)

            ambiguous = resolve_header_projection(header, tuple(profiles))
            self.assertEqual(ambiguous.status, "ambiguous_owner")
            self.assertEqual(
                ambiguous.candidate_profile_identities, ("profile-0", "profile-1")
            )
            selected = resolve_header_projection(
                header, tuple(profiles), selected_owner_identity="profile-1"
            )
            self.assertEqual(selected.status, "ready")
            self.assertIsNotNone(selected.request)
            assert selected.request is not None
            self.assertEqual(selected.request.owner_profile.identity, "profile-1")
            missing = resolve_header_projection(root / "generated.h", tuple(profiles))
            self.assertEqual(missing.status, "missing_header")

    def test_header_projection_holds_stale_dependency_bytes(self) -> None:
        """Reject captured owners whose dependency digest no longer matches.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            header = root / "api.h"
            source = root / "owner.c"
            header.write_text("int api(void);\n", encoding="utf-8")
            source.write_text('#include "api.h"\n', encoding="utf-8")
            captured_digest = sha256(header)
            header.write_text("int api(void); /* changed */\n", encoding="utf-8")
            profile = CompileProfile(
                source_path=source,
                source_sha256=sha256(source),
                working_directory=root,
                repository_root=root,
                argv=("clang", str(source)),
                language="c",
                origin="captured_argv",
                status="complete",
                identity="owner-profile",
                dependencies=(DependencyInput(header, captured_digest),),
                include_search_complete=True,
            )
            resolution = resolve_header_projection(header, (profile,))
            self.assertEqual(resolution.status, "stale_header")
            self.assertIsNone(resolution.request)

    def test_native_protocol_requires_compiler_context(self) -> None:
        """Reject protocol responses without actual Clang target/sysroot fields.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        response: dict[str, object] = {
            "schema_version": "codira.clang-frontend-native/3",
            "declarations": [],
            "non_function_declarations": [],
            "calls": [],
            "diagnostics": [],
            "dependency_paths": [],
            "search_directories": [],
            "includes": [],
            "preprocessing": [],
            "documentation_comments": [],
            "capture_mode": "source_relevant",
            "clang_version": "Clang fixture",
            "tool_return_code": 0,
            "capture_projection": {},
            "target_triple": "x86_64-unknown-linux-gnu",
        }
        self.assertEqual(
            _validate_response(response),
            "invalid_native_protocol_compilation_context",
        )
        response["sysroot"] = "/"
        self.assertIsNone(_validate_response(response))
        response["target_triple"] = ""
        self.assertEqual(
            _validate_response(response),
            "invalid_native_protocol_compilation_context",
        )

    def test_compilation_context_resolves_sysroot_from_captured_cwd(self) -> None:
        """Resolve only the actual native sysroot value against compile cwd.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        with tempfile.TemporaryDirectory() as temp:
            cwd = Path(temp)
            context = _decode_compilation_context(
                {"target_triple": "arm64-unknown-linux-gnu", "sysroot": "sdk"},
                cwd,
            )
        self.assertEqual(
            context,
            CompilationContext(
                "arm64-unknown-linux-gnu", "sdk", (cwd / "sdk").resolve()
            ),
        )

    def test_analysis_holds_when_native_context_differs_from_profile(self) -> None:
        """Do not parse under a target/sysroot unlike the prepared profile.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_dir = root / "src"
            source_dir.mkdir()
            source = source_dir / "unit.c"
            source.write_text("int unit(void) { return 0; }\n", encoding="utf-8")
            helper = root / "helper"
            helper.write_bytes(b"helper")
            receipt = root / "receipt.json"
            receipt.write_text("{}", encoding="utf-8")
            profile = CompileProfile(
                source,
                sha256(source),
                root,
                root,
                ("clang", str(source)),
                "c",
                "captured_argv",
                "complete",
                "context-bound-profile",
                compilation_context=CompilationContext("x86_64-test", "/", Path("/")),
            )
            identity = ToolchainIdentity(
                root / "clang",
                "compiler-sha",
                "Clang fixture",
                root,
                "resource-sha",
                helper,
                sha256(helper),
                "source-sha",
                receipt,
                sha256(receipt),
                "0.1.0",
                "not_hashed",
            )
            response = {
                "schema_version": "codira.clang-frontend-native/3",
                "declarations": [],
                "non_function_declarations": [],
                "calls": [],
                "diagnostics": [],
                "dependency_paths": [],
                "search_directories": [],
                "includes": [],
                "preprocessing": [],
                "documentation_comments": [],
                "capture_mode": "source_relevant",
                "clang_version": "Clang fixture",
                "target_triple": "arm64-test",
                "sysroot": "/",
                "tool_return_code": 0,
                "capture_projection": {},
            }
            completed = subprocess.CompletedProcess(
                [str(helper)], 0, json.dumps(response).encode(), b""
            )
            frontend = ClangFrontend(helper, receipt, package_version="0.1.0")
            with (
                patch(
                    "codira_clang_frontend.frontend.subprocess.run",
                    return_value=completed,
                ),
                patch.object(
                    frontend, "toolchain_fingerprint", return_value="fingerprint"
                ),
                patch.object(
                    frontend, "_load_toolchain_identity", return_value=identity
                ),
            ):
                result = frontend.analyze(
                    profile,
                    attempt_dir=root / "attempts",
                    attempt_id="context-mismatch",
                )
        self.assertEqual(result.status, "held")
        self.assertEqual(result.reasons, ("clang_compilation_context_changed",))
        self.assertIsNotNone(result.compilation_context)
        assert result.compilation_context is not None
        self.assertEqual(result.compilation_context.target_triple, "arm64-test")

    def test_prepared_profile_round_trip_preserves_context_and_fingerprint(
        self,
    ) -> None:
        """Retain Clang context through prepared-profile serialization.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "unit.c"
            source.write_text("int unit(void) { return 0; }\n", encoding="utf-8")
            evidence = root / "original-command.json"
            evidence.write_text('{"argv":["clang"]}\n', encoding="utf-8")
            include = root / "include"
            include.mkdir()
            header = include / "unit.h"
            header.write_text("#define UNIT 1\n", encoding="utf-8")
            context = CompilationContext("x86_64-test-linux", "/", Path("/"))
            dependencies = (
                DependencyInput(source, sha256(source)),
                DependencyInput(header, sha256(header)),
            )
            include_directory = IncludeDirectoryInput(
                include, directory_membership_sha256(include), order=0
            )
            profile = from_captured_argv(
                source,
                root,
                root,
                ("clang", str(source), "-c"),
                "c",
                status="complete",
                evidence_path=evidence,
                dependencies=dependencies,
                include_directories=(include_directory,),
                include_search_complete=True,
                compilation_context=context,
            )
            prepared = write_prepared_profile(
                profile,
                dependencies,
                (include_directory,),
                (),
                "controlled_no_ambient",
                context,
                root / "prepared" / "profile.json",
            )
            loaded = from_captured_profile_json(
                root / "prepared" / "profile.json",
                source,
                root,
                sha256(source),
            )
            helper = root / "helper"
            helper.write_bytes(b"helper")
            receipt = root / "receipt.json"
            receipt.write_text("{}", encoding="utf-8")
            frontend = ClangFrontend(helper, receipt, package_version="0.1.0")
            identity = ToolchainIdentity(
                root / "clang",
                "compiler-sha",
                "Clang fixture",
                root,
                "resource-sha",
                helper,
                sha256(helper),
                "source-sha",
                receipt,
                sha256(receipt),
                "0.1.0",
                "not_hashed",
            )
            with patch.object(
                frontend, "_load_toolchain_identity", return_value=identity
            ):
                original_fingerprint = frontend_profile_fingerprint(frontend, profile)
                prepared_fingerprint = frontend_profile_fingerprint(frontend, prepared)
                loaded_fingerprint = frontend_profile_fingerprint(frontend, loaded)
        self.assertEqual(prepared.compilation_context, context)
        self.assertEqual(loaded.compilation_context, context)
        self.assertEqual(original_fingerprint, prepared_fingerprint)
        self.assertEqual(prepared_fingerprint, loaded_fingerprint)

    def test_captured_owner_profiles_filter_by_header_and_reject_stale_sources(
        self,
    ) -> None:
        """Preserve current context variants for one header owner source.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "unit.cpp"
            source.write_text('#include "unit.hpp"\n', encoding="utf-8")
            include = root / "include"
            include.mkdir()
            header = include / "unit.hpp"
            header.write_text("int function(int value);\n", encoding="utf-8")
            evidence = root / "capture.json"
            evidence.write_text("{}", encoding="utf-8")
            context = CompilationContext("x86_64-test-linux", "/", Path("/"))
            dependencies = (
                DependencyInput(source, sha256(source)),
                DependencyInput(header, sha256(header)),
            )
            include_directory = IncludeDirectoryInput(
                include, directory_membership_sha256(include), order=0
            )
            prepared_profile_paths: list[Path] = []
            for index in (1, 2):
                profile = from_captured_argv(
                    source,
                    root,
                    root,
                    ("clang++", f"-DPROFILE={index}", str(source)),
                    "cpp",
                    profile_id=f"captured-{index}",
                    status="complete",
                    evidence_path=evidence,
                    dependencies=dependencies,
                    include_directories=(include_directory,),
                    include_search_complete=True,
                    compilation_context=context,
                )
                output = root / f"profile-{index}.json"
                write_prepared_profile(
                    profile,
                    dependencies,
                    (include_directory,),
                    (),
                    "controlled_no_ambient",
                    context,
                    output,
                )
                prepared_profile_paths.append(output)
            collection = _write_captured_profiles_manifest(prepared_profile_paths, root)
            combined = json.loads(collection.read_text(encoding="utf-8"))
            records = combined["profiles"]
            records.append(
                {
                    "source_path": str(root / "missing-unrelated.cpp"),
                    "source_sha256": "stale-source-is-filtered-before-read",
                    "dependencies": [{"path": str(root / "other.hpp")}],
                }
            )
            collection.write_text(
                json.dumps({"schema_version": PROFILE_SCHEMA, "profiles": records}),
                encoding="utf-8",
            )

            loaded = from_captured_profiles_json(
                collection,
                root,
                requested_dependency_path=header,
            )
            self.assertEqual(len(loaded), 2)
            self.assertNotEqual(loaded[0].identity, loaded[1].identity)
            self.assertTrue(all(profile.source_path == source for profile in loaded))

            source.write_text("int changed;\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "current translation unit digest"):
                from_captured_profiles_json(
                    collection,
                    root,
                    {source: dependencies[0].sha256},
                    requested_dependency_path=header,
                )

    def test_relative_native_dependencies_resolve_against_compile_cwd(self) -> None:
        """Hash relative Clang paths from the captured profile directory.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "src" / "input.c"
            include = root / "include"
            include.mkdir()
            source.parent.mkdir()
            source.write_text("#include <value.h>\n", encoding="utf-8")
            header = include / "value.h"
            header.write_text("#define VALUE 1\n", encoding="utf-8")
            (root / "search").mkdir()
            closure = _dependency_closure(
                {
                    "dependency_paths": ["include/value.h"],
                    "search_directories": [
                        {
                            "path": "include",
                            "order": 0,
                            "is_framework": False,
                            "is_header_map": False,
                        }
                    ],
                },
                source,
                root,
            )
            self.assertEqual(closure.status, "complete")
            self.assertEqual(
                {item.path for item in closure.files},
                {source.resolve(), header.resolve()},
            )
            self.assertTrue(closure.search_directories_complete)
            self.assertIn(
                source.parent.resolve(),
                {item.path for item in closure.search_directories},
            )

    @unittest.skipUnless(
        os.environ.get("CODIRA_CLANG_FRONTEND_NATIVE_HELPER"),
        "set CODIRA_CLANG_FRONTEND_NATIVE_HELPER to run native helper controls",
    )
    def test_native_macro_links_use_physical_file_path_under_line_directive(
        self,
    ) -> None:
        """Bind source-authored macro links to physical bytes under #line.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Test assertion result.
        """
        helper = Path(os.environ["CODIRA_CLANG_FRONTEND_NATIVE_HELPER"]).resolve(
            strict=True
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "input.c"
            source_lines = (
                b"#define REPICK 1",
                b"int first = REPICK;",
                b"#undef REPICK",
                b'#line 900 "logical/remapped.c"',
                b"#if __LINE__ == 900",
                b"#define LINE_CONTROL 1",
                b"#endif",
                b"#define REPICK 2",
                b"int second = REPICK;",
                b'#if __has_include("missing-native-link-control.h")',
                b"int unexpected_header = 1;",
                b"#endif",
            )
            for newline in (b"\r", b"\r\n"):
                with self.subTest(newline=newline):
                    source.write_bytes(newline.join(source_lines) + newline)
                    request = {
                        "file": str(source),
                        "directory": str(root),
                        "repository_root": str(root),
                        "argv": ["-x", "c", "-std=c11"],
                        "capture_mode": "source_relevant",
                    }
                    result = subprocess.run(
                        [str(helper)],
                        input=json.dumps(request).encode("utf-8"),
                        cwd=root,
                        capture_output=True,
                        check=False,
                        shell=False,
                    )
                    self.assertEqual(
                        result.returncode, 0, result.stderr.decode("utf-8")
                    )
                    response = json.loads(result.stdout)
                    self.assertEqual(
                        _validate_response(response),
                        None,
                        "native response must satisfy the v6 protocol",
                    )
                    self.assertEqual(
                        response["schema_version"], "codira.clang-frontend-native/6"
                    )
                    self.assertTrue(
                        any(
                            event.get("kind") == "if"
                            and event.get("result") == "true"
                            and "900" in str(event.get("condition", ""))
                            for event in response["preprocessing"]
                        ),
                        "the native source must activate its #line remapping",
                    )
                    events = _decode_preprocessing(
                        response["preprocessing"],
                        protocol_version=response["schema_version"],
                    )
                    macro_expansions = [
                        event for event in events if event.kind == "macro_expansion"
                    ]
                    repick_events = [
                        event for event in macro_expansions if event.name == "REPICK"
                    ]
                    self.assertEqual(len(repick_events), 2)
                    physical_source = source.read_bytes()
                    definition_offsets: set[int] = set()
                    for event in repick_events:
                        link = event.macro_definition_link
                        self.assertEqual(event.macro_definition_link_status, "resolved")
                        self.assertIsNotNone(link)
                        assert link is not None
                        self.assertEqual(link.name, "REPICK")
                        self.assertEqual(link.name_token, "REPICK")
                        self.assertFalse(link.function_like)
                        self.assertFalse(link.location.is_macro)
                        definition = link.location.spelling
                        self.assertIsNotNone(definition)
                        assert definition is not None
                        self.assertEqual(definition.path, str(source))
                        self.assertIsNotNone(definition.offset)
                        assert definition.offset is not None
                        source_prefix = physical_source[: definition.offset]
                        normalized_prefix = source_prefix.replace(
                            b"\r\n", b"\n"
                        ).replace(b"\r", b"\n")
                        physical_line = normalized_prefix.count(b"\n") + 1
                        self.assertEqual(definition.line, physical_line)
                        line_start = (
                            max(source_prefix.rfind(b"\n"), source_prefix.rfind(b"\r"))
                            + 1
                        )
                        self.assertEqual(
                            definition.column,
                            definition.offset - line_start + 1,
                        )
                        self.assertEqual(
                            physical_source[
                                definition.offset : definition.offset + len(b"REPICK")
                            ],
                            b"REPICK",
                        )
                        definition_offsets.add(definition.offset)
                    self.assertEqual(len(definition_offsets), 2)
                    self.assertTrue(
                        any(
                            event.name == "__has_include"
                            and event.macro_definition_link_status == "unavailable"
                            and event.macro_definition_link_reason
                            == "definition_record_missing"
                            for event in macro_expansions
                        ),
                        "compiler builtin expansion should retain explicit unavailable state",
                    )


if __name__ == "__main__":
    unittest.main()
