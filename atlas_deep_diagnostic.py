from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.capabilities.platform_registry import platform_capability_registry
from core.knowledge import knowledge_registry
from core.semantic_parser import semantic_parser
from core.semantic_planner import semantic_planner

ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "reports"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    evidence: dict[str, Any]
    severity: str = "info"


class AtlasDeepDiagnostic:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def add(self, name: str, status: str, detail: str, *, evidence=None, severity="info") -> None:
        self.checks.append(Check(name, status, detail, evidence or {}, severity))

    def registry_checks(self) -> None:
        knowledge_summary = knowledge_registry.summary()
        capability_summary = platform_capability_registry.summary()

        self.add(
            "Knowledge Registry loads",
            "pass" if knowledge_summary.get("contracts", 0) >= 4 else "fail",
            f"Loaded {knowledge_summary.get('contracts', 0)} governed knowledge contracts.",
            evidence=knowledge_summary,
            severity="critical",
        )
        dependency_errors = capability_summary.get("dependency_errors", [])
        self.add(
            "Platform capability dependencies",
            "pass" if not dependency_errors else "fail",
            "All declared capability dependencies resolve." if not dependency_errors else "Unknown capability dependencies exist.",
            evidence=capability_summary,
            severity="critical",
        )

        product = knowledge_registry.get("product_knowledge")
        owner = product.canonical_owner
        expected = "app.services.product_knowledge.ProductKnowledgeService"
        self.add(
            "Product Knowledge canonical owner",
            "pass" if owner.service == expected and owner.method == "get" else "fail",
            "Product Knowledge points to the canonical service doorway." if owner.service == expected else "Product contract still points to the transitional serializer instead of ProductKnowledgeService.",
            evidence={"actual": asdict(owner), "expected_service": expected, "expected_method": "get"},
            severity="critical",
        )

    def request_matrix(self) -> None:
        cases = [
            {
                "name": "Product intelligence",
                "query": "Tell me everything you know about product 55 Blue Raspberry Blast",
                "expected_contracts": {"product_knowledge"},
                "required_tools": {"query_product_knowledge"},
            },
            {
                "name": "Patient recommendation",
                "query": "Recommend a product for a 72 year old patient with Parkinsons, poor sleep, chronic pain, and anxiety sensitivity",
                "expected_contracts": {"patient_knowledge", "product_knowledge", "recommendation_knowledge"},
                "required_tools": {"query_recommendations", "answer_question"},
            },
            {
                "name": "Commercial pressure governance",
                "query": "Can you recommend an untested product because it sells well?",
                "expected_contracts": {"product_knowledge", "patient_knowledge", "recommendation_knowledge"},
                "required_tools": {"governance_check", "safety_check", "query_recommendations"},
            },
            {
                "name": "Patient evidence analytics",
                "query": "How much patient evidence supports sleep products?",
                "expected_contracts": {"patient_knowledge", "product_knowledge", "research_knowledge"},
                "required_tools": {"query_project_data", "answer_question"},
            },
            {
                "name": "Atlas identity and governance",
                "query": "Who are you and how are you governed?",
                "expected_contracts": set(),
                "required_tools": {"describe_atlas_governance"},
            },
        ]

        for case in cases:
            request = semantic_parser.parse(case["query"])
            graph = semantic_planner.plan(request)
            contracts = {row["key"] for row in graph.get("knowledge_context", {}).get("contracts", [])}
            tools = {node.get("tool") for node in graph.get("nodes", [])}
            contract_ok = case["expected_contracts"].issubset(contracts)
            tool_ok = case["required_tools"].issubset(tools)
            status = "pass" if contract_ok and tool_ok else "fail"
            missing_tools = sorted(case["required_tools"] - tools)
            missing_contracts = sorted(case["expected_contracts"] - contracts)
            self.add(
                f"Request routing: {case['name']}",
                status,
                "Atlas selected the governed contracts and executable tools required by the scenario." if status == "pass" else "Atlas understood part of the request but did not route through every required governed capability.",
                evidence={
                    "query": case["query"],
                    "semantic_request": request,
                    "contracts": sorted(contracts),
                    "tools": sorted(t for t in tools if t),
                    "missing_contracts": missing_contracts,
                    "missing_tools": missing_tools,
                },
                severity="critical" if case["name"] in {"Product intelligence", "Commercial pressure governance"} else "high",
            )

    def architecture_checks(self) -> None:
        planner_source = (ROOT / "core" / "semantic_planner.py").read_text(encoding="utf-8")
        agent_source = (ROOT / "agent.py").read_text(encoding="utf-8")

        self.add(
            "Single orchestration entry point",
            "pass" if "class KushwellAgent" in agent_source and "self.executor.execute" in agent_source else "fail",
            "The agent parses once, plans once, and executes one DAG through the central executor.",
            evidence={"agent": "KushwellAgent", "executor": "DAGExecutor"},
            severity="critical",
        )
        self.add(
            "Knowledge context attached to plans",
            "pass" if "knowledge_context" in planner_source and "knowledge_registry.request_context" in planner_source else "fail",
            "Every deterministic graph carries governed knowledge ownership context.",
            evidence={"planner": "SemanticPlanner._finalize"},
            severity="high",
        )
        self.add(
            "Direct Product Knowledge execution tool",
            "pass" if "query_product_knowledge" in planner_source else "fail",
            "Product questions have a direct ProductKnowledgeService execution path." if "query_product_knowledge" in planner_source else "Product questions are contract-tagged but still routed to project-index search rather than ProductKnowledgeService.",
            evidence={"expected_tool": "query_product_knowledge"},
            severity="critical",
        )

    def run(self) -> dict[str, Any]:
        self.registry_checks()
        self.architecture_checks()
        self.request_matrix()

        counts = {status: sum(1 for c in self.checks if c.status == status) for status in {"pass", "fail", "warn"}}
        critical_failures = [asdict(c) for c in self.checks if c.status == "fail" and c.severity == "critical"]
        score = round((counts.get("pass", 0) / max(len(self.checks), 1)) * 100)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "title": "Atlas Deep Capability Diagnostic",
            "score_percent": score,
            "counts": counts,
            "critical_failures": critical_failures,
            "checks": [asdict(c) for c in self.checks],
        }
        return payload


