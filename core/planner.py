from __future__ import annotations

from typing import Any


class Planner:
    """
    Converts a user request + inventory result into a focused analysis plan.

    V1 goal:
    - Stop dumping inventory.
    - Select relevant file categories.
    - Produce a second-stage DAG that reads useful files only.
    """

    def plan(
        self,
        request: dict[str, Any],
        inventory: dict[str, Any],
    ) -> dict[str, Any]:

        text = (request.get("original_request") or "").lower()

        if self._is_recommendation_pipeline_request(text):
            return {
                "analysis_type": "recommendation_pipeline",
                "target_categories": {
                    "api",
                    "service",
                    "model",
                    "serializer",
                    "utility",
                    "route",
                },
                "keywords": {
                    "recommend",
                    "recommendation",
                    "rank",
                    "ranking",
                    "score",
                    "scoring",
                    "product",
                    "symptom",
                    "chem",
                    "chemistry",
                    "terpene",
                    "heatmap",
                    "resolve",
                    "evidence",
                },
                "max_files": 12,
            }

        return {
            "analysis_type": "general",
            "target_categories": set(),
            "keywords": set(),
            "max_files": 20,
        }

    def _is_recommendation_pipeline_request(self, text: str) -> bool:
        return (
            "recommendation" in text
            or "recommend" in text
            or "product recommendation" in text
        )


planner = Planner()