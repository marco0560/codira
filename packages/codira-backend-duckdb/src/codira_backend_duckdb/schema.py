"""DuckDB backend physical schema constants."""

from __future__ import annotations

SCHEMA_VERSION = 22

DDL: tuple[str, ...] = (
    "CREATE SEQUENCE IF NOT EXISTS files_id_seq START 1;",
    "CREATE SEQUENCE IF NOT EXISTS modules_id_seq START 1;",
    "CREATE SEQUENCE IF NOT EXISTS classes_id_seq START 1;",
    "CREATE SEQUENCE IF NOT EXISTS functions_id_seq START 1;",
    "CREATE SEQUENCE IF NOT EXISTS imports_id_seq START 1;",
    "CREATE SEQUENCE IF NOT EXISTS overloads_id_seq START 1;",
    "CREATE SEQUENCE IF NOT EXISTS enum_members_id_seq START 1;",
    "CREATE SEQUENCE IF NOT EXISTS docstring_issues_id_seq START 1;",
    "CREATE SEQUENCE IF NOT EXISTS symbol_index_id_seq START 1;",
    "CREATE SEQUENCE IF NOT EXISTS documentation_artifacts_id_seq START 1;",
    "CREATE SEQUENCE IF NOT EXISTS embeddings_id_seq START 1;",
    """
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY DEFAULT nextval('files_id_seq'),
        path TEXT UNIQUE NOT NULL,
        hash TEXT NOT NULL,
        mtime DOUBLE NOT NULL,
        size BIGINT NOT NULL,
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
        id INTEGER PRIMARY KEY DEFAULT nextval('modules_id_seq'),
        file_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        docstring TEXT,
        has_docstring INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY DEFAULT nextval('classes_id_seq'),
        module_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        lineno INTEGER NOT NULL,
        end_lineno INTEGER,
        docstring TEXT,
        has_docstring INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS functions (
        id INTEGER PRIMARY KEY DEFAULT nextval('functions_id_seq'),
        module_id INTEGER NOT NULL,
        class_id INTEGER,
        name TEXT NOT NULL,
        lineno INTEGER NOT NULL,
        end_lineno INTEGER,
        signature TEXT,
        docstring TEXT,
        has_docstring INTEGER NOT NULL,
        is_method INTEGER NOT NULL,
        is_public INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS imports (
        id INTEGER PRIMARY KEY DEFAULT nextval('imports_id_seq'),
        module_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        alias TEXT,
        kind TEXT NOT NULL,
        lineno INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS overloads (
        id INTEGER PRIMARY KEY DEFAULT nextval('overloads_id_seq'),
        function_id INTEGER NOT NULL,
        stable_id TEXT NOT NULL,
        parent_stable_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        signature TEXT NOT NULL,
        docstring TEXT,
        lineno INTEGER NOT NULL,
        end_lineno INTEGER
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS enum_members (
        id INTEGER PRIMARY KEY DEFAULT nextval('enum_members_id_seq'),
        file_id INTEGER NOT NULL,
        module_name TEXT NOT NULL,
        symbol_name TEXT NOT NULL,
        symbol_lineno INTEGER NOT NULL,
        stable_id TEXT NOT NULL,
        parent_stable_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        name TEXT NOT NULL,
        signature TEXT NOT NULL,
        lineno INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS docstring_issues (
        id INTEGER PRIMARY KEY DEFAULT nextval('docstring_issues_id_seq'),
        file_id INTEGER NOT NULL,
        function_id INTEGER,
        class_id INTEGER,
        module_id INTEGER,
        issue_type TEXT NOT NULL,
        message TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS symbol_index (
        id INTEGER PRIMARY KEY DEFAULT nextval('symbol_index_id_seq'),
        name TEXT NOT NULL,
        stable_id TEXT NOT NULL,
        type TEXT NOT NULL,
        module_name TEXT NOT NULL,
        file_id INTEGER NOT NULL,
        lineno INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS documentation_artifacts (
        id INTEGER PRIMARY KEY DEFAULT nextval('documentation_artifacts_id_seq'),
        file_id INTEGER NOT NULL,
        stable_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        source_format TEXT NOT NULL,
        lineno INTEGER NOT NULL,
        end_lineno INTEGER,
        title TEXT NOT NULL,
        heading_path TEXT NOT NULL,
        text TEXT NOT NULL,
        owner_stable_id TEXT,
        owner_kind TEXT,
        attachment_confidence TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS call_edges (
        caller_file_id INTEGER NOT NULL,
        caller_module TEXT NOT NULL,
        caller_name TEXT NOT NULL,
        callee_module TEXT,
        callee_name TEXT,
        unresolved_identity TEXT NOT NULL DEFAULT '',
        external_target_kind TEXT,
        external_target_name TEXT,
        resolved INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS callable_refs (
        owner_file_id INTEGER NOT NULL,
        owner_module TEXT NOT NULL,
        owner_name TEXT NOT NULL,
        target_module TEXT,
        target_name TEXT,
        unresolved_identity TEXT NOT NULL DEFAULT '',
        external_target_kind TEXT,
        external_target_name TEXT,
        resolved INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS call_records (
        file_id INTEGER NOT NULL,
        owner_module TEXT NOT NULL,
        owner_name TEXT NOT NULL,
        kind TEXT NOT NULL,
        base TEXT NOT NULL,
        target TEXT NOT NULL,
        external_target_kind TEXT,
        external_target_name TEXT,
        lineno INTEGER NOT NULL,
        col_offset INTEGER NOT NULL
    );
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
        external_target_kind TEXT,
        external_target_name TEXT,
        lineno INTEGER NOT NULL,
        col_offset INTEGER NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS reference_scan_lines (
        file_id INTEGER NOT NULL,
        lineno INTEGER NOT NULL,
        line_text TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS embeddings (
        id INTEGER PRIMARY KEY DEFAULT nextval('embeddings_id_seq'),
        object_type TEXT NOT NULL,
        object_id INTEGER NOT NULL,
        backend TEXT NOT NULL,
        version TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        dim INTEGER NOT NULL,
        vector BLOB NOT NULL,
        vector_values DOUBLE[]
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS embedding_vector_cache (
        backend TEXT NOT NULL,
        version TEXT NOT NULL,
        dim INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        vector BLOB NOT NULL,
        PRIMARY KEY (backend, version, dim, content_hash)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS pending_embeddings (
        object_type TEXT NOT NULL,
        object_id INTEGER NOT NULL,
        stable_id TEXT NOT NULL,
        backend TEXT NOT NULL,
        version TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        dim INTEGER NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (object_type, object_id, backend, version)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS duckdb_symbol_lookup AS
    SELECT
        s.name,
        s.stable_id,
        s.type,
        s.module_name,
        s.file_id,
        f.path,
        s.lineno
    FROM symbol_index s
    JOIN files f ON f.id = s.file_id
    WHERE false;
    """,
    """
    CREATE TABLE IF NOT EXISTS duckdb_documentation_lookup AS
    SELECT
        d.stable_id,
        d.kind,
        d.source_format,
        d.file_id,
        f.path,
        d.lineno,
        d.end_lineno,
        d.title,
        d.heading_path,
        d.text,
        d.owner_stable_id,
        d.owner_kind,
        d.attachment_confidence
    FROM documentation_artifacts d
    JOIN files f ON f.id = d.file_id
    WHERE false;
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_documentation_stable_id ON documentation_artifacts(stable_id);",
    "CREATE INDEX IF NOT EXISTS idx_documentation_file ON documentation_artifacts(file_id);",
    "CREATE INDEX IF NOT EXISTS idx_documentation_kind_format ON documentation_artifacts(kind, source_format);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_call_edges_identity ON call_edges(caller_file_id, caller_module, caller_name, COALESCE(callee_module, ''), COALESCE(callee_name, ''), unresolved_identity);",
    "CREATE INDEX IF NOT EXISTS idx_call_edges_caller ON call_edges(caller_file_id, caller_module, caller_name);",
    "CREATE INDEX IF NOT EXISTS idx_call_edges_caller_lookup ON call_edges(caller_name, caller_module, caller_file_id);",
    "CREATE INDEX IF NOT EXISTS idx_call_edges_callee ON call_edges(callee_module, callee_name);",
    "CREATE INDEX IF NOT EXISTS idx_call_edges_callee_lookup ON call_edges(callee_name, callee_module);",
    "CREATE INDEX IF NOT EXISTS idx_call_edges_resolved ON call_edges(resolved);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_callable_refs_identity ON callable_refs(owner_file_id, owner_module, owner_name, COALESCE(target_module, ''), COALESCE(target_name, ''), unresolved_identity);",
    "CREATE INDEX IF NOT EXISTS idx_callable_refs_owner ON callable_refs(owner_file_id, owner_module, owner_name);",
    "CREATE INDEX IF NOT EXISTS idx_callable_refs_owner_lookup ON callable_refs(owner_name, owner_module, owner_file_id);",
    "CREATE INDEX IF NOT EXISTS idx_callable_refs_target ON callable_refs(target_module, target_name);",
    "CREATE INDEX IF NOT EXISTS idx_callable_refs_target_lookup ON callable_refs(target_name, target_module);",
    "CREATE INDEX IF NOT EXISTS idx_callable_refs_resolved ON callable_refs(resolved);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_overloads_stable_id ON overloads(stable_id);",
    "CREATE INDEX IF NOT EXISTS idx_overloads_function ON overloads(function_id, ordinal, lineno);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_enum_members_stable_id ON enum_members(stable_id);",
    "CREATE INDEX IF NOT EXISTS idx_enum_members_symbol ON enum_members(file_id, module_name, symbol_name, symbol_lineno, ordinal, lineno);",
    "CREATE INDEX IF NOT EXISTS idx_call_records_file ON call_records(file_id);",
    "CREATE INDEX IF NOT EXISTS idx_call_records_owner ON call_records(owner_module, owner_name);",
    "CREATE INDEX IF NOT EXISTS idx_callable_ref_records_file ON callable_ref_records(file_id);",
    "CREATE INDEX IF NOT EXISTS idx_callable_ref_records_owner ON callable_ref_records(owner_module, owner_name);",
    "CREATE INDEX IF NOT EXISTS idx_reference_scan_lines_file ON reference_scan_lines(file_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_embeddings_object_backend_version ON embeddings(object_type, object_id, backend, version);",
    "CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);",
    "CREATE INDEX IF NOT EXISTS idx_functions_name ON functions(name);",
    "CREATE INDEX IF NOT EXISTS idx_classes_name ON classes(name);",
    "CREATE INDEX IF NOT EXISTS idx_symbol_name ON symbol_index(name);",
    "CREATE INDEX IF NOT EXISTS idx_symbol_exact_lookup ON symbol_index(name, type, module_name, file_id, lineno);",
    "CREATE INDEX IF NOT EXISTS idx_symbol_file ON symbol_index(file_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_symbol_stable_id ON symbol_index(stable_id);",
    "CREATE INDEX IF NOT EXISTS idx_docstring_issues_file ON docstring_issues(file_id);",
    "CREATE INDEX IF NOT EXISTS idx_duckdb_modules_file_name ON modules(file_id, name);",
    "CREATE INDEX IF NOT EXISTS idx_duckdb_functions_symbol_detail ON functions(name, lineno, is_method, module_id);",
    "CREATE INDEX IF NOT EXISTS idx_duckdb_symbol_lookup_name ON duckdb_symbol_lookup(name, type, module_name, file_id, lineno);",
    "CREATE INDEX IF NOT EXISTS idx_duckdb_documentation_lookup_kind ON duckdb_documentation_lookup(kind, source_format);",
)

INDEX_DATA_TABLES: tuple[str, ...] = (
    "docstring_issues",
    "call_edges",
    "callable_refs",
    "call_records",
    "callable_ref_records",
    "reference_scan_lines",
    "overloads",
    "enum_members",
    "embeddings",
    "documentation_artifacts",
    "duckdb_symbol_lookup",
    "duckdb_documentation_lookup",
    "symbol_index",
    "imports",
    "functions",
    "classes",
    "modules",
    "files",
)

SEQUENCED_TABLES: tuple[str, ...] = (
    "files",
    "modules",
    "classes",
    "functions",
    "imports",
    "overloads",
    "enum_members",
    "docstring_issues",
    "symbol_index",
    "documentation_artifacts",
    "embeddings",
)
