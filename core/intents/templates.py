from core.intents.intent_types import IntentDefinition
from core.intents.intent_registry import intent_registry


def build_template_audit(ctx):
    return {
        "nodes": [
            {
                "id": "A",
                "tool": "list_directory",
                "args": {"path": "workspace:/templates"},
                "deps": [],
            },
            {
                "id": "B",
                "tool": "list_directory",
                "args": {"path": "workspace:/"},
                "deps": [],
            },
        ]
    }


intent_registry.register(
    IntentDefinition(
        name="template_audit",
        examples=[
            "audit templates",
            "find unused templates",
            "show templates not used by routes",
            "clean up unused templates",
            "move unused templates into unused folder",
        ],
        keywords=[
            "template",
            "templates",
            "unused",
            "audit",
            "cleanup",
            "clean up",
            "routes",
        ],
        target_hints={
            "templates": "workspace:/templates",
            "template": "workspace:/templates",
        },
        graph_builder=build_template_audit,
        requires_confirmation=True,
        priority=20,
    )
)