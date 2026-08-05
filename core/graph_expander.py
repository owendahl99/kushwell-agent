from __future__ import annotations

import re
from typing import Any

from core.file_classifier import file_classifier
from core.planner import planner
from core.project_filters import should_read


class GraphExpander:
    MAX_DIRECTORY_NODES = 18
    MIN_FOCUSED_SCORE = 12

    def expand(
        self,
        request: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        operations = (
            request.get("constraints", {}).get(
                "operations",
                [],
            )
        )
        source = request.get(
            "source",
            "workspace:/",
        )
        results = result.get(
            "results",
            {},
        ) or {}
        action = request.get("action")
        subject = request.get("subject")

        # Recommendation and patient-evidence graphs are complete
        # when created by SemanticPlanner.
        if action in {
            "recommend",
            "analyze_evidence",
        }:
            return None

        nodes: list[dict[str, Any]] = []

        live_query_exists = any(
            isinstance(item, dict)
            and item.get("tool") == "query_project_data"
            and item.get("status") == "success"
            for item in results.values()
        )

        # Only patient-outcome knowledge questions should automatically
        # query chemical_outcome_summary.
        should_query_patient_data = (
            action == "answer"
            and subject == "patient_outcomes"
            and "answer_question" in operations
        )

        if (
            should_query_patient_data
            and not live_query_exists
        ):
            return {
                "nodes": [
                    {
                        "id": "live_project_data",
                        "tool": "query_project_data",
                        "args": {
                            "question": request.get(
                                "original_request",
                                "",
                            ),
                            "limit_per_outcome": 10,
                        },
                        "deps": [],
                    }
                ]
            }

        if "usage_analysis" in operations:
            self._add_usage_analysis_nodes(
                nodes,
                request,
                result,
                source,
            )

        read_results = [
            item
            for item in results.values()
            if isinstance(item, dict)
            and item.get("tool") == "read_file"
            and item.get("status") == "success"
        ]

        final_answer_exists = any(
            isinstance(item, dict)
            and item.get("tool") == "answer_question"
            and item.get("status") == "success"
            for item in results.values()
        )

        if (
            "answer_question" in operations
            and (read_results or live_query_exists)
            and not final_answer_exists
        ):
            return {
                "nodes": [
                    {
                        "id": "final_answer",
                        "tool": "answer_question",
                        "args": {
                            "question": request.get(
                                "original_request",
                                "",
                            ),
                        },
                        "deps": [],
                    }
                ]
            }

        if any(
            operation in operations
            for operation in {
                "answer_question",
                "summarize",
                "inventory",
            }
        ):
            self._add_planned_read_nodes(
                nodes,
                request,
                result,
                source,
            )

        if not nodes:
            return None

        return {
            "nodes": nodes,
        }
    # =========================================================
    # FOCUS CONTROL
    # =========================================================

    def _request_focus_terms(self, request: dict[str, Any]) -> set[str]:
        text = (request.get("original_request") or "").lower()

        terms = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", text))

        stop = {
            "the", "and", "for", "with", "that", "this", "from", "into",
            "please", "rewrite", "review", "find", "fix", "file", "files",
            "code", "issue", "problem", "error", "thing", "stuff", "make",
            "sure", "does", "what", "where", "when", "why", "how", "all",
            "output", "section", "question", "assignment",
        }

        return {term for term in terms if term not in stop and len(term) >= 3}

    def _is_file_focused(
        self,
        path: str,
        classification: dict[str, Any],
        request: dict[str, Any],
    ) -> bool:
        focus_terms = self._request_focus_terms(request)

        if not focus_terms:
            return True

        haystack = " ".join(
            [
                path,
                classification.get("filename", ""),
                classification.get("directory", ""),
                classification.get("category", ""),
            ]
        ).lower()

        direct_match = any(term in haystack for term in focus_terms)

        if direct_match:
            return True

        score = int(classification.get("score", 0) or 0)

        return score >= self.MIN_FOCUSED_SCORE

    # =========================================================
    # PLANNED FILE READING
    # =========================================================

    def _add_planned_read_nodes(
        self,
        nodes: list[dict[str, Any]],
        request: dict[str, Any],
        result: dict[str, Any],
        source: str,
    ) -> None:
        inventories = self._collect_inventory_nodes(result, source)

        all_files: list[dict[str, str]] = []
        all_directories: list[dict[str, str]] = []

        seen_files: set[str] = set()
        seen_directories: set[str] = set()

        for inventory in inventories:
            base_path = inventory["path"]
            text = inventory["text"]

            for filename in self._extract_files(text):
                path = self._join_workspace_path(base_path, filename)

                if path in seen_files:
                    continue

                seen_files.add(path)

                all_files.append(
                    {
                        "base": base_path,
                        "name": filename,
                        "path": path,
                    }
                )

            for dirname in self._extract_directories(text):
                path = self._join_workspace_path(base_path, dirname)

                if path in seen_directories:
                    continue

                seen_directories.add(path)

                all_directories.append(
                    {
                        "base": base_path,
                        "name": dirname,
                        "path": path,
                    }
                )

        # Do not select loose root files merely because one word matches.
        # First descend into relevant project folders.
        deeper_inventories_exist = any(
            item["path"] != source
            for item in inventories
        )

        if all_directories and not deeper_inventories_exist:
            selected_directories = self._select_directories_for_request(
                directories=all_directories,
                request=request,
            )

            if selected_directories:
                self._add_directory_inventory_nodes(
                    nodes=nodes,
                    directories=selected_directories,
                    request=request,
                )
                return

        # Once deeper folders have been inventoried, select several
        # relevant files rather than one coincidental root match.
        if all_files:
            classified_files = self._classify_file_items(
                file_items=all_files,
                request=request,
            )

            selected_files = self._select_files_for_request(
                classified_files=classified_files,
                request=request,
            )

            if selected_files:
                self._add_read_file_nodes(
                    nodes=nodes,
                    selected=selected_files,
                )
                return

        if all_directories:
            selected_directories = self._select_directories_for_request(
                directories=all_directories,
                request=request,
            )

            if selected_directories:
                self._add_directory_inventory_nodes(
                    nodes=nodes,
                    directories=selected_directories,
                    request=request,
                )

        # ---------------------------------------------------------
        # First preference:
        # Read files that are actually relevant to the assignment.
        #
        # This is the critical correction. Once useful files have
        # been discovered, do not keep listing directories forever.
        # ---------------------------------------------------------
        if all_files:
            classified_files = self._classify_file_items(
                file_items=all_files,
                request=request,
            )

            selected_files = self._select_files_for_request(
                classified_files=classified_files,
                request=request,
            )

            if selected_files:
                self._add_read_file_nodes(
                    nodes=nodes,
                    selected=selected_files,
                )
                return

        # ---------------------------------------------------------
        # Second preference:
        # If no relevant files have been found yet, continue deeper
        # into directories that are related to the request.
        # ---------------------------------------------------------
        if all_directories:
            selected_directories = self._select_directories_for_request(
                directories=all_directories,
                request=request,
            )

            if selected_directories:
                self._add_directory_inventory_nodes(
                    nodes=nodes,
                    directories=selected_directories,
                    request=request,
                )

    def _collect_inventory_nodes(
        self,
        result: dict[str, Any],
        default_source: str,
    ) -> list[dict[str, str]]:
        inventories = []
        results = result.get("results", {}) or {}

        for node_id, node_result in results.items():
            if not str(node_id).startswith("inventory"):
                continue

            raw = node_result.get("result")
            text = self._unwrap_text(raw)

            args = node_result.get("args") or {}
            path = args.get("path") or default_source

            if text:
                inventories.append(
                    {
                        "node_id": node_id,
                        "path": path,
                        "text": text,
                    }
                )

        return inventories

    def _add_directory_inventory_nodes(
        self,
        nodes: list[dict[str, Any]],
        directories: list[dict[str, str]],
        request: dict[str, Any],
    ) -> None:
        selected_dirs = self._select_directories_for_request(directories, request)

        for index, item in enumerate(selected_dirs, start=1):
            nodes.append(
                {
                    "id": f"inventory_dir_{index}",
                    "tool": "list_directory",
                    "args": {"path": item["path"]},
                    "deps": [],
                }
            )

    def _classify_file_items(
        self,
        file_items: list[dict[str, str]],
        request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        classified_files = []

        for item in file_items:
            path = item["path"]
            filename = item["name"]

            if not should_read(path):
                continue

            classification = file_classifier.classify(path)

            classification["score"] = self._score_file_for_request(
                filename=filename,
                classification=classification,
                request=request,
            )

            if not self._is_file_focused(path, classification, request):
                continue

            classified_files.append(classification)

        return classified_files

    def _select_files_for_request(
        self,
        classified_files: list[dict[str, Any]],
        request: dict[str, Any],
    ) -> list[dict[str, Any]]:
        plan = planner.plan(
            request=request,
            inventory={"files": classified_files},
        )

        return self._select_files_for_plan(classified_files, plan)

    def _add_read_file_nodes(
        self,
        nodes: list[dict[str, Any]],
        selected: list[dict[str, Any]],
    ) -> None:
        for index, item in enumerate(selected, start=1):
            nodes.append(
                {
                    "id": f"read_file_{index}",
                    "tool": "read_file",
                    "args": {
                        "path": item["path"],
                        "classification": item,
                    },
                    "deps": [],
                }
            )

    def _select_directories_for_request(
        self,
        directories: list[dict[str, str]],
        request: dict[str, Any],
    ) -> list[dict[str, str]]:
        focus_terms = self._request_focus_terms(request)
        text = (request.get("original_request") or "").lower()

        if any(k in text for k in ["template", "html", "frontend", "page", "screen"]):
            priority = [
                "templates", "partials", "components", "static",
                "css", "js", "routes", "services", "utils",
            ]   
        elif any(k in text for k in ["recommend", "recommendation", "product", "pipeline"]):
            priority = [
                "api", "recommendations", "services", "products",
                "serializers", "models", "routes", "utils",
                "templates", "static",
            ]
        else:
            priority = [
                "app", "core", "api", "routes", "services",
                "models", "serializers", "templates", "static", "utils",
            ]

        scored = []

        for item in directories:
            name = item["name"].lower()
            path = item["path"].lower()

            score = 0

            for index, key in enumerate(priority):
                if name == key or path.endswith("/" + key):
                    score += 100 - index

            if any(term in path for term in focus_terms):
                score += 80

            if any(part in path for part in priority):
                score += 20

            if score <= 0:
                continue

            scored.append((score, item["path"], item))

        scored.sort(key=lambda row: (-row[0], row[1]))

        return [item for _, _, item in scored[: self.MAX_DIRECTORY_NODES]]

    def _select_files_for_plan(
        self,
        classified_files: list[dict[str, Any]],
        plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        target_categories = plan.get("target_categories") or set()

        # A question normally needs evidence from several files.
        max_files = max(
            6,
            min(int(plan.get("max_files") or 10), 12),
        )

        candidates = []

        for item in classified_files:
            if (
                target_categories
                and item.get("category") not in target_categories
            ):
                continue

            score = int(item.get("score", 0) or 0)

            if score < self.MIN_FOCUSED_SCORE:
                continue

            candidates.append(item)

        candidates.sort(
            key=lambda item: (
                -int(item.get("score", 0)),
                item.get("path", ""),
            )
        )

        return candidates[:max_files]

    def _score_file_for_request(
        self,
        filename: str,
        classification: dict[str, Any],
        request: dict[str, Any],
    ) -> int:
        text = (request.get("original_request") or "").lower()

        haystack = " ".join(
            [
                filename,
                classification.get("path", ""),
                classification.get("filename", ""),
                classification.get("directory", ""),
                classification.get("category", ""),
            ]
        ).lower()

        score = 0

        for term in self._request_focus_terms(request):
            if term in haystack:
                score += 25

        keywords = [
            "recommend", "recommendation", "rank", "ranking", "score",
            "scoring", "product", "symptom", "chem", "chemistry",
            "terpene", "heatmap", "resolve", "evidence", "profile",
            "template", "html", "dashboard", "card", "frontend", "route",
        ]

        for keyword in keywords:
            if keyword in text and keyword in haystack:
                score += 10

        category = classification.get("category")

        if category == "api":
            score += 8
        elif category == "service":
            score += 7
        elif category == "serializer":
            score += 6
        elif category == "model":
            score += 5
        elif category in {"route", "template"}:
            score += 4
        elif category == "utility":
            score += 3

        return score

    # =========================================================
    # RELATIONSHIP / USAGE ANALYSIS
    # =========================================================

    def _add_usage_analysis_nodes(
        self,
        nodes: list[dict[str, Any]],
        request: dict[str, Any],
        result: dict[str, Any],
        source: str,
    ) -> None:
        template_inventory = self._extract_node_text(result, "inventory_source")
        route_inventory = self._extract_node_text(result, "inventory_routes")

        templates = self._extract_files(template_inventory)
        route_files = self._extract_files(route_inventory)

        route_read_node_ids = []

        for index, filename in enumerate(route_files, start=1):
            path = self._join_workspace_path("workspace:/routes", filename)

            if not should_read(path):
                continue

            classification = file_classifier.classify(path)

            if classification.get("category") not in {"route", "api"}:
                continue

            node_id = f"read_route_{index}"
            route_read_node_ids.append(node_id)

            nodes.append(
                {
                    "id": node_id,
                    "tool": "read_file",
                    "args": {
                        "path": path,
                        "classification": classification,
                    },
                    "deps": [],
                }
            )

        nodes.append(
            {
                "id": "relationship_analysis",
                "tool": "relationship_analyzer",
                "args": {
                    "objective": request.get("original_request"),
                    "source": source,
                    "target_files": templates,
                    "templates": templates,
                },
                "deps": route_read_node_ids,
            }
        )

    # =========================================================
    # TEXT EXTRACTION
    # =========================================================

    def _extract_node_text(self, result: dict[str, Any], node_id: str) -> str:
        node = result.get("results", {}).get(node_id, {})
        raw = node.get("result")

        if not raw:
            return ""

        return self._unwrap_text(raw)

    def _unwrap_text(self, value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, str):
            match = re.search(r"text='([\s\S]*?)'\s+annotations=", value)

            if match:
                return (
                    match.group(1)
                    .replace("\\n", "\n")
                    .replace("\\r", "\r")
                    .replace("\\'", "'")
                )

            return value

        if isinstance(value, list):
            return "\n".join(self._unwrap_text(item) for item in value)

        if isinstance(value, dict):
            if "text" in value:
                return str(value["text"])

            if "result" in value:
                return self._unwrap_text(value["result"])

        text_attr = getattr(value, "text", None)
        if isinstance(text_attr, str):
            return text_attr

        return str(value)

    def _extract_files(self, text: str) -> list[str]:
        return [
            match.group(1).strip()
            for match in re.finditer(r"\[FILE\]\s+([^\n'\\]+)", text)
            if match.group(1).strip()
        ]

    def _extract_directories(self, text: str) -> list[str]:
        return [
            match.group(1).strip()
            for match in re.finditer(r"\[DIR\]\s+([^\n'\\]+)", text)
            if match.group(1).strip()
        ]

    def _join_workspace_path(self, base: str, filename: str) -> str:
        return base.rstrip("/") + "/" + filename.lstrip("/")


graph_expander = GraphExpander()