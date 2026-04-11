"""Semantic retrieval package for codira.

Responsibilities
----------------
- Expose semantic embedding backend selection and shared helpers for provisioning and search.
- Provide stable imports for embedding metadata used across the CLI and automation code.

Design principles
-----------------
The package keeps the semantic backend interface stable, centralized, and easy to import.

Architectural role
------------------
This module belongs to the **semantic retrieval layer** of codira retrieval architecture.
"""
