"""
core/permissions.py

Permission engine for Kushwell Brain.

This layer decides whether a tool is ALLOWED to execute
based on:

    • tool type
    • workspace context
    • safety rules
    • future user roles (admin / agent / system)

This is NOT validation.
This is NOT execution.
This is authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.tool_registry import registry


# ==========================================================
# EXCEPTIONS
# ==========================================================

class PermissionDenied(Exception):
    pass


# ==========================================================
# PERMISSION ENGINE
# ==========================================================

@dataclass
class PermissionEngine:
    """
    Central authorization layer.
    """

    # ------------------------------------------------------
    # GLOBAL SAFETY RULES (START SIMPLE, EXPAND LATER)
    # ------------------------------------------------------

    SAFE_TOOLS = {
        "list_directory",
        "read_file",
        "write_file",
    }

    # ------------------------------------------------------

    def check(
        self,
        tool_name: str,
        args: dict[str, Any],
    ) -> None:
        """
        Raises PermissionDenied if execution is not allowed.
        """

        # STEP 1 — tool must exist in registry
        if not registry.exists(tool_name):
            raise PermissionDenied(
                f"Unknown tool: {tool_name}"
            )

        tool = registry.get(tool_name)

        # STEP 2 — SAFE TOOL GATE
        if tool_name not in self.SAFE_TOOLS:
            raise PermissionDenied(
                f"Tool not permitted: {tool_name}"
            )

        # STEP 3 — FUTURE EXTENSION POINTS
        # (we will expand this later)
        #
        # - user role checks
        # - workspace isolation rules
        # - file path restrictions
        # - audit logging
        # - rate limiting

        return


# ==========================================================
# GLOBAL INSTANCE
# ==========================================================

permissions = PermissionEngine()