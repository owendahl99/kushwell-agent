from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.knowledge import knowledge_registry


DEFAULT_ATLAS_JSON = "workspace:/.brain/atlas_dashboard.json"
DEFAULT_ATLAS_MD = "workspace:/.brain/atlas_dashboard.md"


class AtlasConsole:
    """Executive and architectural control center for Kushwell development.

    Atlas converts capability-audit evidence into a concise launch dashboard,
    prioritized blockers, and a recommended next-work list. It does not certify
    runtime, usability, clinical correctness, or production readiness.
    """

    STATUS_WEIGHT = {
        "complete": 100,
        "functional_but_incomplete": 80,
        "partially_wired": 55,
        "present_but_broken": 30,
        "concept_only": 15,
        "missing": 0,
        "unknown": 10,
        "legacy": 0,
    }

    def __init__(
        self,
        auditor: Any,
        json_path: str = DEFAULT_ATLAS_JSON,
        markdown_path: str = DEFAULT_ATLAS_MD,
    ) -> None:
        self.auditor = auditor
        self.json_path = json_path
        self.markdown_path = markdown_path

    def build(self, *, rebuild_index: bool = False, persist: bool = True) -> dict[str, Any]:
        audit = self.auditor.audit_all(rebuild_index=rebuild_index, persist=persist)
        capabilities = audit.get("capabilities", [])

        launch_caps = [c for c in capabilities if c.get("launch_critical")]
        deferred_caps = [c for c in capabilities if not c.get("launch_critical")]

        launch_readiness = self._weighted_readiness(launch_caps)
        platform_health = self._weighted_readiness(capabilities)
        blockers = self._collect_blockers(launch_caps)
        priorities = self._prioritize(launch_caps)

        payload = {
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "name": "Kushwell Atlas",
            "disclaimer": (
                "Structural evidence only. Atlas does not certify runtime behavior, "
                "clinical correctness, security, usability, or production readiness."
            ),
            "headline": {
                "platform_health_percent": platform_health,
                "launch_readiness_percent": launch_readiness,
                "capabilities": len(capabilities),
                "launch_critical": len(launch_caps),
                "deferred": len(deferred_caps),
                "launch_blockers": len(blockers),
                "runtime_certified": False,
            },
            "status_counts": self._status_counts(capabilities),
            "launch_status_counts": self._status_counts(launch_caps),
            "capability_heatmap": [self._heatmap_row(c) for c in capabilities],
            "launch_blockers": blockers,
            "recommended_next_work": priorities,
            "deferred_capabilities": [
                {"key": c.get("key"), "name": c.get("name"), "status": c.get("structural_status")}
                for c in deferred_caps
            ],
            "knowledge_registry": knowledge_registry.summary(),
            "source_audit": {
                "generated_at": audit.get("generated_at"),
                "index_generated_at": audit.get("index_generated_at"),
                "summary": audit.get("summary", {}),
            },
        }

        if persist:
            self._save_json(payload)
            self._save_markdown(payload)
        return payload

    def _weighted_readiness(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        numerator = 0.0
        denominator = 0.0
        for row in rows:
            priority = max(1, int(row.get("priority", 1)))
            readiness = int(row.get("readiness_percent", self.STATUS_WEIGHT.get(row.get("structural_status"), 0)))
            numerator += readiness * priority
            denominator += priority
        return round(numerator / denominator) if denominator else 0

    @staticmethod
    def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            status = str(row.get("structural_status", "unknown"))
            counts[status] = counts.get(status, 0) + 1
        return dict(sorted(counts.items()))

    @staticmethod
    def _heatmap_row(row: dict[str, Any]) -> dict[str, Any]:
        status = row.get("structural_status", "unknown")
        marker = {
            "complete": "green",
            "functional_but_incomplete": "green",
            "partially_wired": "yellow",
            "present_but_broken": "red",
            "concept_only": "gray",
            "missing": "red",
            "unknown": "gray",
            "legacy": "gray",
        }.get(status, "gray")
        return {
            "key": row.get("key"),
            "name": row.get("name"),
            "status": status,
            "readiness_percent": row.get("readiness_percent", 0),
            "launch_critical": bool(row.get("launch_critical")),
            "marker": marker,
            "blocker_count": len(row.get("blockers", [])),
            "warning_count": len(row.get("warnings", [])),
        }

    @staticmethod
    def _collect_blockers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in rows:
            for blocker in row.get("blockers", []):
                out.append({
                    "capability_key": row.get("key"),
                    "capability": row.get("name"),
                    "priority": row.get("priority", 0),
                    "readiness_percent": row.get("readiness_percent", 0),
                    "blocker": blocker,
                })
        return sorted(out, key=lambda x: (-int(x["priority"]), int(x["readiness_percent"]), str(x["capability"])))

    @staticmethod
    def _prioritize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for row in rows:
            blockers = row.get("blockers", [])
            warnings = row.get("warnings", [])
            if not blockers and not warnings and row.get("structural_status") in {"complete", "functional_but_incomplete"}:
                continue
            impact = int(row.get("priority", 1)) * 10 + len(blockers) * 20 + len(warnings) * 2
            candidates.append({
                "capability_key": row.get("key"),
                "capability": row.get("name"),
                "status": row.get("structural_status"),
                "readiness_percent": row.get("readiness_percent", 0),
                "impact_score": impact,
                "blockers_removed_if_completed": len(blockers),
                "top_blockers": blockers[:3],
                "top_warnings": warnings[:3],
                "reason": (
                    f"Launch-critical priority {row.get('priority', 0)}; "
                    f"{len(blockers)} blocker(s), {len(warnings)} warning(s)."
                ),
            })
        return sorted(candidates, key=lambda x: (-int(x["impact_score"]), int(x["readiness_percent"])))[:10]

    def _resolve(self, value: str) -> Path:
        return Path(self.auditor.project_indexer.workspace.resolve(value))

    def _save_json(self, payload: dict[str, Any]) -> None:
        path = self._resolve(self.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _save_markdown(self, payload: dict[str, Any]) -> None:
        h = payload["headline"]
        lines = [
            "# Kushwell Atlas",
            "",
            f"Generated: {payload['generated_at']}",
            "",
            "## Executive Snapshot",
            "",
            f"- Platform structural health: **{h['platform_health_percent']}%**",
            f"- Launch structural readiness: **{h['launch_readiness_percent']}%**",
            f"- Launch blockers: **{h['launch_blockers']}**",
            f"- Capabilities: **{h['capabilities']}**",
            f"- Launch-critical capabilities: **{h['launch_critical']}**",
            f"- Deferred capabilities: **{h['deferred']}**",
            f"- Knowledge contracts: **{payload['knowledge_registry']['contracts']}**",
            "",
            "> Structural evidence only; runtime and production readiness remain unverified.",
            "",
            "## Capability Heat Map",
            "",
        ]
        for row in payload["capability_heatmap"]:
            flag = "LAUNCH" if row["launch_critical"] else "DEFERRED"
            lines.append(
                f"- **{row['name']}** — {row['readiness_percent']}% — "
                f"{row['status']} — {flag}"
            )
        lines += ["", "## Launch Blockers", ""]
        if payload["launch_blockers"]:
            for item in payload["launch_blockers"]:
                lines.append(f"- **{item['capability']}**: {item['blocker']}")
        else:
            lines.append("- No structural launch blockers detected.")
        lines += ["", "## Recommended Next Work", ""]
        for i, item in enumerate(payload["recommended_next_work"], 1):
            lines.append(
                f"{i}. **{item['capability']}** — {item['reason']} "
                f"Current readiness: {item['readiness_percent']}%."
            )
        path = self._resolve(self.markdown_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
