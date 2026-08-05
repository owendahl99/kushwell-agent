"""
core/intent_planner.py

Turns structured intent into an execution graph.
"""

from __future__ import annotations

from typing import Any

from core.intents.intent_registry import intent_registry


class IntentPlanner:
    def plan(self, parsed: dict[str, Any]) -> dict[str, Any]:
        intent_name = parsed.get("intent")

        for intent in intent_registry.all():
            if intent.name == intent_name:
                return intent.graph_builder(parsed)

        return self._fallback_graph()

    def _fallback_graph(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "id": "A",
                    "tool": "list_directory",
                    "args": {"path": "workspace:/"},
                    "deps": [],
                }
            ]
        }


intent_planner = IntentPlanner()