"""Prompt construction package for codira.

Responsibilities
----------------
- Provide helper functions to build deterministic prompts and context sections for consumers.
- Collect shared prompt metadata and configuration used by `build_prompt` and related helpers.

Design principles
-----------------
Prompt utilities stay deterministic, human-readable, and easy to extend for new prompt flows.

Architectural role
------------------
This module belongs to the **prompt infrastructure layer** that serves CLI and agent-facing prompt generation.
"""
