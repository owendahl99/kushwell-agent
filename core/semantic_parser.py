from __future__ import annotations

import re

from core.semantic_request import SemanticRequest


class SemanticParser:
    EVIDENCE_ANALYTICS_PHRASES = {
        "how much evidence",
        "how many outcomes",
        "how many observations",
        "patient evidence",
        "patient outcomes",
        "evidence coverage",
        "data coverage",
        "sample size",
        "success rate",
        "confidence interval",
        "statistically significant",
        "statistical significance",
        "meaningful outcomes",
        "how are we doing",
        "how much are we collecting",
        "what have we collected",
        "outcome count",
    }

    ACQUISITION_STATUS_PHRASES = {
        "acquisition status",
        "kap status",
        "acquisition health",
        "what is kap doing",
        "what did kap do",
        "acquisition dashboard",
    }

    ACQUISITION_RUN_PHRASES = {
        "acquisition runs",
        "run ledger",
        "recent acquisition",
        "failed acquisition",
        "last acquisition",
        "acquisition history",
    }

    ACQUISITION_PLAN_PHRASES = {
        "plan acquisition",
        "plan a crawl",
        "dry run acquisition",
        "preview acquisition",
        "prepare acquisition",
    }

    ACQUISITION_EXECUTE_PHRASES = {
        "run acquisition",
        "run the acquisition",
        "update california inventory",
        "acquire california products",
        "start acquisition",
    }

    RECOMMENDATION_PHRASES = {
        "what should i take",
        "what should i use",
        "what can i take",
        "recommend",
        "recommendation",
        "recommend a product",
        "which product",
        "best product",
        "product for",
        "help with",
        "relief for",
        "assist with",
        "chemical profile corresponds",
        "chemical profile for",
        "what works for",
        "treat",
    }

    OUTCOME_ALIASES = {
        "sleep": {
            "sleep",
            "insomnia",
            "difficulty falling asleep",
            "difficulty staying asleep",
            "restless sleep",
            "sleep disruption",
        },
        "pain_control": {
            "pain",
            "back pain",
            "chronic pain",
            "arthritis",
            "joint pain",
            "muscle pain",
            "inflammation",
            "headache",
            "migraine",
        },
        "anxiety": {
            "anxiety",
            "anxious",
            "stress",
            "calm",
            "relaxation",
        },
        "appetite": {
            "appetite",
            "poor appetite",
            "appetite loss",
            "hunger",
            "nausea",
        },
        "mood": {
            "mood",
            "depression",
            "emotional wellbeing",
            "emotional well-being",
            "uplift",
        },
        "energy": {
            "energy",
            "fatigue",
            "low energy",
            "motivation",
        },
        "focus": {
            "focus",
            "clarity",
            "concentration",
        },
    }

    def parse(self, user_input: str) -> dict:
        text = str(user_input or "").strip()
        normalized = self._normalize(text)

        action = self._extract_action(normalized)
        subject = self._extract_subject(normalized, action)
        source = self._extract_source(normalized)
        destination = self._extract_destination(normalized)
        filters = self._extract_filters(normalized)
        outcomes = self._extract_outcomes(normalized)
        operations = self._extract_operations(action)
        deliverable = self._extract_deliverable(action, normalized)
        constraints = self._extract_constraints(normalized)
        search_term = self._extract_search_term(text)

        destructive = action in {
            "move",
            "delete",
            "write",
            "cleanup",
        }

        no_changes = bool(
            constraints.get("no_changes")
        )

        return SemanticRequest(
            action=action,
            subject=subject,
            source=source,
            destination=destination,
            filters=filters,
            constraints={
                **constraints,
                "operations": operations,
                "deliverable": deliverable,
                "search_term": search_term,
                "outcomes": outcomes,
                "overwrite": False,
                "dry_run": no_changes or destructive,
            },
            requires_confirmation=no_changes or destructive,
            confidence=self._confidence(
                action=action,
                subject=subject,
                source=source,
                operations=operations,
                outcomes=outcomes,
            ),
            original_request=text,
        ).to_dict()

    # =========================================================
    # NORMALIZATION
    # =========================================================

    def _normalize(self, text: str) -> str:
        return re.sub(
            r"\s+",
            " ",
            str(text or "").lower(),
        ).strip()

    # =========================================================
    # ACTION CLASSIFICATION
    # =========================================================

    def _extract_action(self, text: str) -> str:
        if any(
            phrase in text
            for phrase in self.ACQUISITION_EXECUTE_PHRASES
        ):
            return "run_acquisition"

        if any(
            phrase in text
            for phrase in self.ACQUISITION_PLAN_PHRASES
        ):
            return "plan_acquisition"

        if any(
            phrase in text
            for phrase in self.ACQUISITION_RUN_PHRASES
        ):
            return "acquisition_runs"

        if any(
            phrase in text
            for phrase in self.ACQUISITION_STATUS_PHRASES
        ):
            return "acquisition_status"

        # Literal filesystem text search.
        if any(
            phrase in text
            for phrase in {
                "find the term",
                "search for text",
                "find text",
                "contains the phrase",
                "contains the term",
            }
        ):
            return "search"

        if any(
            phrase in text
            for phrase in self.EVIDENCE_ANALYTICS_PHRASES
        ):
            return "analyze_evidence"

        if any(
            phrase in text
            for phrase in self.RECOMMENDATION_PHRASES
        ):
            return "recommend"

        if any(
            phrase in text
            for phrase in {
                "move ",
                "relocate ",
                "put into ",
            }
        ):
            return "move"

        if any(
            phrase in text
            for phrase in {
                "delete ",
                "remove ",
            }
        ):
            return "delete"

        if any(
            phrase in text
            for phrase in {
                "read file",
                "open file",
                "show file",
            }
        ):
            return "read"

        if any(
            phrase in text
            for phrase in {
                "list files",
                "show files",
                "what is in",
                "what's in",
            }
        ):
            return "list"

        return "answer"

    def _extract_subject(
        self,
        text: str,
        action: str,
    ) -> str:
        if action in {
            "acquisition_status",
            "acquisition_runs",
            "plan_acquisition",
            "run_acquisition",
        }:
            return "acquisition_operations"

        if action == "recommend":
            return "symptom_treatment"

        if action == "analyze_evidence":
            return "patient_outcomes"

        if action == "search":
            return "files"

        if "template" in text:
            return "templates"

        if "route" in text:
            return "routes"

        return "project_knowledge"

    # =========================================================
    # OUTCOMES
    # =========================================================

    def _extract_outcomes(
        self,
        text: str,
    ) -> list[str]:
        outcomes = []

        for canonical, aliases in self.OUTCOME_ALIASES.items():
            if any(alias in text for alias in aliases):
                outcomes.append(canonical)

        return outcomes

    # =========================================================
    # OPERATIONS
    # =========================================================

    def _extract_operations(
        self,
        action: str,
    ) -> list[str]:
        operation_map = {
            "acquisition_status": [
                "query_acquisition_status",
                "answer_question",
            ],
            "acquisition_runs": [
                "query_acquisition_runs",
                "answer_question",
            ],
            "plan_acquisition": [
                "plan_product_acquisition",
                "answer_question",
            ],
            "run_acquisition": [
                "run_product_acquisition",
                "answer_question",
            ],
            "search": [
                "text_search",
            ],
            "recommend": [
                "query_recommendations",
                "answer_question",
            ],
            "analyze_evidence": [
                "query_patient_evidence",
                "answer_question",
            ],
            "answer": [
                "answer_question",
            ],
            "list": [
                "inventory",
            ],
            "read": [
                "read_file",
            ],
            "move": [
                "move_file",
            ],
            "delete": [
                "delete_file",
            ],
        }

        return operation_map.get(
            action,
            ["answer_question"],
        )

    # =========================================================
    # FILESYSTEM HELPERS
    # =========================================================

    def _extract_search_term(
        self,
        text: str,
    ) -> str | None:
        match = re.search(r'"([^"]+)"', text)

        if match:
            return match.group(1).strip()

        match = re.search(r"'([^']+)'", text)

        if match:
            return match.group(1).strip()

        match = re.search(
            r"find\s+(?:the\s+term\s+)?"
            r"(.+?)(?:\s+in\s+|\s+inside\s+|$)",
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(1).strip()

        return None

    def _extract_source(
        self,
        text: str,
    ) -> str:
        explicit = self._extract_explicit_workspace_path(
            text
        )

        if explicit:
            return explicit

        if "template" in text:
            return "workspace:/templates"

        if "route" in text:
            return "workspace:/routes"

        if "core" in text:
            return "workspace:/core"

        return "workspace:/"

    def _extract_explicit_workspace_path(
        self,
        text: str,
    ) -> str | None:
        patterns = [
            r"(templates/[a-zA-Z0-9_\-/]+)",
            r"(routes/[a-zA-Z0-9_\-/]+)",
            r"(core/[a-zA-Z0-9_\-/]+)",
            r"(static/[a-zA-Z0-9_\-/]+)",
            r"(services/[a-zA-Z0-9_\-/]+)",
            r"(models/[a-zA-Z0-9_\-/]+)",
            r"(products/[a-zA-Z0-9_\-/]+)",
            r"(recommendations/[a-zA-Z0-9_\-/]+)",
            r"(heatmap/[a-zA-Z0-9_\-/]+)",
            r"(chemistry/[a-zA-Z0-9_\-/]+)",
            r"(literature/[a-zA-Z0-9_\-/]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)

            if match:
                return (
                    "workspace:/"
                    + match.group(1).strip("/")
                )

        return None

    def _extract_destination(
        self,
        text: str,
    ) -> str | None:
        match = re.search(
            r"(?:to|into|in)\s+"
            r"(templates/[a-zA-Z0-9_\-/]+)",
            text,
        )

        if match:
            return (
                "workspace:/"
                + match.group(1).strip("/")
            )

        return None

    def _extract_filters(
        self,
        text: str,
    ) -> list[str]:
        filters = []

        if "recursive" in text or "every file" in text:
            filters.append("recursive")

        if "source" in text or "sources" in text:
            filters.append("requires_sources")

        return filters

    # =========================================================
    # REQUEST METADATA
    # =========================================================

    def _extract_deliverable(
        self,
        action: str,
        text: str,
    ) -> str:
        if action == "recommend":
            return "recommendation"

        if action == "analyze_evidence":
            return "evidence_report"

        if action == "search":
            return "search_results"

        if "summary" in text:
            return "summary"

        return "answer"

    def _extract_constraints(
        self,
        text: str,
    ) -> dict:
        return {
            "no_changes": any(
                phrase in text
                for phrase in {
                    "do not change",
                    "don't change",
                    "do not delete",
                    "don't delete",
                    "do not write",
                    "don't write",
                    "dry run",
                    "no changes",
                }
            ),
            "manual_review": (
                "manual review" in text
            ),
        }

    def _confidence(
        self,
        action: str,
        subject: str,
        source: str,
        operations: list[str],
        outcomes: list[str],
    ) -> int:
        score = 30

        if action:
            score += 20

        if subject:
            score += 15

        if operations:
            score += 15

        if outcomes:
            score += 15

        if source != "workspace:/":
            score += 5

        return min(score, 100)


semantic_parser = SemanticParser()