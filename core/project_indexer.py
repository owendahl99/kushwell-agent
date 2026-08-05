"""
Persistent recursive project index for the Kushwell Brain.

The indexer builds a code-aware map of the workspace without relying on the
LLM.  It records files, Python symbols/imports/routes, Jinja relationships,
static references, and parse errors.  Unchanged files are reused from the
previous index, making repeated scans fast.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.file_classifier import file_classifier
from core.project_filters import IGNORED_DIRECTORIES, should_read
from core.workspace import WorkspaceManager

INDEX_VERSION = 1
DEFAULT_INDEX_PATH = "workspace:/.brain/project_index.json"

_TEMPLATE_CALL_RE = re.compile(
    r"\b(?:render_template|render_template_string)\s*\(\s*[rRuUbBfF]*[\"']([^\"']+)[\"']"
)
_URL_FOR_RE = re.compile(r"\burl_for\s*\(\s*[\"']([^\"']+)[\"']")
_JINJA_LINK_RE = re.compile(
    r"{%-?\s*(?:extends|include|import|from)\s+[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_JINJA_URL_FOR_RE = re.compile(r"\burl_for\s*\(\s*[\"']([^\"']+)[\"']")
_STATIC_PATH_RE = re.compile(
    r"(?:src|href)\s*=\s*[\"'](?:/static/|static/)([^\"'#?]+)",
    re.IGNORECASE,
)
_JS_IMPORT_RE = re.compile(
    r"(?:import\s+(?:[^;]+?\s+from\s+)?|require\s*\()\s*[\"']([^\"']+)[\"']"
)
_CSS_URL_RE = re.compile(r"url\(\s*[\"']?([^\"')]+)[\"']?\s*\)", re.IGNORECASE)


@dataclass(slots=True)
class IndexStats:
    scanned: int = 0
    reused: int = 0
    skipped: int = 0
    errors: int = 0


class ProjectIndexer:
    """Build, persist, load, and search a recursive workspace index."""

    def __init__(
        self,
        workspace: WorkspaceManager,
        index_path: str = DEFAULT_INDEX_PATH,
    ) -> None:
        self.workspace = workspace
        self.index_path = index_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        source: str = "workspace:/",
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        root = Path(self.workspace.resolve(source))
        if not root.exists():
            raise FileNotFoundError(f"Index source does not exist: {source}")
        if not root.is_dir():
            raise NotADirectoryError(f"Index source is not a directory: {source}")

        previous = {} if force else self.load(optional=True)
        previous_files = {
            item.get("path"): item
            for item in previous.get("files", [])
            if isinstance(item, dict) and item.get("path")
        }

        stats = IndexStats()
        files: list[dict[str, Any]] = []

        for full_path in self._walk(root):
            try:
                workspace_path = self.workspace.to_workspace(full_path)
            except Exception:
                stats.skipped += 1
                continue

            if not should_read(workspace_path):
                stats.skipped += 1
                continue

            try:
                stat = full_path.stat()
                fingerprint = self._fingerprint(stat)
                old = previous_files.get(workspace_path)

                if old and old.get("fingerprint") == fingerprint:
                    files.append(old)
                    stats.reused += 1
                    continue

                files.append(
                    self._index_file(
                        full_path=full_path,
                        workspace_path=workspace_path,
                        stat=stat,
                        fingerprint=fingerprint,
                    )
                )
                stats.scanned += 1
            except Exception as exc:
                stats.errors += 1
                files.append(
                    {
                        "path": workspace_path,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        files.sort(key=lambda item: str(item.get("path", "")).lower())
        index = {
            "version": INDEX_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "workspace_root": self.workspace.workspace_root,
            "source": source,
            "summary": self._summarize(files, stats),
            "files": files,
        }
        self.save(index)
        return index

    def load(self, *, optional: bool = False) -> dict[str, Any]:
        path = Path(self.workspace.resolve(self.index_path))
        if not path.exists():
            if optional:
                return {}
            raise FileNotFoundError(
                f"Project index not found at {self.index_path}. Build it first."
            )
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("Project index root must be a JSON object.")
        return value

    def save(self, index: dict[str, Any]) -> None:
        destination = Path(self.workspace.resolve(self.index_path))
        destination.parent.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(index, indent=2, ensure_ascii=False, sort_keys=False)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            temp_name = handle.name
        Path(temp_name).replace(destination)

    def search(
        self,
        query: str,
        *,
        limit: int = 50,
        categories: Iterable[str] | None = None,
        extensions: Iterable[str] | None = None,
        rebuild_if_missing: bool = True,
    ) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            return {"query": query, "count": 0, "matches": []}

        try:
            index = self.load()
        except FileNotFoundError:
            if not rebuild_if_missing:
                raise
            index = self.build()

        category_set = {x.lower() for x in categories or []}
        extension_set = {
            x.lower() if str(x).startswith(".") else f".{str(x).lower()}"
            for x in extensions or []
        }
        terms = [term for term in re.split(r"\s+", query.lower()) if term]
        matches: list[dict[str, Any]] = []

        for item in index.get("files", []):
            if item.get("status") != "ok":
                continue
            if category_set and str(item.get("category", "")).lower() not in category_set:
                continue
            if extension_set and str(item.get("extension", "")).lower() not in extension_set:
                continue

            score, reasons = self._score(item, terms)
            if score <= 0:
                continue

            matches.append(
                {
                    "score": score,
                    "path": item.get("path"),
                    "category": item.get("category"),
                    "extension": item.get("extension"),
                    "reasons": reasons,
                    "symbols": item.get("symbols", [])[:20],
                    "routes": item.get("routes", [])[:20],
                    "templates": item.get("templates", [])[:20],
                }
            )

        matches.sort(key=lambda row: (-row["score"], str(row["path"]).lower()))
        matches = matches[: max(1, min(int(limit), 500))]
        return {
            "query": query,
            "count": len(matches),
            "index_generated_at": index.get("generated_at"),
            "matches": matches,
        }


    def relationships(
        self,
        query: str,
        *,
        limit: int = 25,
        include_reverse: bool = True,
        rebuild_if_missing: bool = True,
    ) -> dict[str, Any]:
        """Return direct and reverse relationships for the best index matches."""
        try:
            index = self.load()
        except FileNotFoundError:
            if not rebuild_if_missing:
                raise
            index = self.build()

        search_result = self.search(
            query,
            limit=max(1, min(int(limit), 100)),
            rebuild_if_missing=rebuild_if_missing,
        )
        files = [
            item for item in index.get("files", [])
            if isinstance(item, dict) and item.get("status") == "ok"
        ]
        by_path = {str(item.get("path")): item for item in files}

        targets = [str(row.get("path")) for row in search_result.get("matches", [])]
        target_names = {Path(path.replace("workspace:/", "")).name.lower(): path for path in targets}
        output = []

        for target_path in targets:
            item = by_path.get(target_path)
            if not item:
                continue

            outgoing = []
            for kind, values in (
                ("import", item.get("imports", [])),
                ("template", item.get("templates", [])),
                ("endpoint", item.get("url_endpoints", [])),
                ("static_asset", item.get("static_assets", [])),
                ("reference", item.get("references", [])),
            ):
                for value in values or []:
                    outgoing.append({"kind": kind, "value": value})

            incoming = []
            if include_reverse:
                target_lower = target_path.lower().replace("workspace:/", "")
                target_name = Path(target_lower).name
                target_stem = Path(target_lower).stem

                for candidate in files:
                    candidate_path = str(candidate.get("path", ""))
                    if candidate_path == target_path:
                        continue

                    fields = {
                        "import": candidate.get("imports", []),
                        "template": candidate.get("templates", []),
                        "endpoint": candidate.get("url_endpoints", []),
                        "static_asset": candidate.get("static_assets", []),
                        "reference": candidate.get("references", []),
                    }
                    for kind, values in fields.items():
                        for value in values or []:
                            value_lower = str(value).lower().replace("\\", "/")
                            if (
                                target_lower.endswith(value_lower)
                                or value_lower.endswith(target_name)
                                or (target_stem and target_stem in value_lower)
                            ):
                                incoming.append({
                                    "kind": kind,
                                    "from": candidate_path,
                                    "value": value,
                                })

            output.append({
                "path": target_path,
                "category": item.get("category"),
                "extension": item.get("extension"),
                "symbols": item.get("symbols", []),
                "routes": item.get("routes", []),
                "outgoing": outgoing[:100],
                "incoming": incoming[:100],
            })

        return {
            "query": query,
            "count": len(output),
            "index_generated_at": index.get("generated_at"),
            "relationships": output,
        }

    # ------------------------------------------------------------------
    # Traversal and parsing
    # ------------------------------------------------------------------

    def _walk(self, root: Path) -> Iterable[Path]:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                name for name in dirnames if name not in IGNORED_DIRECTORIES
            )
            for filename in sorted(filenames):
                yield Path(dirpath) / filename

    def _index_file(
        self,
        *,
        full_path: Path,
        workspace_path: str,
        stat: os.stat_result,
        fingerprint: str,
    ) -> dict[str, Any]:
        classification = file_classifier.classify(workspace_path)
        text = full_path.read_text(encoding="utf-8", errors="replace")
        extension = full_path.suffix.lower()

        item: dict[str, Any] = {
            **classification,
            "status": "ok",
            "size": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
            "fingerprint": fingerprint,
            "line_count": text.count("\n") + (1 if text else 0),
            "content_hash": hashlib.sha1(text.encode("utf-8")).hexdigest(),
            "symbols": [],
            "imports": [],
            "routes": [],
            "templates": [],
            "url_endpoints": [],
            "static_assets": [],
            "references": [],
            "parse_errors": [],
        }

        if extension == ".py":
            self._parse_python(text, item)
        elif extension in {".html", ".jinja", ".jinja2"}:
            self._parse_template(text, item)
        elif extension in {".js", ".ts"}:
            self._parse_javascript(text, item)
        elif extension in {".css", ".scss"}:
            self._parse_css(text, item)

        return item

    def _parse_python(self, text: str, item: dict[str, Any]) -> None:
        item["templates"] = sorted(set(_TEMPLATE_CALL_RE.findall(text)))
        item["url_endpoints"] = sorted(set(_URL_FOR_RE.findall(text)))

        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            item["parse_errors"].append(
                {
                    "type": "SyntaxError",
                    "line": exc.lineno,
                    "offset": exc.offset,
                    "message": exc.msg,
                }
            )
            return

        symbols: list[dict[str, Any]] = []
        imports: set[str] = set()
        routes: list[dict[str, Any]] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decorators = [self._expr_name(x) for x in node.decorator_list]
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                        "line": node.lineno,
                        "decorators": [x for x in decorators if x],
                    }
                )
                for decorator in node.decorator_list:
                    route = self._route_from_decorator(decorator, node.name)
                    if route:
                        routes.append(route)

            elif isinstance(node, ast.ClassDef):
                bases = [self._expr_name(base) for base in node.bases]
                symbols.append(
                    {
                        "name": node.name,
                        "kind": "class",
                        "line": node.lineno,
                        "bases": [x for x in bases if x],
                    }
                )

            elif isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = ",".join(alias.name for alias in node.names)
                imports.add(f"{'.' * node.level}{module}:{names}")

        item["symbols"] = sorted(symbols, key=lambda row: (row["line"], row["name"]))
        item["imports"] = sorted(imports)
        item["routes"] = sorted(routes, key=lambda row: (row.get("line", 0), row.get("path", "")))

    def _parse_template(self, text: str, item: dict[str, Any]) -> None:
        item["templates"] = sorted(set(_JINJA_LINK_RE.findall(text)))
        item["url_endpoints"] = sorted(set(_JINJA_URL_FOR_RE.findall(text)))
        item["static_assets"] = sorted(set(_STATIC_PATH_RE.findall(text)))

    def _parse_javascript(self, text: str, item: dict[str, Any]) -> None:
        item["references"] = sorted(set(_JS_IMPORT_RE.findall(text)))
        item["url_endpoints"] = sorted(
            set(re.findall(r"(?:fetch|axios\.(?:get|post|put|delete))\s*\(\s*[\"']([^\"']+)", text))
        )

    def _parse_css(self, text: str, item: dict[str, Any]) -> None:
        item["static_assets"] = sorted(
            value for value in set(_CSS_URL_RE.findall(text)) if not value.startswith("data:")
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fingerprint(stat: os.stat_result) -> str:
        return f"{stat.st_size}:{stat.st_mtime_ns}"

    @staticmethod
    def _expr_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = ProjectIndexer._expr_name(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        if isinstance(node, ast.Call):
            return ProjectIndexer._expr_name(node.func)
        if isinstance(node, ast.Subscript):
            return ProjectIndexer._expr_name(node.value)
        try:
            return ast.unparse(node)
        except Exception:
            return ""

    def _route_from_decorator(
        self,
        decorator: ast.AST,
        function_name: str,
    ) -> dict[str, Any] | None:
        if not isinstance(decorator, ast.Call):
            return None
        decorator_name = self._expr_name(decorator.func)
        if not decorator_name.endswith((".route", ".get", ".post", ".put", ".delete", ".patch")):
            return None

        route_path = ""
        if decorator.args and isinstance(decorator.args[0], ast.Constant):
            route_path = str(decorator.args[0].value)

        methods: list[str] = []
        for keyword in decorator.keywords:
            if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
                for value in keyword.value.elts:
                    if isinstance(value, ast.Constant):
                        methods.append(str(value.value).upper())
        suffix = decorator_name.rsplit(".", 1)[-1].upper()
        if suffix in {"GET", "POST", "PUT", "DELETE", "PATCH"} and not methods:
            methods = [suffix]

        return {
            "path": route_path,
            "endpoint": function_name,
            "methods": methods or ["GET"],
            "decorator": decorator_name,
            "line": getattr(decorator, "lineno", None),
        }

    @staticmethod
    def _summarize(files: list[dict[str, Any]], stats: IndexStats) -> dict[str, Any]:
        category_counts = Counter()
        extension_counts = Counter()
        totals = Counter()

        for item in files:
            if item.get("status") != "ok":
                totals["file_errors"] += 1
                continue
            category_counts[str(item.get("category", "other"))] += 1
            extension_counts[str(item.get("extension", ""))] += 1
            totals["symbols"] += len(item.get("symbols", []))
            totals["routes"] += len(item.get("routes", []))
            totals["imports"] += len(item.get("imports", []))
            totals["template_links"] += len(item.get("templates", []))
            totals["url_endpoints"] += len(item.get("url_endpoints", []))
            totals["parse_errors"] += len(item.get("parse_errors", []))

        return {
            "files": len(files),
            "scanned": stats.scanned,
            "reused": stats.reused,
            "skipped": stats.skipped,
            "errors": stats.errors,
            **dict(totals),
            "by_category": dict(sorted(category_counts.items())),
            "by_extension": dict(sorted(extension_counts.items())),
        }

    @staticmethod
    def _score(item: dict[str, Any], terms: list[str]) -> tuple[int, list[str]]:
        path = str(item.get("path", "")).lower()
        filename = str(item.get("filename", "")).lower()
        category = str(item.get("category", "")).lower()

        symbol_names = [str(x.get("name", "")).lower() for x in item.get("symbols", [])]
        routes = [str(x.get("path", "")).lower() for x in item.get("routes", [])]
        imports = [str(x).lower() for x in item.get("imports", [])]
        templates = [str(x).lower() for x in item.get("templates", [])]
        endpoints = [str(x).lower() for x in item.get("url_endpoints", [])]
        assets = [str(x).lower() for x in item.get("static_assets", [])]
        references = [str(x).lower() for x in item.get("references", [])]

        score = 0
        reasons: list[str] = []
        for term in terms:
            term_score = 0
            if term == filename or term in filename:
                term_score += 20
                reasons.append(f"filename:{term}")
            if term in path:
                term_score += 12
                reasons.append(f"path:{term}")
            if term == category:
                term_score += 8
                reasons.append(f"category:{term}")
            if any(term in value for value in symbol_names):
                term_score += 18
                reasons.append(f"symbol:{term}")
            if any(term in value for value in routes):
                term_score += 16
                reasons.append(f"route:{term}")
            if any(term in value for value in templates):
                term_score += 14
                reasons.append(f"template:{term}")
            if any(term in value for value in endpoints):
                term_score += 12
                reasons.append(f"endpoint:{term}")
            if any(term in value for value in imports):
                term_score += 8
                reasons.append(f"import:{term}")
            if any(term in value for value in assets + references):
                term_score += 6
                reasons.append(f"reference:{term}")
            if term_score == 0:
                return 0, []
            score += term_score

        return score, sorted(set(reasons))
