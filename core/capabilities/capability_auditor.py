from __future__ import annotations

import fnmatch
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.capabilities.platform_registry import (
    CapabilityRequirement,
    PlatformCapability,
    PlatformCapabilityRegistry,
    platform_capability_registry,
)
from core.project_indexer import ProjectIndexer


VALID_REQUIREMENT_STATUSES = {"present", "partial", "missing", "broken", "unknown"}
DEFAULT_AUDIT_PATH = "workspace:/.brain/capability_audit.json"
DEFAULT_REPORT_PATH = "workspace:/.brain/capability_health_report.md"


@dataclass(slots=True)
class RequirementEvidence:
    path: str
    score: int
    reasons: list[str] = field(default_factory=list)
    parse_errors: list[dict[str, Any]] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RequirementAudit:
    kind: str
    name: str
    description: str
    required: bool
    launch_blocking: bool
    status: str
    confidence: str
    message: str
    patterns: list[str]
    evidence: list[RequirementEvidence] = field(default_factory=list)
    manual_review_required: bool = False


@dataclass(slots=True)
class CapabilityAudit:
    key: str
    name: str
    purpose: str
    launch_critical: bool
    priority: int
    structural_status: str
    readiness_percent: int
    blockers: list[str]
    warnings: list[str]
    requirements: list[RequirementAudit]
    dependencies: list[str]
    dependency_status: dict[str, str]
    runtime_certified: bool = False


