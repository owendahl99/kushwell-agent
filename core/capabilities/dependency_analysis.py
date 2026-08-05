from core.capabilities.capability_registry import Capability, capability_registry


def build_dependency_nodes(request: dict, nodes: list[dict]) -> list[dict]:
    operations = request.get("constraints", {}).get("operations", [])
    subject = request.get("subject")

    if "usage_analysis" not in operations:
        return nodes

    if subject in {"templates", "unused_templates"}:
        nodes.append({
            "id": "inventory_routes",
            "tool": "list_directory",
            "args": {"path": "workspace:/routes"},
            "deps": [],
        })

    return nodes


capability_registry.register(
    Capability(
        name="dependency_analysis",
        operations=["usage_analysis"],
        builder=build_dependency_nodes,
        priority=90,
    )
)