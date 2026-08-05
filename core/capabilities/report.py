from core.capabilities.capability_registry import Capability, capability_registry
    


def build_report_nodes(request: dict, nodes: list[dict]) -> list[dict]:
    deliverable = request.get("constraints", {}).get("deliverable")

    if deliverable == "location_file":
        # Placeholder until write/report tools are approved.
        # No write is performed yet because dry_run/no_changes is true.
        return nodes

    return nodes


capability_registry.register(
    Capability(
        name="report",
        operations=["report", "summarize", "recommend"],
        builder=build_report_nodes,
        priority=10,
    )
)