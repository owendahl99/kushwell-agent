from core.capabilities.capability_registry import Capability, capability_registry



def build_summary_nodes(request: dict, nodes: list[dict]) -> list[dict]:
    # Placeholder for next tool: summarize_files.
    # For now, summary depends on inventory existing.
    return nodes


capability_registry.register(
    Capability(
        name="summarize",
        operations=["summarize"],
        builder=build_summary_nodes,
        priority=50,
    )
)