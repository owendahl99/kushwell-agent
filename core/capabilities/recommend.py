from core.capabilities.capability_registry import Capability, capability_registry



def build_recommendation_nodes(request: dict, nodes: list[dict]) -> list[dict]:
    # Placeholder for next tool: recommend_file_actions.
    # For now, recommendations are report-layer work.
    return nodes


capability_registry.register(
    Capability(
        name="recommend",
        operations=["recommend"],
        builder=build_recommendation_nodes,
        priority=40,
    )
)