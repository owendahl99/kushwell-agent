from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(slots=True)
class SemanticRequest:
    action: str
    subject: str = ""
    source: str = "workspace:/"
    destination: str | None = None
    filters: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    confidence: int = 0
    original_request: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)