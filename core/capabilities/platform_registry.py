from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable


VALID_STATUSES = {
    "complete",
    "functional_but_incomplete",
    "partially_wired",
    "present_but_broken",
    "concept_only",
    "legacy",
    "missing",
    "unknown",
}


@dataclass(slots=True)
class CapabilityRequirement:
    kind: str
    name: str
    description: str = ""
    required: bool = True
    launch_blocking: bool = False
    patterns: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass(slots=True)
class PlatformCapability:
    key: str
    name: str
    purpose: str
    launch_critical: bool
    priority: int
    audience: list[str]
    outcomes: list[str]
    dependencies: list[str]
    requirements: list[CapabilityRequirement]
    status: str = "unknown"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PlatformCapabilityRegistry:
    """Authoritative registry of what Kushwell capabilities are meant to do.

    This registry is intentionally separate from the planner-builder registry in
    ``core.capabilities.capability_registry``. The planner registry answers
    "which DAG builder should run?"; this registry answers "what must this
    platform capability contain and accomplish?".
    """

    def __init__(self, definitions_dir: str | Path | None = None):
        self.definitions_dir = Path(definitions_dir or Path(__file__).parent / "definitions")
        self._capabilities: dict[str, PlatformCapability] = {}

    def load(self, force: bool = False) -> "PlatformCapabilityRegistry":
        if self._capabilities and not force:
            return self

        self._capabilities.clear()
        if not self.definitions_dir.exists():
            return self

        for path in sorted(self.definitions_dir.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            cap = self._parse_capability(raw, source=path)
            if cap.key in self._capabilities:
                raise ValueError(f"Duplicate platform capability key: {cap.key}")
            self._capabilities[cap.key] = cap
        return self

    def _parse_capability(self, raw: dict[str, Any], source: Path) -> PlatformCapability:
        required_fields = {"key", "name", "purpose", "launch_critical", "priority"}
        missing = sorted(required_fields - raw.keys())
        if missing:
            raise ValueError(f"{source.name} missing required fields: {', '.join(missing)}")

        status = str(raw.get("status", "unknown")).strip().lower()
        if status not in VALID_STATUSES:
            raise ValueError(f"{source.name} has invalid status: {status}")

        requirements = []
        for item in raw.get("requirements", []):
            if not item.get("kind") or not item.get("name"):
                raise ValueError(f"{source.name} contains requirement without kind/name")
            requirements.append(CapabilityRequirement(**item))

        return PlatformCapability(
            key=str(raw["key"]),
            name=str(raw["name"]),
            purpose=str(raw["purpose"]),
            launch_critical=bool(raw["launch_critical"]),
            priority=int(raw["priority"]),
            audience=list(raw.get("audience", [])),
            outcomes=list(raw.get("outcomes", [])),
            dependencies=list(raw.get("dependencies", [])),
            requirements=requirements,
            status=status,
            notes=str(raw.get("notes", "")),
        )

    def all(self, *, launch_critical: bool | None = None) -> list[PlatformCapability]:
        self.load()
        rows: Iterable[PlatformCapability] = self._capabilities.values()
        if launch_critical is not None:
            rows = (c for c in rows if c.launch_critical is launch_critical)
        return sorted(rows, key=lambda c: (-c.priority, c.name.lower()))

    def get(self, key: str) -> PlatformCapability:
        self.load()
        normalized = key.strip().lower().replace(" ", "_").replace("-", "_")
        if normalized in self._capabilities:
            return self._capabilities[normalized]
        for cap in self._capabilities.values():
            if cap.name.lower() == key.strip().lower():
                return cap
        raise KeyError(f"Unknown platform capability: {key}")

    def search(self, query: str) -> list[PlatformCapability]:
        self.load()
        terms = [t for t in query.lower().split() if t]
        if not terms:
            return self.all()

        scored: list[tuple[int, PlatformCapability]] = []
        for cap in self._capabilities.values():
            haystack = " ".join([
                cap.key, cap.name, cap.purpose, " ".join(cap.audience),
                " ".join(cap.outcomes), " ".join(cap.dependencies),
                " ".join(r.name + " " + r.description for r in cap.requirements),
            ]).lower()
            score = sum(3 if term in cap.key or term in cap.name.lower() else 1 for term in terms if term in haystack)
            if score:
                scored.append((score, cap))
        return [cap for _, cap in sorted(scored, key=lambda x: (-x[0], -x[1].priority, x[1].name))]

    def validate_dependencies(self) -> list[str]:
        self.load()
        errors: list[str] = []
        keys = set(self._capabilities)
        for cap in self._capabilities.values():
            for dep in cap.dependencies:
                if dep not in keys:
                    errors.append(f"{cap.key} depends on unknown capability {dep}")
        return errors

    def summary(self) -> dict[str, Any]:
        caps = self.all()
        return {
            "capabilities": len(caps),
            "launch_critical": sum(1 for c in caps if c.launch_critical),
            "non_launch_critical": sum(1 for c in caps if not c.launch_critical),
            "requirements": sum(len(c.requirements) for c in caps),
            "dependency_errors": self.validate_dependencies(),
            "by_status": {
                status: sum(1 for c in caps if c.status == status)
                for status in sorted(VALID_STATUSES)
                if any(c.status == status for c in caps)
            },
        }


platform_capability_registry = PlatformCapabilityRegistry()
