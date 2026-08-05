from __future__ import annotations

from core.capabilities.capability_registry import (
    capability_registry,
)
from core.knowledge import knowledge_registry

# Load capability packs.
import core.capabilities.inventory  # noqa: F401
import core.capabilities.dependency_analysis  # noqa: F401
import core.capabilities.summarize  # noqa: F401
import core.capabilities.recommend  # noqa: F401
import core.capabilities.report  # noqa: F401


class SemanticPlanner:
    def _finalize(self, graph: dict, request: dict) -> dict:
        """Attach governed knowledge ownership without changing DAG execution."""
        graph = graph or {"nodes": []}
        graph["request"] = request
        graph["knowledge_context"] = knowledge_registry.request_context(request)
        return graph

    def plan(self, request: dict) -> dict:
        action = request.get("action")
        source = request.get(
            "source",
            "workspace:/",
        )
        constraints = (
            request.get("constraints") or {}
        )
        outcomes = constraints.get("outcomes") or []
        question = request.get(
            "original_request",
            "",
        )

        # =====================================================
        # KAP ACQUISITION OPERATIONS
        # =====================================================

        if action == "acquisition_status":
            return self._finalize({
                "nodes": [
                    {
                        "id": "acquisition_status",
                        "tool": "query_acquisition_status",
                        "args": {"requested_by": "atlas"},
                        "deps": [],
                    },
                    {
                        "id": "final_answer",
                        "tool": "answer_question",
                        "args": {
                            "question": question,
                            "answer_mode": "acquisition_status",
                        },
                        "deps": ["acquisition_status"],
                    },
                ],
                "request": request,
            }, request)

        if action == "acquisition_runs":
            return self._finalize({
                "nodes": [
                    {
                        "id": "acquisition_runs",
                        "tool": "query_acquisition_runs",
                        "args": {"limit": 25},
                        "deps": [],
                    },
                    {
                        "id": "final_answer",
                        "tool": "answer_question",
                        "args": {
                            "question": question,
                            "answer_mode": "acquisition_runs",
                        },
                        "deps": ["acquisition_runs"],
                    },
                ],
                "request": request,
            }, request)

        if action == "plan_acquisition":
            return self._finalize({
                "nodes": [
                    {
                        "id": "acquisition_plan",
                        "tool": "plan_product_acquisition",
                        "args": {
                            "jurisdiction_code": "CA",
                            "provider_key": "weedmaps",
                            "start_id": 1,
                            "batch_size": 25,
                            "max_batches": 1,
                            "triggered_by": "atlas",
                        },
                        "deps": [],
                    },
                    {
                        "id": "final_answer",
                        "tool": "answer_question",
                        "args": {
                            "question": question,
                            "answer_mode": "acquisition_plan",
                        },
                        "deps": ["acquisition_plan"],
                    },
                ],
                "request": request,
            }, request)

        if action == "run_acquisition":
            # Safety default: Atlas interprets an ordinary natural-language
            # request as a recorded dry run. A future confirmed admin action
            # may explicitly set dry_run=False and confirm_live=True.
            return self._finalize({
                "nodes": [
                    {
                        "id": "acquisition_execution",
                        "tool": "run_product_acquisition",
                        "args": {
                            "jurisdiction_code": "CA",
                            "provider_key": "weedmaps",
                            "start_id": 1,
                            "batch_size": 25,
                            "max_batches": 1,
                            "dry_run": True,
                            "confirm_live": False,
                            "triggered_by": "atlas",
                        },
                        "deps": [],
                    },
                    {
                        "id": "final_answer",
                        "tool": "answer_question",
                        "args": {
                            "question": question,
                            "answer_mode": "acquisition_execution",
                        },
                        "deps": ["acquisition_execution"],
                    },
                ],
                "request": request,
            }, request)

        # =====================================================
        # RECOMMENDATION REQUEST
        # =====================================================

        if action == "recommend":
            return self._finalize({
                "nodes": [
                    {
                        "id": "recommendation_data",
                        "tool": "query_recommendations",
                        "args": {
                            "question": question,
                            "outcomes": outcomes,
                            "limit_per_outcome": 5,
                            "candidate_limit": 2000,
                        },
                        "deps": [],
                    },
                    {
                        "id": "final_answer",
                        "tool": "answer_question",
                        "args": {
                            "question": question,
                            "answer_mode": "recommendation",
                        },
                        "deps": [
                            "recommendation_data",
                        ],
                    },
                ],
                "request": request,
            }, request)

        # =====================================================
        # PATIENT-EVIDENCE ANALYTICS
        # =====================================================

        if action == "analyze_evidence":
            return self._finalize({
                "nodes": [
                    {
                        "id": "patient_evidence",
                        "tool": "query_project_data",
                        "args": {
                            "question": question,
                            "outcomes": outcomes,
                            "limit_per_outcome": 50,
                        },
                        "deps": [],
                    },
                    {
                        "id": "final_answer",
                        "tool": "answer_question",
                        "args": {
                            "question": question,
                            "answer_mode": "evidence_analytics",
                        },
                        "deps": [
                            "patient_evidence",
                        ],
                    },
                ],
                "request": request,
            }, request)

        # =====================================================
        # RECURSIVE LITERAL TEXT SEARCH
        # =====================================================

        if action == "search":
            return self._finalize({
                "nodes": [
                    {
                        "id": "text_search",
                        "tool": "search_files",
                        "args": {
                            "path": source,
                            "term": constraints.get(
                                "search_term"
                            ),
                        },
                        "deps": [],
                    }
                ],
                "request": request,
            }, request)

        # =====================================================
        # DIRECTORY LIST
        # =====================================================

        if action == "list":
            return self._finalize({
                "nodes": [
                    {
                        "id": "inventory_source",
                        "tool": "list_directory",
                        "args": {
                            "path": source,
                        },
                        "deps": [],
                    }
                ],
                "request": request,
            }, request)

        # =====================================================
        # SINGLE FILE READ
        # =====================================================

        if action == "read":
            return self._finalize({
                "nodes": [
                    {
                        "id": "read_source",
                        "tool": "read_file",
                        "args": {
                            "path": source,
                        },
                        "deps": [],
                    }
                ],
                "request": request,
            }, request)

        # =====================================================
        # GENERAL PROJECT QUESTION
        # =====================================================

        if action == "answer":
            return self._finalize({
                "nodes": [
                    {
                        "id": "project_search",
                        "tool": "search_project_index",
                        "args": {
                            "query": question,
                            "limit": 25,
                        },
                        "deps": [],
                    },
                    {
                        "id": "project_relationships",
                        "tool": "get_project_relationships",
                        "args": {
                            "query": question,
                            "limit": 15,
                            "include_reverse": True,
                        },
                        "deps": [],
                    },
                    {
                        "id": "final_answer",
                        "tool": "answer_question",
                        "args": {
                            "question": question,
                            "answer_mode": "project_knowledge",
                        },
                        "deps": [
                            "project_search",
                            "project_relationships",
                        ],
                    },
                ],
                "request": request,
            }, request)

        nodes: list[dict] = []

        for capability in capability_registry.matching(
            request
        ):
            nodes = capability.builder(
                request,
                nodes,
            )

        if not nodes:
            nodes = [
                {
                    "id": "inventory_source",
                    "tool": "list_directory",
                    "args": {
                        "path": source,
                    },
                    "deps": [],
                }
            ]

        return self._finalize({
            "nodes": self._dedupe_nodes(nodes),
            "request": request,
        }, request)

    def _dedupe_nodes(
        self,
        nodes: list[dict],
    ) -> list[dict]:
        seen = set()
        clean = []

        for node in nodes:
            node_id = node.get("id")

            if not node_id:
                continue

            if node_id in seen:
                continue

            seen.add(node_id)
            clean.append(node)

        return clean


semantic_planner = SemanticPlanner()