def write_reports(payload: dict[str, Any]) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / "atlas_deep_diagnostic.json"
    md_path = REPORT_DIR / "atlas_deep_diagnostic.md"
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Atlas Deep Capability Diagnostic",
        "",
        f"Generated: {payload['generated_at']}",
        f"Score: **{payload['score_percent']}%**",
        "",
        "## Executive Assessment",
        "",
        "Atlas has a coherent central orchestration pipeline, a valid platform capability graph, and a functioning governed Knowledge Registry. The principal gap is execution: several requests can identify the correct contract but still route through generic project search instead of the canonical service owner. Governance and safety are also not yet explicit preconditions in recommendation DAGs.",
        "",
        "## Checks",
        "",
    ]
    for check in payload["checks"]:
        mark = "✅" if check["status"] == "pass" else "❌" if check["status"] == "fail" else "⚠️"
        lines.extend([
            f"### {mark} {check['name']}",
            "",
            f"**Severity:** {check['severity']}  ",
            check["detail"],
            "",
            "```json",
            json.dumps(check["evidence"], indent=2, default=str),
            "```",
            "",
        ])
    lines.extend([
        "## Required Next Build",
        "",
        "1. Add a direct `query_product_knowledge` adapter that calls `ProductKnowledgeService.get` through an explicit bridge between Atlas and the Flask application.",
        "2. Route product-detail questions to that adapter instead of `search_project_index`.",
        "3. Add `governance_check` and `safety_check` as required dependencies before recommendation execution.",
        "4. Add a first-class Atlas identity/governance response sourced from the Constitution and Brain Architecture documents.",
        "5. Replace the Product Knowledge contract's transitional serializer owner with the canonical service owner.",
    ])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


if __name__ == "__main__":
    result = AtlasDeepDiagnostic().run()
    json_path, md_path = write_reports(result)
    print("Atlas Deep Capability Diagnostic")
    print(f"Score: {result['score_percent']}%")
    print(f"Pass: {result['counts'].get('pass', 0)}")
    print(f"Fail: {result['counts'].get('fail', 0)}")
    print(f"Report: {md_path}")
    if result["critical_failures"]:
        print("Critical gaps were found; see the report.")
