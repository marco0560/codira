"""Query-time retrieval and rendering helpers for codira.

Responsibilities
----------------
- Export context building entrypoints, scorer rules, and utility helpers for query execution.
- Re-export core symbols used by CLI commands that fetch and render context.

Design principles
-----------------
This package stays lightweight so CLI and tooling logic can import query helpers succinctly.

Architectural role
------------------
This module belongs to the **query entrypoint layer** that unifies context, classifier, and registry helpers for retrieval workflows.
"""