class CapabilityAuditor:
    """Compare the platform capability registry to the persistent project index.

    The auditor is deliberately conservative. It can establish structural
    evidence (files, symbols, routes, templates, references) but it does not
    claim runtime or clinical completeness without explicit tests.
    """

    def __init__(
        self,
        project_indexer: ProjectIndexer,
        registry: PlatformCapabilityRegistry | None = None,
        audit_path: str = DEFAULT_AUDIT_PATH,
        report_path: str = DEFAULT_REPORT_PATH,
    ) -> None:
        self.project_indexer = project_indexer
        self.registry = registry or platform_capability_registry
        self.audit_path = audit_path
        self.report_path = report_path

    def audit_all(
        self,
        *,
        rebuild_index: bool = False,
        capability_keys: Iterable[str] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        if rebuild_index:
            index = self.project_indexer.build(force=False)
        else:
            try:
                index = self.project_indexer.load()
            except FileNotFoundError:
                index = self.project_indexer.build()

        requested = {x.strip().lower() for x in capability_keys or [] if str(x).strip()}
        capabilities = self.registry.all()
        if requested:
            capabilities = [c for c in capabilities if c.key in requested]

        first_pass: dict[str, CapabilityAudit] = {}
        for capability in capabilities:
            first_pass[capability.key] = self._audit_capability(capability, index)

        for result in list(first_pass.values()):
            for dep in result.dependencies:
                dep_result = first_pass.get(dep)
                if dep_result is None:
                    try:
                        dep_result = self._audit_capability(self.registry.get(dep), index)
                        first_pass[dep] = dep_result
                    except KeyError:
                        result.dependency_status[dep] = "unknown"
                        continue
                result.dependency_status[dep] = dep_result.structural_status

            bad_dependencies = [
                name for name, status in result.dependency_status.items()
                if status in {"missing", "present_but_broken", "concept_only"}
            ]
            if bad_dependencies:
                result.warnings.append(
                    "Unhealthy dependencies: " + ", ".join(sorted(bad_dependencies))
                )
                if result.launch_critical:
                    result.blockers.append(
                        "Launch-critical dependency gap: " + ", ".join(sorted(bad_dependencies))
                    )

        rows = sorted(first_pass.values(), key=lambda x: (-x.priority, x.name.lower()))
        payload = {
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "index_generated_at": index.get("generated_at"),
            "runtime_certified": False,
            "disclaimer": (
                "Structural evidence only. Presence does not prove runtime behavior, "
                "clinical correctness, usability, or production readiness."
            ),
            "summary": self._summary(rows),
            "capabilities": [self._capability_to_dict(row) for row in rows],
        }

        if persist:
            self._save_json(payload)
            self._save_markdown(payload)

        return payload

    def audit_one(self, key: str, *, persist: bool = False) -> dict[str, Any]:
        return self.audit_all(capability_keys=[self.registry.get(key).key], persist=persist)

    def _audit_capability(
        self,
        capability: PlatformCapability,
        index: dict[str, Any],
    ) -> CapabilityAudit:
        requirement_results = [
            self._audit_requirement(requirement, index)
            for requirement in capability.requirements
        ]

        blockers = [
            r.name for r in requirement_results
            if r.launch_blocking and r.status in {"missing", "broken"}
        ]
        warnings = [
            r.name for r in requirement_results
            if r.required and r.status in {"partial", "unknown"}
        ]
        unverified_launch = [
            r.name for r in requirement_results
            if r.launch_blocking and r.status == "unknown"
        ]
        if unverified_launch:
            warnings.append(
                "Launch requirements awaiting manual/runtime verification: "
                + ", ".join(unverified_launch)
            )

        status = self._capability_status(requirement_results)
        readiness = self._readiness(requirement_results)

        return CapabilityAudit(
            key=capability.key,
            name=capability.name,
            purpose=capability.purpose,
            launch_critical=capability.launch_critical,
            priority=capability.priority,
            structural_status=status,
            readiness_percent=readiness,
            blockers=blockers,
            warnings=warnings,
            requirements=requirement_results,
            dependencies=list(capability.dependencies),
            dependency_status={},
            runtime_certified=False,
        )

    def _audit_requirement(
        self,
        requirement: CapabilityRequirement,
        index: dict[str, Any],
    ) -> RequirementAudit:
        patterns = [p.strip() for p in requirement.patterns if str(p).strip()]
        if not patterns:
            return RequirementAudit(
                kind=requirement.kind,
                name=requirement.name,
                description=requirement.description,
                required=requirement.required,
                launch_blocking=requirement.launch_blocking,
                status="unknown",
                confidence="low",
                message="No machine-verifiable pattern is defined; manual or runtime review is required.",
                patterns=[],
                evidence=[],
                manual_review_required=True,
            )

        evidence = self._find_evidence(patterns, index)
        if not evidence:
            return RequirementAudit(
                kind=requirement.kind,
                name=requirement.name,
                description=requirement.description,
                required=requirement.required,
                launch_blocking=requirement.launch_blocking,
                status="missing",
                confidence="high",
                message="No indexed file, symbol, route, import, template, endpoint, or asset matched the requirement patterns.",
                patterns=patterns,
                evidence=[],
                manual_review_required=False,
            )

        broken = [item for item in evidence if item.parse_errors]
        if broken and len(broken) == len(evidence):
            status = "broken"
            confidence = "high"
            message = "Evidence exists, but every matching source has parser errors."
        elif broken:
            status = "partial"
            confidence = "medium"
            message = "Evidence exists, but some matching source files contain parser errors."
        else:
            status = "present"
            confidence = "high" if evidence[0].score >= 80 else "medium"
            message = "Structural evidence was found in the project index. Runtime behavior remains unverified."

        return RequirementAudit(
            kind=requirement.kind,
            name=requirement.name,
            description=requirement.description,
            required=requirement.required,
            launch_blocking=requirement.launch_blocking,
            status=status,
            confidence=confidence,
            message=message,
            patterns=patterns,
            evidence=evidence[:12],
            manual_review_required=status in {"partial", "unknown"},
        )

    def _find_evidence(
        self,
        patterns: list[str],
        index: dict[str, Any],
    ) -> list[RequirementEvidence]:
        found: dict[str, RequirementEvidence] = {}
        for item in index.get("files", []):
            if item.get("status") != "ok":
                continue

            path = str(item.get("path", "")).replace("\\", "/").lower()
            filename = str(item.get("filename", "")).lower()
            symbols = [str(x.get("name", "")) for x in item.get("symbols", [])]
            routes = [str(x.get("path", "")) for x in item.get("routes", [])]
            imports = [str(x) for x in item.get("imports", [])]
            templates = [str(x) for x in item.get("templates", [])]
            endpoints = [str(x) for x in item.get("url_endpoints", [])]
            assets = [str(x) for x in item.get("static_assets", [])]
            references = [str(x) for x in item.get("references", [])]

            searchable = {
                "path": [path],
                "filename": [filename],
                "symbol": symbols,
                "route": routes,
                "import": imports,
                "template": templates,
                "endpoint": endpoints,
                "asset": assets,
                "reference": references,
            }

            score = 0
            reasons: list[str] = []
            for raw_pattern in patterns:
                pattern = raw_pattern.replace("\\", "/").lower()
                pattern_matched = False
                for field_name, values in searchable.items():
                    for value in values:
                        normalized = value.replace("\\", "/").lower()
                        if self._matches(pattern, normalized):
                            pattern_matched = True
                            weight = {
                                "path": 100,
                                "filename": 90,
                                "symbol": 85,
                                "route": 85,
                                "template": 80,
                                "endpoint": 75,
                                "import": 65,
                                "asset": 60,
                                "reference": 55,
                            }[field_name]
                            score = max(score, weight)
                            reasons.append(f"{field_name}:{raw_pattern}")
                            break
                    if pattern_matched:
                        break

            if score:
                found[path] = RequirementEvidence(
                    path=str(item.get("path", "")),
                    score=score,
                    reasons=sorted(set(reasons)),
                    parse_errors=list(item.get("parse_errors", [])),
                    symbols=symbols[:20],
                    routes=routes[:20],
                )

        return sorted(found.values(), key=lambda x: (-x.score, x.path.lower()))

    @staticmethod
    def _matches(pattern: str, value: str) -> bool:
        if any(ch in pattern for ch in "*?["):
            return fnmatch.fnmatch(value, pattern) or fnmatch.fnmatch(value, f"*{pattern}*")
        return pattern in value

    @staticmethod
    def _capability_status(requirements: list[RequirementAudit]) -> str:
        required = [r for r in requirements if r.required]
        if not required:
            return "concept_only"
        if all(r.status == "missing" for r in required):
            return "missing"
        if any(r.status == "broken" and r.launch_blocking for r in required):
            return "present_but_broken"
        if any(r.status == "missing" and r.launch_blocking for r in required):
            return "partially_wired"
        if any(r.status in {"missing", "broken"} for r in required):
            return "partially_wired"
        if any(r.status in {"partial", "unknown"} for r in required):
            return "functional_but_incomplete"
        return "complete"

    @staticmethod
    def _readiness(requirements: list[RequirementAudit]) -> int:
        weights = {"present": 1.0, "partial": 0.6, "unknown": 0.35, "broken": 0.15, "missing": 0.0}
        weighted = []
        for row in requirements:
            importance = 3 if row.launch_blocking else 2 if row.required else 1
            weighted.extend([weights[row.status]] * importance)
        return round(100 * sum(weighted) / len(weighted)) if weighted else 0

    @staticmethod
    def _summary(rows: list[CapabilityAudit]) -> dict[str, Any]:
        statuses: dict[str, int] = {}
        for row in rows:
            statuses[row.structural_status] = statuses.get(row.structural_status, 0) + 1
        launch_rows = [row for row in rows if row.launch_critical]
        blockers = [
            {"capability": row.key, "name": row.name, "blockers": row.blockers}
            for row in launch_rows if row.blockers
        ]
        unverified = [
            {
                "capability": row.key,
                "name": row.name,
                "requirements": [
                    req.name for req in row.requirements
                    if req.launch_blocking and req.status == "unknown"
                ],
            }
            for row in launch_rows
            if any(req.launch_blocking and req.status == "unknown" for req in row.requirements)
        ]
        average = round(sum(r.readiness_percent for r in launch_rows) / len(launch_rows)) if launch_rows else 0
        return {
            "capabilities": len(rows),
            "launch_critical": len(launch_rows),
            "average_launch_structural_readiness": average,
            "launch_blocker_capabilities": len(blockers),
            "launch_blockers": blockers,
            "unverified_launch_capabilities": len(unverified),
            "unverified_launch_requirements": unverified,
            "by_status": dict(sorted(statuses.items())),
        }

    @staticmethod
    def _capability_to_dict(row: CapabilityAudit) -> dict[str, Any]:
        return asdict(row)

    def _save_json(self, payload: dict[str, Any]) -> None:
        path = Path(self.project_indexer.workspace.resolve(self.audit_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _save_markdown(self, payload: dict[str, Any]) -> None:
        path = Path(self.project_indexer.workspace.resolve(self.report_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Kushwell Capability Health Report",
            "",
            f"Generated: {payload['generated_at']}",
            "",
            f"> {payload['disclaimer']}",
            "",
            "## Summary",
            "",
            f"- Capabilities audited: {payload['summary']['capabilities']}",
            f"- Launch-critical capabilities: {payload['summary']['launch_critical']}",
            f"- Average launch structural readiness: {payload['summary']['average_launch_structural_readiness']}%",
            f"- Capabilities with launch blockers: {payload['summary']['launch_blocker_capabilities']}",
            f"- Capabilities with unverified launch requirements: {payload['summary']['unverified_launch_capabilities']}",
            "",
        ]

        for cap in payload["capabilities"]:
            lines.extend([
                f"## {cap['name']}",
                "",
                f"**Structural status:** `{cap['structural_status']}`  ",
                f"**Structural readiness:** {cap['readiness_percent']}%  ",
                f"**Launch critical:** {'Yes' if cap['launch_critical'] else 'No'}",
                "",
                cap["purpose"],
                "",
            ])
            if cap["blockers"]:
                lines.append("**Launch blockers:** " + ", ".join(cap["blockers"]))
                lines.append("")
            lines.append("| Requirement | Kind | Status | Evidence |")
            lines.append("|---|---|---|---|")
            for req in cap["requirements"]:
                evidence = "<br>".join(x["path"] for x in req["evidence"][:3]) or "Manual review"
                lines.append(f"| {req['name']} | {req['kind']} | {req['status']} | {evidence} |")
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")


__all__ = ["CapabilityAuditor", "DEFAULT_AUDIT_PATH", "DEFAULT_REPORT_PATH"]
