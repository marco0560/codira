"""In-memory backend relation-resolution helpers for contract tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from codira.prefix import normalize_prefix, path_has_prefix

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from memory_backend_models import (
        CallableRefRow,
        CallEdgeRow,
        _MemoryRelation,
        _MemoryState,
    )


class _MemoryRelationStateOwner(Protocol):
    """Backend state surface required by relation queries."""

    def _conn_state(self, root: Path, conn: object | None) -> _MemoryState:
        """Return the state selected for a backend operation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None
            Optional connection.

        Returns
        -------
        _MemoryState
            Selected mutable backend state.
        """


class MemoryRelationBackendMixin:
    """Resolve and query in-memory call and callable-reference relations."""

    def _conn_state(self, root: Path, conn: object | None) -> _MemoryState:
        """Return the state selected for a backend operation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None
            Optional connection.

        Returns
        -------
        _MemoryState
            Selected mutable backend state.

        Raises
        ------
        NotImplementedError
            Always; concrete backend classes provide the state-selection seam.
        """
        del root, conn
        raise NotImplementedError

    def _module_functions(self, state: _MemoryState) -> dict[str, set[str]]:
        """
        Return top-level functions keyed by module name.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.

        Returns
        -------
        dict[str, set[str]]
            Top-level function names keyed by module name.
        """
        module_functions: dict[str, set[str]] = {}
        for function in state.functions:
            if function.class_name is None:
                module_functions.setdefault(function.module_name, set()).add(
                    function.name
                )
        return module_functions

    def _class_methods(self, state: _MemoryState) -> dict[tuple[str, str], set[str]]:
        """
        Return method names keyed by ``(module, class)``.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.

        Returns
        -------
        dict[tuple[str, str], set[str]]
            Method names keyed by module and class name.
        """
        class_methods: dict[tuple[str, str], set[str]] = {}
        for function in state.functions:
            if function.class_name is not None:
                class_methods.setdefault(
                    (function.module_name, function.class_name),
                    set(),
                ).add(function.name)
        return class_methods

    def _import_aliases(self, state: _MemoryState) -> dict[str, dict[str, str]]:
        """
        Return import aliases keyed by owning module.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.

        Returns
        -------
        dict[str, dict[str, str]]
            Import alias maps keyed by owning module.
        """
        aliases_by_module: dict[str, dict[str, str]] = {}
        for imp in sorted(
            state.imports,
            key=lambda item: (
                item.module_name,
                item.lineno,
                item.name,
                item.alias or "",
            ),
        ):
            if imp.kind != "import":
                continue
            aliases = aliases_by_module.setdefault(imp.module_name, {})
            local_name = imp.alias if imp.alias is not None else imp.name.split(".")[-1]
            if "." in imp.name and imp.alias is None and "." not in local_name:
                aliases[imp.name] = imp.name
            aliases[local_name] = imp.name
        return aliases_by_module

    def _resolve_relation(
        self,
        state: _MemoryState,
        record: _MemoryRelation,
    ) -> tuple[str | None, str | None, int]:
        """
        Resolve one raw call-style relation conservatively.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.
        record : _MemoryRelation
            Raw relation record to resolve.

        Returns
        -------
        tuple[str | None, str | None, int]
            Target module, target logical name, and certainty flag.
        """
        module_functions = self._module_functions(state)
        class_methods = self._class_methods(state)
        import_aliases = self._import_aliases(state).get(record.owner_module, {})
        candidates: set[tuple[str, str]] = set()

        if record.kind == "name" and record.target:
            imported = import_aliases.get(record.target)
            if imported is not None and "." in imported:
                imported_module, imported_name = imported.rsplit(".", 1)
                if imported_name in module_functions.get(imported_module, set()):
                    candidates.add((imported_module, imported_name))
            if record.target in module_functions.get(record.owner_module, set()):
                candidates.add((record.owner_module, record.target))

        if record.kind == "attribute" and record.target:
            caller_class = (
                record.owner_name.rsplit(".", 1)[0]
                if "." in record.owner_name
                else None
            )
            if caller_class is not None and record.base in {"self", "cls"}:
                methods = class_methods.get((record.owner_module, caller_class), set())
                if record.target in methods:
                    candidates.add(
                        (record.owner_module, f"{caller_class}.{record.target}")
                    )
            methods = class_methods.get((record.owner_module, record.base), set())
            if record.target in methods:
                candidates.add((record.owner_module, f"{record.base}.{record.target}"))
            imported = import_aliases.get(record.base)
            if imported is not None and record.target in module_functions.get(
                imported,
                set(),
            ):
                candidates.add((imported, record.target))

        if len(candidates) == 1:
            module_name, name = next(iter(candidates))
            return (module_name, name, 1)
        return (None, None, 0)

    def _derived_relations(
        self,
        state: _MemoryState,
        records: Sequence[_MemoryRelation],
        *,
        include_endpoint_ids: bool,
    ) -> list[CallEdgeRow] | list[CallableRefRow]:
        """
        Resolve raw relation records into public edge rows.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.
        records : collections.abc.Sequence[_MemoryRelation]
            Raw relation records to resolve.

        Returns
        -------
        list[codira.contracts.CallEdgeRow]
            Derived graph edge rows.
        """
        rows: set[CallEdgeRow] | set[CallableRefRow]
        if include_endpoint_ids:
            rows = cast(
                "set[CallEdgeRow]",
                {
                    (
                        record.owner_module,
                        record.owner_name,
                        None,
                        target_module,
                        target_name,
                        None,
                        None if resolved else record.external_target_kind,
                        None if resolved else record.external_target_name,
                        resolved,
                    )
                    for record in records
                    for target_module, target_name, resolved in (
                        self._resolve_relation(state, record),
                    )
                },
            )
        else:
            rows = cast(
                "set[CallableRefRow]",
                {
                    (
                        record.owner_module,
                        record.owner_name,
                        target_module,
                        target_name,
                        None if resolved else record.external_target_kind,
                        None if resolved else record.external_target_name,
                        resolved,
                    )
                    for record in records
                    for target_module, target_name, resolved in (
                        self._resolve_relation(state, record),
                    )
                },
            )
        return cast(
            "list[CallEdgeRow] | list[CallableRefRow]",
            sorted(rows, key=lambda row: tuple(str(value or "") for value in row)),
        )

    def _find_relations(
        self,
        root: Path,
        name: str,
        *,
        records_attr: str,
        module: str | None,
        incoming: bool,
        prefix: str | None,
        conn: object | None,
        stable_id: str | None = None,
    ) -> list[CallEdgeRow] | list[CallableRefRow]:
        """
        Find derived relation rows for calls or callable refs.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        name : str
            Owner or target logical name to match.
        records_attr : str
            State attribute containing raw relation records.
        module : str | None
            Optional module filter.
        incoming : bool
            Whether to search incoming relations.
        prefix : str | None
            Optional repository-relative path prefix.
        conn : object | None
            Optional backend connection.
        stable_id : str | None, optional
            Optional exact caller or callee identity.

        Returns
        -------
        list[codira.contracts.CallEdgeRow]
            Matching derived relation rows.

        Raises
        ------
        TypeError
            If ``records_attr`` does not resolve to a relation list.
        """
        state = self._conn_state(root, conn)
        normalized_prefix = normalize_prefix(root, prefix)
        records = getattr(state, records_attr)
        if not isinstance(records, list):
            msg = f"Unknown relation collection: {records_attr}"
            raise TypeError(msg)
        include_endpoint_ids = records_attr == "call_records"
        if stable_id is not None and include_endpoint_ids:
            return []
        file_path_by_owner = {
            (record.owner_module, record.owner_name): state.files[record.file_id].path
            for record in records
        }
        rows = [
            row
            for row in self._derived_relations(
                state,
                records,
                include_endpoint_ids=include_endpoint_ids,
            )
            if path_has_prefix(file_path_by_owner[(row[0], row[1])], normalized_prefix)
            and (
                (
                    incoming
                    and row[4 if include_endpoint_ids else 3] == name
                    and (
                        module is None
                        or row[3 if include_endpoint_ids else 2] == module
                    )
                )
                or (
                    not incoming
                    and row[1] == name
                    and (module is None or row[0] == module)
                )
            )
        ]
        return cast(
            "list[CallEdgeRow] | list[CallableRefRow]",
            sorted(rows, key=lambda row: tuple(str(value or "") for value in row)),
        )
