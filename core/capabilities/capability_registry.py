from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any


@dataclass(slots=True)
class Capability:
    name: str
    operations: list[str]
    builder: Callable[[dict[str, Any], list[dict]], list[dict]]
    priority: int = 0


class CapabilityRegistry:
    def __init__(self):
        self._capabilities: list[Capability] = []

    def register(self, capability: Capability):
        self._capabilities.append(capability)

    def matching(self, request: dict) -> list[Capability]:
            operations = set(request.get("constraints", {}).get("operations", []))
            subject = request.get("subject")

            matched = []

            for cap in self._capabilities:
                if operations.intersection(cap.operations):
                    matched.append(cap)
                    continue

                if subject in {"templates", "unused_templates"} and cap.name == "dependency_analysis":
                    matched.append(cap)

            return sorted(matched, key=lambda c: c.priority, reverse=True)

capability_registry = CapabilityRegistry()