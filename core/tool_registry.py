"""
core/tool_registry.py

Single source of truth for every tool the Kushwell Brain can execute.

The registry owns:

    • Tool existence
    • Required arguments
    • Optional arguments
    • Permissions
    • Descriptions
    • Future metadata (cost, timeout, retries, etc.)

Nothing else in the system should maintain its own list of tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ==========================================================
# TOOL DEFINITION
# ==========================================================

@dataclass(slots=True)
class ToolDefinition:

    # Internal name used by the Brain
    name: str

    # MCP tool name (can differ later if needed)
    mcp_name: str

    # Human description
    description: str

    # Required arguments
    required_args: list[str] = field(default_factory=list)

    # Optional arguments
    optional_args: list[str] = field(default_factory=list)

    # Permission tags
    permissions: list[str] = field(default_factory=list)

    # Future metadata
    timeout: float = 60.0

    retries: int = 2


# ==========================================================
# REGISTRY
# ==========================================================

class ToolRegistry:

    def __init__(self):

        self._tools: dict[str, ToolDefinition] = {}

    # ------------------------------------------------------

    def register(self, tool: ToolDefinition):

        if tool.name in self._tools:
            raise ValueError(
                f"Tool '{tool.name}' is already registered."
            )

        self._tools[tool.name] = tool

    # ------------------------------------------------------

    def exists(self, tool_name: str) -> bool:

        return tool_name in self._tools

    # ------------------------------------------------------

    def get(self, tool_name: str) -> ToolDefinition:

        if tool_name not in self._tools:
            raise ValueError(
                f"Unknown tool '{tool_name}'."
            )

        return self._tools[tool_name]

    # -----------------------------------------------------
    
    def mcp_name(self, tool_name: str) -> str:
       return self.get(tool_name).mcp_name

    # ------------------------------------------------------

    def validate(self, tool_name: str, args: dict[str, Any]):

        tool = self.get(tool_name)

        for required in tool.required_args:

            if required not in args:
                raise ValueError(
                    f"Tool '{tool_name}' requires argument '{required}'."
                )

    # ------------------------------------------------------

    def mcp_name(self, tool_name: str) -> str:

        return self.get(tool_name).mcp_name

    # ------------------------------------------------------

    def permissions(self, tool_name: str):

        return self.get(tool_name).permissions

    # ------------------------------------------------------

    def all(self):

        return list(self._tools.values())

    # ------------------------------------------------------

    def names(self):

        return sorted(self._tools.keys())


# ==========================================================
# GLOBAL REGISTRY
# ==========================================================

registry = ToolRegistry()


# ==========================================================
# FILESYSTEM TOOLS
# ==========================================================

registry.register(
    ToolDefinition(
        name="list_directory",
        mcp_name="list_directory",
        description="List directory contents.",
        required_args=["path"],
        permissions=["filesystem.read"],
    )
)

registry.register(
    ToolDefinition(
        name="read_file",
        mcp_name="read_file",
        description="Read a text file.",
        required_args=["path"],
        permissions=["filesystem.read"],
    )
)


registry.register(
    ToolDefinition(
        name="project_index",
        mcp_name="project_index",
        description="Build or refresh the persistent recursive project index.",
        optional_args=["path", "force"],
        permissions=["filesystem.read"],
    )
)

registry.register(
    ToolDefinition(
        name="search_project_index",
        mcp_name="search_project_index",
        description="Search the persistent project index by file, symbol, route, or reference.",
        required_args=["query"],
        optional_args=["limit", "categories", "extensions"],
        permissions=["filesystem.read"],
    )
)

registry.register(
    ToolDefinition(
        name="get_project_relationships",
        mcp_name="get_project_relationships",
        description="Expand direct and reverse relationships for matching project files.",
        required_args=["query"],
        optional_args=["limit", "include_reverse"],
        permissions=["filesystem.read"],
    )
)



registry.register(
    ToolDefinition(
        name="audit_platform_capabilities",
        mcp_name="audit_platform_capabilities",
        description="Compare platform capability definitions to the persistent project index and produce a structural health report.",
        optional_args=["capability", "rebuild_index", "persist"],
        permissions=["filesystem.read"],
    )
)

registry.register(
    ToolDefinition(
        name="get_atlas_dashboard",
        mcp_name="get_atlas_dashboard",
        description="Build the Kushwell Atlas executive launch and architecture dashboard.",
        optional_args=["rebuild_index", "persist"],
        permissions=["filesystem.read"],
    )
)


registry.register(
    ToolDefinition(
        name="write_file",
        mcp_name="write_file",
        description="Write a text file.",
        required_args=[
            "path",
            "content",
        ],
        permissions=["filesystem.write"],
    )
)

# ==========================================================
# KAP ACQUISITION TOOLS
# ==========================================================

registry.register(
    ToolDefinition(
        name="query_acquisition_status",
        mcp_name="query_acquisition_status",
        description=(
            "Read KAP regional registry and acquisition run-ledger status."
        ),
        optional_args=["requested_by"],
        permissions=["acquisition.read"],
    )
)

registry.register(
    ToolDefinition(
        name="query_acquisition_runs",
        mcp_name="query_acquisition_runs",
        description="Read recent governed KAP acquisition runs.",
        optional_args=["limit"],
        permissions=["acquisition.read"],
    )
)

registry.register(
    ToolDefinition(
        name="plan_product_acquisition",
        mcp_name="plan_product_acquisition",
        description=(
            "Create a dry-run regional product acquisition plan."
        ),
        optional_args=[
            "jurisdiction_code",
            "provider_key",
            "start_id",
            "batch_size",
            "max_batches",
            "triggered_by",
        ],
        permissions=["acquisition.plan"],
    )
)

registry.register(
    ToolDefinition(
        name="run_product_acquisition",
        mcp_name="run_product_acquisition",
        description=(
            "Execute a governed regional product acquisition. "
            "Live execution requires explicit confirmation."
        ),
        optional_args=[
            "jurisdiction_code",
            "provider_key",
            "start_id",
            "batch_size",
            "max_batches",
            "dry_run",
            "confirm_live",
            "triggered_by",
        ],
        permissions=["acquisition.execute"],
        timeout=3600.0,
        retries=0,
    )
)
