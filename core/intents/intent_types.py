from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class IntentDefinition:
    name: str
    examples: list[str]
    keywords: list[str]
    target_hints: dict[str, str]
    graph_builder: Callable[[dict[str, Any]], dict[str, Any]]
    requires_confirmation: bool = False
    priority: int = 0


@dataclass(slots=True)
class IntentMatch:
    intent: str
    confidence: int
    target: str
    requires_confirmation: bool
    metadata: dict[str, Any] = field(default_factory=dict)