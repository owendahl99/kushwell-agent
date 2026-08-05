import asyncio
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from core.tool_registry import registry
from core.workspace import WorkspaceManager
from core.validator import validator
from core.permissions import permissions
from core.project_filters import should_read
from core.project_indexer import ProjectIndexer
from core.capabilities.capability_auditor import CapabilityAuditor
from core.atlas.atlas_console import AtlasConsole


class MCPToolError(Exception):
    pass


class MCPFilesystemClient:
    def __init__(
        self,
        root: str = "C:/Users/Kushwell/app",
        workspace_root: str = "C:/Users/Kushwell/app",
    ):
        self.root = root
        self.session: ClientSession | None = None
        self._ctx = None
        self._started = False
        self.workspace = WorkspaceManager(workspace_root)
        self.project_indexer = ProjectIndexer(self.workspace)
        self.capability_auditor = CapabilityAuditor(self.project_indexer)
        self.atlas = AtlasConsole(self.capability_auditor)

    async def start(self):
        if self._started:
            return

        server = StdioServerParameters(
            command="npx",
            args=[
                "-y",
                "@modelcontextprotocol/server-filesystem",
                self.root,
            ],
        )

        self._ctx = stdio_client(server)
        read, write = await self._ctx.__aenter__()

        self.session = ClientSession(read, write)
        await self.session.__aenter__()
        await self.session.initialize()

        self._started = True

    async def call(self, tool_name: str, args: dict):
        await self.start()

        print("MCP CALL:", tool_name, args)

        try:
            args = dict(args or {})

            # Local custom tools. Do NOT send these to the external filesystem
            # MCP server.
            if tool_name == "search_files":
                return self._search_files(args)

            if tool_name == "project_index":
                return self._project_index(args)

            if tool_name == "search_project_index":
                return self._search_project_index(args)

            if tool_name == "get_project_relationships":
                return self._get_project_relationships(args)

            if tool_name == "audit_platform_capabilities":
                return self._audit_platform_capabilities(args)

            if tool_name == "get_atlas_dashboard":
                return self._get_atlas_dashboard(args)

            if tool_name == "research_strain":
                from core.strain_research import research_strain

                return await asyncio.to_thread(
                    research_strain,
                    args,
                )

            args = validator.validate(tool_name, args)
            permissions.check(tool_name, args)

            tool = registry.get(tool_name)

            if "path" in args:
                print("BEFORE RESOLVE:", args["path"])
                args["path"] = self.workspace.resolve(args["path"])
                print("AFTER RESOLVE:", args["path"])

            result = await self.session.call_tool(
                tool.mcp_name,
                args,
            )

            print("MCP RESULT:", result)

            result = self._normalize_result(result)
            self._raise_if_tool_error(result)

            return result

        except Exception as e:
            print("MCP ERROR:", str(e))
            raise

    def _project_index(self, args: dict) -> dict:
        source = args.get("path") or "workspace:/"
        force = bool(args.get("force", False))
        index = self.project_indexer.build(source=source, force=force)
        return {
            "tool": "project_index",
            "status": "success",
            "index_path": self.project_indexer.index_path,
            "generated_at": index.get("generated_at"),
            "summary": index.get("summary", {}),
        }

    def _search_project_index(self, args: dict) -> dict:
        return {
            "tool": "search_project_index",
            "status": "success",
            **self.project_indexer.search(
                query=args.get("query") or "",
                limit=args.get("limit", 50),
                categories=args.get("categories"),
                extensions=args.get("extensions"),
            ),
        }

    def _get_project_relationships(self, args: dict) -> dict:
        return {
            "tool": "get_project_relationships",
            "status": "success",
            **self.project_indexer.relationships(
                query=args.get("query") or "",
                limit=args.get("limit", 25),
                include_reverse=bool(args.get("include_reverse", True)),
            ),
        }

    def _audit_platform_capabilities(self, args: dict) -> dict:
        capability = str(args.get("capability") or "").strip()
        keys = [capability] if capability else None
        result = self.capability_auditor.audit_all(
            rebuild_index=bool(args.get("rebuild_index", False)),
            capability_keys=keys,
            persist=bool(args.get("persist", True)),
        )
        return {
            "tool": "audit_platform_capabilities",
            "status": "success",
            **result,
        }

    def _get_atlas_dashboard(self, args: dict) -> dict:
        result = self.atlas.build(
            rebuild_index=bool(args.get("rebuild_index", False)),
            persist=bool(args.get("persist", True)),
        )
        return {
            "tool": "get_atlas_dashboard",
            "status": "success",
            **result,
        }

    def _search_files(self, args: dict) -> dict:
        workspace_path = args.get("path") or "workspace:/"
        term = (args.get("term") or args.get("query") or "").strip()

        if not term:
            return {
                "tool": "search_files",
                "status": "failed",
                "error": "Missing search term.",
                "matches": [],
                "count": 0,
            }

        root = Path(self.workspace.resolve(workspace_path))
        term_lower = term.lower()

        matches = []
        skipped = 0

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d not in {
                    "__pycache__",
                    ".git",
                    ".venv",
                    "venv",
                    "node_modules",
                    ".pytest_cache",
                    ".mypy_cache",
                    ".idea",
                    ".vscode",
                }
            ]

            for filename in filenames:
                full_path = Path(dirpath) / filename

                try:
                    workspace_file = self.workspace.to_workspace(full_path)
                except Exception:
                    skipped += 1
                    continue

                if not should_read(workspace_file):
                    skipped += 1
                    continue

                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_number, line in enumerate(f, start=1):
                            if term_lower in line.lower():
                                matches.append(
                                    {
                                        "path": workspace_file,
                                        "line": line_number,
                                        "text": line.strip(),
                                    }
                                )
                except Exception:
                    skipped += 1
                    continue

        return {
            "tool": "search_files",
            "status": "success",
            "term": term,
            "root": workspace_path,
            "count": len(matches),
            "skipped": skipped,
            "matches": matches,
        }

    def _normalize_result(self, result):
        if hasattr(result, "content"):
            return result.content

        return result

    def _raise_if_tool_error(self, result):
        if isinstance(result, dict) and "error" in result:
            raise MCPToolError(str(result["error"]))

        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    text = str(item.get("text", "")).lower()
                    if "access denied" in text or "error" in item:
                        raise MCPToolError(
                            item.get("error") or item.get("text") or str(item)
                        )

    async def list_tools(self):
        await self.start()
        return await self.session.list_tools()

    async def stop(self):
        if self.session:
            try:
                await self.session.__aexit__(None, None, None)
            except Exception:
                pass

        if self._ctx:
            try:
                await self._ctx.__aexit__(None, None, None)
            except Exception:
                pass

        self.session = None
        self._ctx = None
        self._started = False
