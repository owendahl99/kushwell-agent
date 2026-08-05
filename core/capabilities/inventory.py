from core.capabilities.capability_registry import Capability, capability_registry


def build_inventory_nodes(request: dict, nodes: list[dict]) -> list[dict]:
    source = request.get("source", "workspace:/")

    nodes.append({
        "id": "inventory_source",
        "tool": "project_index",
        "args": {"path": source},
        "deps": [],
    })

    return nodes


capability_registry.register(
    Capability(
        name="inventory",
        operations=["inventory"],
        builder=build_inventory_nodes,
        priority=100,
    )
)