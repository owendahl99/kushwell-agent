from __future__ import annotations

import asyncio
import copy
import re
import time
import json

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set


@dataclass(slots=True)
class ExecutorConfig:
    max_parallel_tasks: int = 8
    max_retries: int = 2
    retry_backoff: float = 0.50
    task_timeout: float = 60.0
    fail_fast: bool = False
    debug: bool = True


@dataclass(slots=True)
class ExecutionMetrics:
    started_at: float = 0.0
    finished_at: float = 0.0
    total_nodes: int = 0
    completed_nodes: int = 0
    failed_nodes: int = 0
    skipped_nodes: int = 0
    retries: int = 0
    wall_time: float = 0.0


class DAGExecutor:
    def __init__(self, mcp, memory=None, config: Optional[ExecutorConfig] = None):
        self.mcp = mcp
        self.memory = memory
        self.config = config or ExecutorConfig()
        self.metrics = ExecutionMetrics()

        self.results: Dict[str, Any] = {}
        self.errors: Dict[str, Any] = {}
        self.node_map: Dict[str, Dict[str, Any]] = {}
        self.dependencies: Dict[str, Set[str]] = {}
        self.reverse_dependencies: Dict[str, Set[str]] = defaultdict(set)

        self.completed: Set[str] = set()
        self.failed: Set[str] = set()
        self.skipped: Set[str] = set()

        self._lock = asyncio.Lock()

    def _debug(self, *msg):
        if self.config.debug:
            print("[DAG]", *msg)

    def validate_graph(self, graph: Dict[str, Any]) -> None:
        if not isinstance(graph, dict):
            raise ValueError("Graph must be a dictionary.")

        nodes = graph.get("nodes")

        if nodes is None:
            raise ValueError("Graph missing 'nodes'.")

        if not isinstance(nodes, list):
            raise ValueError("'nodes' must be a list.")

        if not nodes:
            raise ValueError("Graph contains no nodes.")

        self._validate_nodes(nodes)
        self._build_indexes(nodes)
        self._detect_cycles()

    def _validate_nodes(self, nodes: List[Dict[str, Any]]) -> None:
        ids = set()

        for node in nodes:
            if not isinstance(node, dict):
                raise ValueError("Node must be dictionary.")

            node_id = node.get("id")

            if not node_id:
                raise ValueError("Node missing id.")

            if node_id in ids:
                raise ValueError(f"Duplicate node '{node_id}'.")

            ids.add(node_id)

            if "tool" not in node:
                raise ValueError(f"Node '{node_id}' missing tool.")

            deps = node.get("deps", [])

            if deps is None:
                deps = []

            if not isinstance(deps, list):
                raise ValueError(f"Node '{node_id}' deps must be list.")

    def _build_indexes(self, nodes: List[Dict[str, Any]]) -> None:
        self.node_map.clear()
        self.dependencies.clear()
        self.reverse_dependencies.clear()

        for node in nodes:
            node = copy.deepcopy(node)
            node.setdefault("args", {})
            node.setdefault("deps", [])

            node_id = node["id"]

            self.node_map[node_id] = node
            self.dependencies[node_id] = set(node["deps"])

        for node in nodes:
            node_id = node["id"]

            for dep in node.get("deps", []):
                if dep not in self.node_map:
                    raise ValueError(
                        f"Node '{node_id}' depends on missing node '{dep}'."
                    )

                self.reverse_dependencies[dep].add(node_id)

    def _detect_cycles(self) -> None:
        visited = set()
        visiting = set()

        def dfs(node_id: str):
            if node_id in visiting:
                raise ValueError(f"Dependency cycle detected at '{node_id}'.")

            if node_id in visited:
                return

            visiting.add(node_id)

            for dep in self.dependencies[node_id]:
                dfs(dep)

            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in self.node_map:
            dfs(node_id)

    def _inject_dependencies(self, args: dict):
        if not isinstance(args, dict):
            return args

        resolved = {}

        for key, value in args.items():
            if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
                ref = value[2:-2].strip()
                node_id, field = ref.split(".", 1)

                dep = self.results.get(node_id, {})
                resolved[key] = dep.get(field)
            else:
                resolved[key] = value

        return resolved
    
    async def _run_answer_question(self, args: dict) -> dict:
        question = str(args.get("question") or "").strip()

        evidence = self._extract_read_files(
            prefix="read_file_"
        )

        structured_data = {
            "patient_evidence": {},
            "recommendations": {},
            "project_search": {},
            "project_relationships": {},
            "acquisition_status": {},
            "acquisition_runs": {},
            "acquisition_plan": {},
            "acquisition_execution": {},
        }

        for node_result in self.results.values():
            if not isinstance(node_result, dict):
                continue

            if node_result.get("status") != "success":
                continue

            tool_name = node_result.get("tool")
            output = node_result.get("result")

            if not isinstance(output, dict):
                continue

            if tool_name == "query_project_data":
                structured_data["patient_evidence"] = output

            elif tool_name == "query_recommendations":
                structured_data["recommendations"] = output

            elif tool_name == "search_project_index":
                structured_data["project_search"] = output

            elif tool_name == "get_project_relationships":
                structured_data["project_relationships"] = output

            elif tool_name == "query_acquisition_status":
                structured_data["acquisition_status"] = output

            elif tool_name == "query_acquisition_runs":
                structured_data["acquisition_runs"] = output

            elif tool_name == "plan_product_acquisition":
                structured_data["acquisition_plan"] = output

            elif tool_name == "run_product_acquisition":
                structured_data["acquisition_execution"] = output

        structured_data = {
            key: value
            for key, value in structured_data.items()
            if value
        }

        if not evidence and not structured_data:
            return {
                "status": "failed",
                "answer": (
                    "The Brain could not answer because "
                    "no project evidence, patient evidence, "
                    "or recommendation results were available."
                ),
                "sources": [],
            }

        prompt = self._build_answer_prompt(
            question=question,
            evidence=evidence,
            live_data=structured_data,
        )

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI()

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the Kushwell project-analysis answer layer. "
                            "Answer only from supplied project evidence. "
                            "Never invent chemical effects, heatmap values, clinical outcomes, "
                            "confidence scores, or product recommendations. "
                            "Clearly distinguish code structure from actual stored evidence. "
                            "When actual data is unavailable, identify the exact missing query, "
                            "table, service, or execution step needed to answer. "
                            "Stay focused on the user's assignment and cite workspace paths."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.1,
            )

            answer = (
                response.choices[0].message.content or ""
            ).strip()

            if answer:
                return {
                    "status": "success",
                    "answer": answer,
                    "sources": list(evidence.keys()),
                }

        except Exception as exc:
            self._debug(
                "ANSWER_MODEL_UNAVAILABLE",
                {"error": str(exc)},
            )

        # Honest fallback when the API model is unavailable.
        return self._build_extractable_fallback(
            question=question,
            evidence=evidence,
        )


    def _build_answer_prompt(
        self,
        question: str,
        evidence: dict[str, str],
        live_data: dict | None = None,
    ) -> str:
        """
        Build a focused evidence package for the answering model.

        Goals:
        - Keep the model centered on the user's assignment.
        - Treat live database results as the strongest evidence.
        - Prioritize project-specific chemistry and heatmap logic.
        - Prevent invented scores, products, or clinical claims.
        - Distinguish implementation evidence from actual stored data.
        """

        question = str(question or "").strip()
        evidence = evidence or {}
        live_data = live_data or {}

        if not question:
            question = "Answer the user's project question."

        # =========================================================
        # GROUP SOURCE-CODE EVIDENCE
        # =========================================================

        priority_groups: dict[str, list[dict[str, str]]] = {
            "heatmap_and_outcomes": [],
            "chemistry": [],
            "recommendation": [],
            "literature_and_evidence": [],
            "models_and_schema": [],
            "other": [],
        }

        for path, raw_content in evidence.items():
            path_value = str(path or "")
            path_text = path_value.lower()

            content = self._extract_text(raw_content).strip()

            if not content:
                continue

            item = {
                "path": path_value,
                "content": content,
            }

            if any(
                marker in path_text
                for marker in {
                    "heatmap",
                    "heat_map",
                    "chemical_impact",
                    "outcome",
                    "symptom",
                }
            ):
                priority_groups["heatmap_and_outcomes"].append(item)

            elif any(
                marker in path_text
                for marker in {
                    "chem",
                    "terpene",
                    "cannabinoid",
                    "strain_chemistry",
                }
            ):
                priority_groups["chemistry"].append(item)

            elif any(
                marker in path_text
                for marker in {
                    "recommend",
                    "ranking",
                    "scoring",
                    "resolve",
                    "product_impact",
                }
            ):
                priority_groups["recommendation"].append(item)

            elif any(
                marker in path_text
                for marker in {
                    "literature",
                    "evidence",
                    "source",
                    "confidence",
                }
            ):
                priority_groups["literature_and_evidence"].append(item)

            elif any(
                marker in path_text
                for marker in {
                    "/models/",
                    "model",
                    "schema",
                }
            ):
                priority_groups["models_and_schema"].append(item)

            else:
                priority_groups["other"].append(item)

        section_labels = {
            "heatmap_and_outcomes": "HEATMAP AND OUTCOME LOGIC",
            "chemistry": "CHEMISTRY PROFILE LOGIC",
            "recommendation": "RECOMMENDATION AND PRODUCT-RANKING LOGIC",
            "literature_and_evidence": (
                "LITERATURE, SOURCES, AND CONFIDENCE LOGIC"
            ),
            "models_and_schema": "DATA MODELS AND SCHEMA",
            "other": "OTHER POTENTIALLY RELEVANT PROJECT EVIDENCE",
        }

        # =========================================================
        # BASE INSTRUCTIONS
        # =========================================================

        sections = [
            "USER ASSIGNMENT",
            question,
            "",
            "EVIDENCE PRIORITY",
            (
                "1. Live Kushwell database results are the strongest evidence."
            ),
            (
                "2. Source-code evidence may explain how data is calculated, "
                "stored, ranked, or retrieved."
            ),
            (
                "3. Source-code structure alone does not prove that a specific "
                "chemical, score, outcome, or product exists in the live data."
            ),
            "",
            "RESPONSE RULES",
            (
                "1. Answer the user's actual assignment directly. "
                "Do not discuss directory traversal, graph nodes, MCP calls, "
                "or tool execution."
            ),
            (
                "2. Use only the supplied live data and project evidence. "
                "Do not rely on outside cannabis knowledge."
            ),
            (
                "3. Do not invent heatmap scores, percentages, confidence values, "
                "chemical weights, symptom relationships, product names, "
                "or product rankings."
            ),
            (
                "4. Clearly distinguish live database findings from "
                "implementation details found in source files."
            ),
            (
                "5. When exact values or products are absent, state precisely "
                "what information is missing."
            ),
            (
                "6. Identify the project table, service, function, or query "
                "that could provide missing information."
            ),
            (
                "7. Cite supporting workspace paths inline when referring "
                "to implementation evidence."
            ),
            (
                "8. For multiple requested outcomes, answer each outcome "
                "separately using the same structure."
            ),
            (
                "9. Do not recommend a specific product unless an actual product "
                "record or ranked product result appears in the supplied evidence."
            ),
            "",
            "REQUIRED ANSWER FORMAT",
            "For each requested outcome, provide:",
            "- Outcome",
            "- Live chemical-profile findings",
            "- Heatmap or outcome evidence",
            "- Confidence and sample information, when available",
            "- Missing data or limitations",
            "- Product recommendation, only when supported by an actual result",
        ]

        # =========================================================
        # LIVE DATABASE RESULTS
        # =========================================================

        if live_data:
            sections.extend(
                [
                    "",
                    "LIVE KUSHWELL DATABASE RESULTS",
                    json.dumps(
                        live_data,
                        indent=2,
                        default=str,
                    ),
                    "",
                    (
                        "Use the live database results above as the primary "
                        "basis for chemical-profile conclusions."
                    ),
                    (
                        "If an outcome has no returned chemical-profile rows, "
                        "state that no live result was found. Do not fill the gap "
                        "with general knowledge."
                    ),
                ]
            )
        else:
            sections.extend(
                [
                    "",
                    "LIVE KUSHWELL DATABASE RESULTS",
                    "No live database results were supplied.",
                    "",
                    (
                        "Do not present source-code structures as though they "
                        "were live chemical or product findings."
                    ),
                ]
            )

        # =========================================================
        # SOURCE-CODE EVIDENCE
        # =========================================================

        max_chars_per_file = 8000
        max_files_per_group = 5

        for group_name, items in priority_groups.items():
            if not items:
                continue

            sections.extend(
                [
                    "",
                    section_labels[group_name],
                ]
            )

            for item in items[:max_files_per_group]:
                content = item["content"]

                if len(content) > max_chars_per_file:
                    content = (
                        content[:max_chars_per_file].rstrip()
                        + "\n[File content truncated]"
                    )

                sections.extend(
                    [
                        "",
                        f"FILE: {item['path']}",
                        content,
                    ]
                )

        # =========================================================
        # FINAL INSTRUCTION
        # =========================================================

        sections.extend(
            [
                "",
                "FINAL INSTRUCTION",
                (
                    "Produce a concise, evidence-grounded answer now. "
                    "Lead with live database findings. Use source files only "
                    "to explain how the result was produced or what additional "
                    "query is required."
                ),
                (
                    "Do not claim that a specific terpene, cannabinoid, score, "
                    "symptom relationship, or product is supported unless it "
                    "appears in the supplied live data or project evidence."
                ),
                (   
                    "Do not output Markdown heading markers such as ###. "
                    "Use plain readable headings and short paragraphs."
                ),
            ]
        )

        return "\n".join(sections)

    def _build_extractable_fallback(
        self,
        question: str,
        evidence: dict[str, str],
    ) -> dict:
        """
        Build a compact, readable evidence summary when the answering
        model is unavailable.

        This fallback must never dump complete source files into the UI.
        """

        stop_words = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "that",
            "this",
            "what",
            "using",
            "each",
            "following",
            "patient",
            "patients",
            "their",
            "they",
            "them",
            "into",
            "would",
            "could",
            "should",
            "describe",
            "desired",
            "outcome",
            "outcomes",
            "wishes",
            "seeks",
            "desires",
            "improved",
            "reduce",
            "relief",
        }

        focus_terms = {
            term.lower()
            for term in re.findall(
                r"[A-Za-z][A-Za-z0-9_-]{2,}",
                question or "",
            )
            if term.lower() not in stop_words
        }

        # Useful general project concepts that strengthen matching when
        # they appear in both the question and source evidence.
        concept_aliases = {
            "chemical": {
                "chemical",
                "chemistry",
                "cannabinoid",
                "cannabinoids",
                "terpene",
                "terpenes",
                "chemotype",
            },
            "heatmap": {
                "heatmap",
                "heatmaps",
                "matrix",
                "weight",
                "weights",
                "score",
                "scores",
            },
            "sleep": {
                "sleep",
                "insomnia",
                "night",
                "sedating",
                "sedation",
            },
            "pain": {
                "pain",
                "arthritis",
                "inflammation",
                "inflammatory",
                "analgesic",
            },
            "anxiety": {
                "anxiety",
                "anxious",
                "calm",
                "stress",
                "relaxation",
            },
        }

        expanded_terms = set(focus_terms)

        for concept, aliases in concept_aliases.items():
            if concept in focus_terms or focus_terms.intersection(aliases):
                expanded_terms.update(aliases)

        excerpts: list[dict] = []
        seen_excerpt_keys: set[tuple[str, str]] = set()

        for path, raw_content in evidence.items():
            content = self._extract_text(raw_content)

            if not content:
                continue

            for line_number, raw_line in enumerate(
                content.splitlines(),
                start=1,
            ):
                line = raw_line.strip()

                if not line:
                    continue

                # Remove common MCP string-representation wrappers.
                line = re.sub(
                    r"^type=['\"]text['\"]\s+text=['\"]?",
                    "",
                    line,
                )

                line = re.sub(
                    r"\s+annotations=None(?:\s+meta=None)?$",
                    "",
                    line,
                )

                # Skip low-information syntax and formatting lines.
                if line in {
                    "{",
                    "}",
                    "[",
                    "]",
                    "(",
                    ")",
                    "return",
                    "pass",
                }:
                    continue

                normalized = line.lower()

                matched_terms = {
                    term
                    for term in expanded_terms
                    if term in normalized
                }

                if not matched_terms:
                    continue

                # Reward lines that contain several relevant concepts.
                score = len(matched_terms) * 10

                path_lower = path.lower()

                for term in focus_terms:
                    if term in path_lower:
                        score += 8

                # Favor explanatory and data-bearing lines.
                if any(
                    marker in normalized
                    for marker in {
                        "score",
                        "weight",
                        "chemical_key",
                        "domain",
                        "success_rate",
                        "positive",
                        "negative",
                        "terpene",
                        "cannabinoid",
                        "confidence",
                        "heatmap",
                    }
                ):
                    score += 5

                # Penalize imports and unrelated scaffolding.
                if normalized.startswith(
                    (
                        "import ",
                        "from ",
                        "class ",
                        "@",
                    )
                ):
                    score -= 5

                cleaned = re.sub(r"\s+", " ", line).strip()

                cleaned = cleaned.replace("\\r", "").replace("\\n", " ")

                if any(
                    marker in normalized
                    for marker in {
                        "back_populates",
                        "db.column",
                        "nullable=",
                        "primary_key=",
                        "foreignkey",
                    }
                ):
                    score -= 8

                if len(cleaned) > 220:
                    cleaned = cleaned[:217].rstrip() + "..."

                dedupe_key = (
                    path,
                    cleaned.lower(),
                )

                if dedupe_key in seen_excerpt_keys:
                    continue

                seen_excerpt_keys.add(dedupe_key)

                excerpts.append(
                    {
                        "score": score,
                        "path": path,
                        "line": line_number,
                        "text": cleaned,
                        "matched_terms": sorted(matched_terms),
                    }
                )

        excerpts.sort(
            key=lambda item: (
                -item["score"],
                item["path"],
                item["line"],
            )
        )

        # Keep the answer short. Do not flood the UI.
        best = excerpts[:8]

        if not best:
            return {
                "status": "partial",
                "answer": (
                    "The relevant project files were read, but the answering "
                    "model is unavailable and the local fallback could not find "
                    "enough direct evidence to answer the question safely."
                ),
                "sources": list(evidence.keys())[:12],
            }

        grouped: dict[str, list[dict]] = {}

        for item in best:
            grouped.setdefault(item["path"], []).append(item)

        lines = [
            (
                "The answering model is currently unavailable. "
                "Below is a focused evidence summary from the most relevant "
                "project files; it is not a fully synthesized conclusion."
            ),
            "",
        ]

        for path, items in grouped.items():
            lines.append(path)

            for item in items:
                lines.append(
                    f"  Line {item['line']}: {item['text']}"
                )

            lines.append("")

        lines.extend(
            [
                (
                    "A complete natural-language answer requires the configured "
                    "answering model to be available."
                )
            ]
        )

        return {
            "status": "partial",
            "answer": "\n".join(lines).strip(),
            "sources": list(grouped.keys()),
        }

    async def _execute_node(self, node: dict):
        node_id = node["id"]
        tool = node["tool"]
        args = node.get("args", {})

        resolved_args = self._inject_dependencies(args)

        attempt = 0 
        last_error = None

        for attempt in range(self.config.max_retries + 1):
            try:
                self._debug(
                    "NODE_ATTEMPT",
                    {
                        "node": node_id,
                        "tool": tool,
                        "attempt": attempt + 1,
                        "args": resolved_args,
                    },
                )

                start = time.time()

                if tool == "relationship_analyzer":
                    result = self._run_relationship_analyzer(
                        resolved_args
                    )

                elif tool == "query_project_data":
                    from core.kushwell_data import (
                        query_project_data,
                    )

                    result = await asyncio.to_thread(
                        query_project_data,
                        resolved_args,
                    )

                elif tool == "query_recommendations":
                    from core.kushwell_recommendations import (
                        query_recommendations,
                    )

                    result = await asyncio.to_thread(
                        query_recommendations,
                        resolved_args,
                    )

                elif tool == "answer_question":
                    result = await self._run_answer_question(
                        resolved_args
                    )

                elif tool == "query_acquisition_status":
                    from core.kushwell_acquisition import (
                        acquisition_status,
                    )
                    result = await asyncio.to_thread(
                        acquisition_status,
                        resolved_args,
                    )

                elif tool == "query_acquisition_runs":
                    from core.kushwell_acquisition import (
                        acquisition_runs,
                    )
                    result = await asyncio.to_thread(
                        acquisition_runs,
                        resolved_args,
                    )

                elif tool == "plan_product_acquisition":
                    from core.kushwell_acquisition import (
                        plan_product_acquisition,
                    )
                    result = await asyncio.to_thread(
                        plan_product_acquisition,
                        resolved_args,
                    )

                elif tool == "run_product_acquisition":
                    from core.kushwell_acquisition import (
                        run_product_acquisition,
                    )
                    result = await asyncio.to_thread(
                        run_product_acquisition,
                        resolved_args,
                    )

                else:
                    result = await asyncio.wait_for(
                        self.mcp.call(
                            tool,
                            resolved_args,
                        ),
                        timeout=self.config.task_timeout,
                    )
                duration = round(time.time() - start, 4)

                output = {
                    "node": node_id,
                    "tool": tool,
                    "status": "success",
                    "attempts": attempt + 1,
                    "duration": duration,
                    "args": resolved_args,
                    "result": result,
                }

                self._debug("NODE_SUCCESS", output)

                return output

            except Exception as exc:
                last_error = str(exc)

                self._debug(
                    "NODE_ERROR",
                    {
                        "node": node_id,
                        "tool": tool,
                        "attempt": attempt + 1,
                        "error": last_error,
                    },
                )

                await asyncio.sleep(self.config.retry_backoff * (2 ** attempt))

        failure = {
            "node": node_id,
            "tool": tool,
            "status": "failed",
            "attempts": attempt + 1,
            "args": resolved_args,
            "error": last_error,
        }

        self.errors[node_id] = failure
        self._debug("NODE_FAILED_FINAL", failure)

        return failure

    def _run_relationship_analyzer(self, args: dict) -> dict:
        from core.relationship_analyzer import relationship_analyzer

        evidence = self._build_relationship_evidence(args)

        return relationship_analyzer.analyze(
            objective=args.get("objective", ""),
            evidence=evidence,
        )

    def _build_relationship_evidence(self, args: dict | None = None) -> dict:
        args = args or {}

        return {
            "target_files": args.get("templates", []) or args.get("target_files", []),
            "evidence_files": self._extract_read_files(prefix="read_"),
        }

    def _extract_inventory_files(self, node_result) -> list[str]:
        text = self._extract_text(node_result)
        files = []

        for line in text.splitlines():
            line = line.strip()

            if line.startswith("[FILE]"):
                files.append(line.replace("[FILE]", "").strip())

        return files

    def _extract_read_files(self, prefix: str) -> dict[str, str]:
        files = {}

        for node_id, node_result in self.results.items():
            if not node_id.startswith(prefix):
                continue

            args = node_result.get("args", {}) if isinstance(node_result, dict) else {}
            path = args.get("path") or node_id

            files[path] = self._extract_text(node_result)

        return files

    def _extract_text(self, value) -> str:
        if value is None:
            return ""

        if isinstance(value, str):
            embedded = self._extract_embedded_text(value)
            return embedded or value

        if isinstance(value, dict):
            if isinstance(value.get("text"), str):
                return value["text"]

            if "result" in value:
                return self._extract_text(value["result"])

        if isinstance(value, list):
            return "\n".join(self._extract_text(item) for item in value)

        return str(value)

    def _extract_embedded_text(self, value: str) -> str:
        match = re.search(
            r"text='([\s\S]*?)'\s+annotations=",
            value,
        )

        if not match:
            return ""

        return (
            match.group(1)
            .replace("\\n", "\n")
            .replace("\\'", "'")
        )
       
    async def _reduce_results(self):
        successful = {}
        failed = {}
        total_duration = 0.0
        final_answer_parts = []

        for node_id, result in self.results.items():
            if isinstance(result, dict) and result.get("status") == "success":
                successful[node_id] = result
                total_duration += result.get("duration", 0.0)

                tool = result.get("tool")
                output = result.get("result")

                if tool == "answer_question" and isinstance(output, dict):
                    answer = str(output.get("answer") or "").strip()

                    if answer:
                        final_answer_parts.append(answer)

                if tool == "search_files" and isinstance(output, dict):
                    term = output.get("term", "")
                    matches = output.get("matches", []) or []
                    count = output.get("count", len(matches))

                    if not matches:
                        final_answer_parts.append(
                            f'Search completed. No matches found for "{term}".'
                        )
                    else:
                        lines = [
                            f'Search completed. Found {count} match(es) for "{term}".',
                            "",
                        ]

                        for index, match in enumerate(matches, start=1):
                            path = match.get("path", "Unknown file")
                            line = match.get("line", "Unknown line")
                            text = match.get("text", "").strip()

                            lines.append(f"{index}. {path}")
                            lines.append(f"   Line {line}: {text}")
                            lines.append("")

                        final_answer_parts.append("\n".join(lines).strip())

            else:
                failed[node_id] = result

        return {
            "success": successful,
            "failed": failed,
            "answer": "\n\n".join(final_answer_parts).strip(),
            "metrics": {
                "total_nodes": len(self.results),
                "successful_nodes": len(successful),
                "failed_nodes": len(failed),
                "total_duration": round(total_duration, 4),
            },
        }
    
    async def execute(
        self,
        graph: dict,
        request: dict | None = None,
    ):
        from core.graph_expander import graph_expander

        request = request or graph.get("request") or {}

        self.results = {}
        self.errors = {}
        self.completed = set()
        self.failed = set()
        self.skipped = set()

        async def _run_graph_once(current_graph: dict):
            nodes = current_graph.get("nodes", [])

            if not nodes:
                return

            self.validate_graph(current_graph)

            node_map = {node["id"]: node for node in nodes}

            deps = {
                node["id"]: set(node.get("deps", []))
                for node in nodes
            }

            dependents = defaultdict(list)

            for node in nodes:
                for dep in node.get("deps", []):
                    dependents[dep].append(node["id"])

            ready = [
                node_id
                for node_id, node_deps in deps.items()
                if not node_deps
            ]

            seen_ready = set()

            while ready:
                batch = list(dict.fromkeys(ready))
                ready = []

                self._debug("BATCH_START", {"nodes": batch})

                tasks = [
                    self._execute_node(node_map[node_id])
                    for node_id in batch
                ]

                results = await asyncio.gather(
                    *tasks,
                    return_exceptions=True,
                )

                for index, node_id in enumerate(batch):
                    result = results[index]

                    if isinstance(result, Exception):
                        result = {
                            "node": node_id,
                            "tool": node_map[node_id].get("tool"),
                            "status": "failed",
                            "args": node_map[node_id].get("args", {}),
                            "error": str(result),
                        }

                        self.errors[node_id] = result
                        self.failed.add(node_id)

                    else:
                        if isinstance(result, dict) and result.get("status") == "success":
                            self.completed.add(node_id)
                        else:
                            self.failed.add(node_id)

                            if isinstance(result, dict):
                                self.errors[node_id] = result

                    self.results[node_id] = result
                    self._debug("NODE_COMPLETE", result)

                    for child in dependents[node_id]:
                        deps[child].discard(node_id)

                        if not deps[child] and child not in seen_ready:
                            ready.append(child)
                            seen_ready.add(child)

        nodes = graph.get("nodes", [])

        if not nodes:
            return {
                "graph_status": "failed",
                "results": {},
                "errors": {"graph": "Empty graph"},
                "summary": {
                    "total_nodes": 0,
                    "successful_nodes": 0,
                    "failed_nodes": 0,
                    "total_duration": 0.0,
                },
                "expanded_graphs": [],
            }

        await _run_graph_once(graph)

        expanded_graphs = []
        executed_signatures = set()
        max_expansion_rounds = 6

        for round_number in range(1, max_expansion_rounds + 1):
            expanded_graph = graph_expander.expand(
                request=request,
                result={"results": self.results},
            )

            if not expanded_graph or not expanded_graph.get("nodes"):
                break

            fresh_nodes = []

            for node in expanded_graph.get("nodes", []):
                tool = node.get("tool")
                args = node.get("args", {}) or {}

                signature = (
                    tool,
                    json.dumps(
                        args,
                        sort_keys=True,
                        default=str,
                    ),
                )

                if signature in executed_signatures:
                    continue

                executed_signatures.add(signature)
                fresh_nodes.append(node)

            if not fresh_nodes:
                break

            fresh_graph = {"nodes": fresh_nodes}

            self._debug(
                "GRAPH_EXPANSION",
                {
                    "round": round_number,
                    "graph": fresh_graph,
                },
            )

            expanded_graphs.append(fresh_graph)

            await _run_graph_once(fresh_graph)

        reduced = await self._reduce_results()

        if self.memory:
            await self.memory.add("dag_execution", reduced)

        return {
            "graph_status": "completed",
            "answer": reduced.get("answer", ""),
            "results": self.results,
            "errors": self.errors,
            "summary": reduced["metrics"],
            "expanded_graphs": expanded_graphs,
            }