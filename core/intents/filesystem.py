from core.intents.intent_types import IntentDefinition
from core.intents.intent_registry import intent_registry


def build_list_directory(ctx):
    return {
        "nodes": [
            {
                "id": "A",
                "tool": "list_directory",
                "args": {"path": ctx["target"]},
                "deps": [],
            }
        ]
    }


def build_read_file(ctx):
    return {
        "nodes": [
            {
                "id": "A",
                "tool": "read_file",
                "args": {"path": ctx["target"]},
                "deps": [],
            }
        ]
    }


intent_registry.register(
    IntentDefinition(
        name="list_directory",
        examples=[
            "list files",
            "show files",
            "what is in this folder",
            "show everything in templates",
            "list everything in the templates folder",
        ],
        keywords=["list", "show", "files", "folder", "directory", "everything"],
        target_hints={
            "templates": "workspace:/templates",
            "template": "workspace:/templates",
            "core": "workspace:/core",
            "root": "workspace:/",
        },
        graph_builder=build_list_directory,
        priority=10,
    )
)

intent_registry.register(
    IntentDefinition(
        name="read_file",
        examples=[
            "read file",
            "open file",
            "show me agent.py",
            "display server.py",
        ],
        keywords=["read", "open", "display", "show file"],
        target_hints={
            "agent.py": "workspace:/agent.py",
            "server.py": "workspace:/server.py",
            "memory.json": "workspace:/memory.json",
        },
        graph_builder=build_read_file,
        priority=8,
    )
)