from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any
from core.swmantic_parser import semantic_parser


class RelationshipAnalyzer:
    """
    Generic evidence-to-relationship analyzer.

    Purpose:
    - Find which evidence files reference/support target files.
    - Classify the relationship instead of only saying "found."
    - Prepare structured output that can later feed dependency analysis.
    """

    def analyze(self, objective: str, evidence: dict[str, Any]) -> dict[str, Any]:
        target_files = evidence.get("target_files", [])
        evidence_files = evidence.get("evidence_files", {})

        return self.file_relationship_usage(
            objective=objective,
            target_files=target_files,
            evidence_files=evidence_files,
        )

    def file_relationship_usage(
        self,
        objective: str,
        target_files: list[str],
        evidence_files: dict[str, str],
    ) -> dict[str, Any]:

        relationships = []

        for target in target_files:
            normalized_target = self._normalize_path(target)
            target_name = PurePosixPath(normalized_target).name

            refs = []

            for evidence_path, source in evidence_files.items():
                normalized_evidence_path = self._normalize_path(evidence_path)

                matches = self._source_references_file(
                    source=source or "",
                    target_path=normalized_target,
                )

                for match in matches:
                    refs.append(
                        {
                            "file": normalized_evidence_path,
                            "relationship": match["relationship"],
                            "matched": match["matched"],
                            "confidence": match["confidence"],
                        }
                    )

            refs = self._dedupe_refs(refs)

            relationships.append(
                {
                    "target": normalized_target,
                    "file_name": target_name,
                    "folder": self._folder(normalized_target),
                    "referenced_by": refs,
                    "status": self._status_for(refs),
                }
            )

        referenced = sum(
            1 for row in relationships
            if row["status"] != "not_found"
        )

        return {
            "type": "file_relationship_usage",
            "status": "ok",
            "objective": objective,
            "total_targets": len(target_files),
            "referenced_targets": referenced,
            "unreferenced_targets": len(target_files) - referenced,
            "relationships": relationships,
        }

    # =========================================================
    # MATCHING
    # =========================================================

    def _source_references_file(
        self,
        source: str,
        target_path: str,
    ) -> list[dict[str, Any]]:

        source = source or ""
        filename = PurePosixPath(target_path).name
        stem = PurePosixPath(filename).stem

        candidates = [
            {
                "relationship": "render_template",
                "confidence": 100,
                "patterns": [
                    rf"render_template\(\s*['\"]{re.escape(target_path)}['\"]",
                    rf"render_template\(\s*['\"]patient/{re.escape(target_path)}['\"]",
                    rf"render_template\(\s*['\"]{re.escape(filename)}['\"]",
                ],
            },
            {
                "relationship": "template_include_or_extends",
                "confidence": 95,
                "patterns": [
                    rf"{{%\s*include\s+['\"]{re.escape(target_path)}['\"]",
                    rf"{{%\s*include\s+['\"]patient/{re.escape(target_path)}['\"]",
                    rf"{{%\s*include\s+['\"]{re.escape(filename)}['\"]",
                    rf"{{%\s*extends\s+['\"]{re.escape(target_path)}['\"]",
                    rf"{{%\s*extends\s+['\"]patient/{re.escape(target_path)}['\"]",
                    rf"{{%\s*extends\s+['\"]{re.escape(filename)}['\"]",
                ],
            },
            {
                "relationship": "url_or_path_reference",
                "confidence": 75,
                "patterns": [
                    re.escape(target_path),
                    re.escape(f"patient/{target_path}"),
                ],
            },
            {
                "relationship": "filename_reference",
                "confidence": 45,
                "patterns": [
                    rf"\b{re.escape(filename)}\b",
                ],
            },
            {
                "relationship": "symbol_name_reference",
                "confidence": 25,
                "patterns": [
                    rf"\b{re.escape(stem)}\b",
                ],
            },
        ]

        matches = []

        for candidate in candidates:
            for pattern in candidate["patterns"]:
                found = re.search(pattern, source)

                if found:
                    matches.append(
                        {
                            "relationship": candidate["relationship"],
                            "confidence": candidate["confidence"],
                            "matched": found.group(0),
                        }
                    )
                    break

        return matches

    # =========================================================
    # STATUS / CLEANUP
    # =========================================================

    def _status_for(self, refs: list[dict[str, Any]]) -> str:
        if not refs:
            return "not_found"

        best = max(ref.get("confidence", 0) for ref in refs)

        if best >= 95:
            return "strong_reference"

        if best >= 75:
            return "likely_reference"

        return "weak_reference"

    def _dedupe_refs(self, refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen = set()
        clean = []

        for ref in refs:
            key = (
                ref.get("file"),
                ref.get("relationship"),
                ref.get("matched"),
            )

            if key in seen:
                continue

            seen.add(key)
            clean.append(ref)

        clean.sort(
            key=lambda item: (
                -int(item.get("confidence", 0)),
                item.get("file", ""),
                item.get("relationship", ""),
            )
        )

        return clean

    def _normalize_path(self, path: str) -> str:
        return str(path or "").replace("\\", "/").strip()

    def _folder(self, path: str) -> str:
        parent = str(PurePosixPath(path).parent)
        return "" if parent == "." else parent


relationship_analyzer = RelationshipAnalyzer()