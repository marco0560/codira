"""Agent-efficiency benchmark implementation support.

Responsibilities
----------------
- Hold benchmark tooling that is intentionally separate from Codira runtime.
- Keep runner and isolation code importable by focused tests.

Design principles
-----------------
Benchmark helpers preserve evidence and fail closed when their prerequisites are
not proven.

Architectural role
------------------
This package belongs to the developer tooling layer.
"""
