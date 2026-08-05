"""
core/validator.py

Validation layer for the Kushwell Brain.

Responsibilities
----------------
• Validate tool existence
• Validate required arguments
• Validate argument types
• Validate workspace paths
• Normalize arguments before execution

The validator never executes tools.
"""

from __future__ import annotations

from typing import Any

from core.tool_registry import registry


# ==========================================================
# EXCEPTIONS
# ==========================================================

class ValidationError(Exception):
    """Base validation exception."""


class UnknownToolError(ValidationError):
    """Raised when a tool does not exist."""


class MissingArgumentError(ValidationError):
    """Raised when required arguments are missing."""


class InvalidArgumentError(ValidationError):
    """Raised when an argument is invalid."""


# ==========================================================
# VALIDATOR
# ==========================================================

class ToolValidator:

    def validate(
        self,
        tool_name: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Validate a tool call.

        Returns a normalized copy of args.
        """

        if not registry.exists(tool_name):
            raise UnknownToolError(
                f"Unknown tool '{tool_name}'."
            )

        tool = registry.get(tool_name)

        args = dict(args)

        # ------------------------------------------
        # Required arguments
        # ------------------------------------------

        for required in tool.required_args:

            if required not in args:
                raise MissingArgumentError(
                    f"'{required}' is required "
                    f"for tool '{tool_name}'."
                )

        # ------------------------------------------
        # Path validation
        # ------------------------------------------

        if "path" in args:

            if not isinstance(args["path"], str):
                raise InvalidArgumentError(
                    "'path' must be a string."
                )

            if not (
                args["path"].startswith("workspace:/")
                or args["path"].startswith("/")
            ):
                raise InvalidArgumentError(
                    "Path must begin with "
                    "'workspace:/'."
                )

        # ------------------------------------------
        # Content validation
        # ------------------------------------------

        if "content" in args:

            if not isinstance(args["content"], str):
                raise InvalidArgumentError(
                    "'content' must be a string."
                )

        return args


# ==========================================================
# GLOBAL VALIDATOR
# ==========================================================

validator = ToolValidator()