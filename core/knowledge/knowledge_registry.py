from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass(slots=True, frozen=True)
class KnowledgeOwner:
    """Canonical implementation endpoint for a governed knowledge contract."""

    service: str
    method: str
    project: str
    interface: str = "python"
    status: str = "planned"


@dataclass(slots=True)
class KnowledgeContract:
    """Machine-readable description of one canonical Kushwell knowledge domain."""

    key: str
    name: str
    version: str
    purpose: str
    canonical_owner: KnowledgeOwner
    aliases: list[str] = field(default_factory=list)
    audiences: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    contract_document: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeRegistry:
    """Atlas registry of canonical knowledge ownership.

    This registry answers: "Who owns this knowledge, and through which stable
    interface should Atlas request it?"

    It does not replace the DAG capability registry, which chooses executable
    builders, or the platform capability registry, which audits whether a
    platform capability is structurally present.
    """

    def __init__(self, contracts_dir: str | Path | None = None) -> None:
        self.contracts_dir = Path(
            contracts_dir or Path(__file__).parent / "contracts"
        )
        self._contracts: dict[str, KnowledgeContract] = {}

    @staticmethod
    def normalize_key(value: str) -> str:
        return (
            str(value or "")
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )

    def load(self, force: bool = False) -> "KnowledgeRegistry":
        if self._contracts and not force:
            return self

        self._contracts.clear()
        if not self.contracts_dir.exists():
            return self

        for path in sorted(self.contracts_dir.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            contract = self._parse(raw, path)
            if contract.key in self._contracts:
                raise ValueError(f"Duplicate knowledge contract key: {contract.key}")
            self._contracts[contract.key] = contract

        self.validate()
        return self

    def _parse(self, raw: dict[str, Any], source: Path) -> KnowledgeContract:
        required = {"key", "name", "version", "purpose", "canonical_owner"}
        missing = sorted(required - raw.keys())
        if missing:
            raise ValueError(
                f"{source.name} missing required fields: {', '.join(missing)}"
            )

        owner_raw = raw["canonical_owner"]
        owner_required = {"service", "method", "project"}
        owner_missing = sorted(owner_required - owner_raw.keys())
        if owner_missing:
            raise ValueError(
                f"{source.name} canonical_owner missing: {', '.join(owner_missing)}"
            )

        key = self.normalize_key(raw["key"])
        aliases = [self.normalize_key(v) for v in raw.get("aliases", [])]

        return KnowledgeContract(
            key=key,
            name=str(raw["name"]),
            version=str(raw["version"]),
            purpose=str(raw["purpose"]),
            canonical_owner=KnowledgeOwner(**owner_raw),
            aliases=aliases,
            audiences=list(raw.get("audiences", [])),
            sources=list(raw.get("sources", [])),
            permissions=list(raw.get("permissions", [])),
            capabilities=list(raw.get("capabilities", [])),
            contract_document=str(raw.get("contract_document", "")),
            notes=str(raw.get("notes", "")),
        )

    def validate(self) -> None:
        alias_owner: dict[str, str] = {}
        for contract in self._contracts.values():
            for alias in [contract.key, *contract.aliases]:
                previous = alias_owner.get(alias)
                if previous and previous != contract.key:
                    raise ValueError(
                        f"Knowledge alias {alias!r} belongs to both "
                        f"{previous!r} and {contract.key!r}"
                    )
                alias_owner[alias] = contract.key

    def all(self) -> list[KnowledgeContract]:
        self.load()
        return sorted(self._contracts.values(), key=lambda row: row.name.lower())

    def get(self, key: str) -> KnowledgeContract:
        self.load()
        normalized = self.normalize_key(key)

        if normalized in self._contracts:
            return self._contracts[normalized]

        for contract in self._contracts.values():
            if normalized in contract.aliases:
                return contract
            if contract.name.lower() == str(key or "").strip().lower():
                return contract

        raise KeyError(f"Unknown knowledge contract: {key}")

    def search(self, query: str) -> list[KnowledgeContract]:
        self.load()
        terms = [term for term in self.normalize_key(query).split("_") if term]
        if not terms:
            return self.all()

        scored: list[tuple[int, KnowledgeContract]] = []
        for contract in self._contracts.values():
            priority_text = " ".join(
                [contract.key, contract.name, *contract.aliases]
            ).lower()
            full_text = " ".join(
                [
                    priority_text,
                    contract.purpose,
                    *contract.audiences,
                    *contract.sources,
                    *contract.capabilities,
                ]
            ).lower()

            score = 0
            for term in terms:
                if term in priority_text:
                    score += 4
                elif term in full_text:
                    score += 1

            if score:
                scored.append((score, contract))

        return [
            contract
            for _, contract in sorted(
                scored,
                key=lambda row: (-row[0], row[1].name.lower()),
            )
        ]

    def resolve_request(self, request: dict[str, Any]) -> list[KnowledgeContract]:
        """Resolve only the contracts relevant to one semantic request."""

        request = request or {}
        action = str(request.get("action") or "")
        subject = str(request.get("subject") or "")
        original = str(request.get("original_request") or "")
        outcomes = " ".join(
            str(value)
            for value in (request.get("constraints") or {}).get("outcomes", [])
        )
        text = " ".join([action, subject, original, outcomes]).lower()

        keys: list[str] = []

        rules: tuple[tuple[set[str], str], ...] = (
            ({"product", "strain", "chemistry", "potency", "inventory"}, "product_knowledge"),
            ({"patient", "wellness", "check-in", "checkin", "symptom", "medical"}, "patient_knowledge"),
            ({"recommend", "recommendation", "rank", "match"}, "recommendation_knowledge"),
            ({"research", "population", "cohort", "study", "evidence"}, "research_knowledge"),
        )

        for terms, key in rules:
            if any(term in text for term in terms):
                keys.append(key)

        # Recommendation requests require both sides of the matching contract.
        if action == "recommend":
            keys.extend(
                [
                    "patient_knowledge",
                    "product_knowledge",
                    "recommendation_knowledge",
                ]
            )

        resolved: list[KnowledgeContract] = []
        seen: set[str] = set()
        for key in keys:
            if key in seen:
                continue
            try:
                resolved.append(self.get(key))
                seen.add(key)
            except KeyError:
                # Contracts can be introduced incrementally without breaking Atlas.
                continue

        return resolved

    def request_context(self, request: dict[str, Any]) -> dict[str, Any]:
        contracts = self.resolve_request(request)
        return {
            "registry_version": 1,
            "contracts": [
                {
                    "key": contract.key,
                    "name": contract.name,
                    "version": contract.version,
                    "owner": asdict(contract.canonical_owner),
                    "permissions": contract.permissions,
                    "capabilities": contract.capabilities,
                }
                for contract in contracts
            ],
        }

    def summary(self) -> dict[str, Any]:
        contracts = self.all()
        by_status: dict[str, int] = {}
        for contract in contracts:
            status = contract.canonical_owner.status
            by_status[status] = by_status.get(status, 0) + 1
        return {
            "contracts": len(contracts),
            "by_owner_status": dict(sorted(by_status.items())),
            "keys": [contract.key for contract in contracts],
        }


knowledge_registry = KnowledgeRegistry()
