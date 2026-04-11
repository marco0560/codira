"""Database schema constants for the codira SQLite store.

Responsibilities
----------------
- Maintain `SCHEMA_VERSION` for compatibility guards and upgrades.
- Provide canonical DDL statements for files, modules, classes, functions, imports, docstring issues, embeddings, and call edges.
- Keep schema expectations centralized for the indexer, storage, and query layers.

Design principles
-----------------
Schema definitions remain declarative, versioned, and stable so migration checks can run deterministically.

Architectural role
------------------
This module belongs to the **storage infrastructure layer** and anchors table definitions for all persistence actions.
"""

from __future__ import annotations

SCHEMA_VERSION = 11

DDL = [
    """
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        path TEXT UNIQUE NOT NULL,
        hash TEXT NOT NULL,
        mtime REAL NOT NULL,
        size INTEGER NOT NULL,
        analyzer_name TEXT NOT NULL,
        analyzer_version TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS index_runtime (
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
        backend_name TEXT NOT NULL,
        backend_version TEXT NOT NULL,
        coverage_complete INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS index_analyzers (
        name TEXT PRIMARY KEY,
        version TEXT NOT NULL,
        discovery_globs TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS modules (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        docstring TEXT,
        has_docstring INTEGER NOT NULL,
        FOREIGN KEY(file_id) REFERENCES files(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY,
        module_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        lineno INTEGER NOT NULL,
        end_lineno INTEGER,
        docstring TEXT,
        has_docstring INTEGER NOT NULL,
        FOREIGN KEY(module_id) REFERENCES modules(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS functions (
        id INTEGER PRIMARY KEY,
        module_id INTEGER NOT NULL,
        class_id INTEGER,
        name TEXT NOT NULL,
        lineno INTEGER NOT NULL,
        end_lineno INTEGER,
        signature TEXT,
        docstring TEXT,
        has_docstring INTEGER NOT NULL,
        is_method INTEGER NOT NULL,
        is_public INTEGER NOT NULL,
        FOREIGN KEY(module_id) REFERENCES modules(id),
        FOREIGN KEY(class_id) REFERENCES classes(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS imports (
        id INTEGER PRIMARY KEY,
        module_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        alias TEXT,
        kind TEXT NOT NULL,
        lineno INTEGER NOT NULL,
        FOREIGN KEY(module_id) REFERENCES modules(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS docstring_issues (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        function_id INTEGER,
        class_id INTEGER,
        module_id INTEGER,
        issue_type TEXT NOT NULL,
        message TEXT NOT NULL,
        FOREIGN KEY(file_id) REFERENCES files(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS symbol_index (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        stable_id TEXT NOT NULL,
        type TEXT NOT NULL,
        module_name TEXT NOT NULL,
        file_id INTEGER NOT NULL,
        lineno INTEGER NOT NULL
        ,
        FOREIGN KEY(file_id) REFERENCES files(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS call_edges (
        caller_file_id INTEGER NOT NULL,
        caller_module TEXT NOT NULL,
        caller_name TEXT NOT NULL,
        callee_module TEXT,
        callee_name TEXT,
        resolved INTEGER NOT NULL,
        PRIMARY KEY (
            caller_file_id,
            caller_module,
            caller_name,
            callee_module,
            callee_name
        ),
        FOREIGN KEY(caller_file_id) REFERENCES files(id)
    );
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_call_edges_identity
    ON call_edges(
        caller_file_id,
        caller_module,
        caller_name,
        COALESCE(callee_module, ''),
        COALESCE(callee_name, '')
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_call_edges_caller
    ON call_edges(caller_file_id, caller_module, caller_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_call_edges_callee
    ON call_edges(callee_module, callee_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_call_edges_resolved
    ON call_edges(resolved);
    """,
    """
    CREATE TABLE IF NOT EXISTS callable_refs (
        owner_file_id INTEGER NOT NULL,
        owner_module TEXT NOT NULL,
        owner_name TEXT NOT NULL,
        target_module TEXT,
        target_name TEXT,
        resolved INTEGER NOT NULL,
        PRIMARY KEY (
            owner_file_id,
            owner_module,
            owner_name,
            target_module,
            target_name
        ),
        FOREIGN KEY(owner_file_id) REFERENCES files(id)
    );
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_callable_refs_identity
    ON callable_refs(
        owner_file_id,
        owner_module,
        owner_name,
        COALESCE(target_module, ''),
        COALESCE(target_name, '')
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_callable_refs_owner
    ON callable_refs(owner_file_id, owner_module, owner_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_callable_refs_target
    ON callable_refs(target_module, target_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_callable_refs_resolved
    ON callable_refs(resolved);
    """,
    """
    CREATE TABLE IF NOT EXISTS call_records (
        file_id INTEGER NOT NULL,
        owner_module TEXT NOT NULL,
        owner_name TEXT NOT NULL,
        kind TEXT NOT NULL,
        base TEXT NOT NULL,
        target TEXT NOT NULL,
        lineno INTEGER NOT NULL,
        col_offset INTEGER NOT NULL,
        PRIMARY KEY (
            file_id,
            owner_module,
            owner_name,
            kind,
            base,
            target,
            lineno,
            col_offset
        ),
        FOREIGN KEY(file_id) REFERENCES files(id)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_call_records_file
    ON call_records(file_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_call_records_owner
    ON call_records(owner_module, owner_name);
    """,
    """
    CREATE TABLE IF NOT EXISTS callable_ref_records (
        file_id INTEGER NOT NULL,
        owner_module TEXT NOT NULL,
        owner_name TEXT NOT NULL,
        kind TEXT NOT NULL,
        ref_kind TEXT NOT NULL,
        base TEXT NOT NULL,
        target TEXT NOT NULL,
        lineno INTEGER NOT NULL,
        col_offset INTEGER NOT NULL,
        PRIMARY KEY (
            file_id,
            owner_module,
            owner_name,
            kind,
            ref_kind,
            base,
            target,
            lineno,
            col_offset
        ),
        FOREIGN KEY(file_id) REFERENCES files(id)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_callable_ref_records_file
    ON callable_ref_records(file_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_callable_ref_records_owner
    ON callable_ref_records(owner_module, owner_name);
    """,
    """
    CREATE TABLE IF NOT EXISTS embeddings (
        id INTEGER PRIMARY KEY,
        object_type TEXT NOT NULL,
        object_id INTEGER NOT NULL,
        backend TEXT NOT NULL,
        version TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        dim INTEGER NOT NULL,
        vector BLOB NOT NULL
    );
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_embeddings_object_backend_version
    ON embeddings(object_type, object_id, backend, version);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_functions_name ON functions(name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_classes_name ON classes(name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_symbol_name ON symbol_index(name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_symbol_file ON symbol_index(file_id);
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_symbol_stable_id ON symbol_index(stable_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_docstring_issues_file ON docstring_issues(file_id);
    """,
]
