import asyncio
import json
import os
import time
from datetime import datetime
from typing import Any, Mapping

from core.mcp_client import MCPFilesystemClient
from core.router import GPTRouterV8
from core.dag_executor import DAGExecutor, ExecutorConfig
from core.memory import MemoryStore
from core.semantic_parser import semantic_parser
from core.semantic_planner import semantic_planner
from core.semantic_request import SemanticRequest
from core.knowledge import knowledge_registry


STRAIN_RESEARCH_TIMEOUT_ENV = "KUSHWELL_BRAIN_STRAIN_RESEARCH_TIMEOUT"
DEFAULT_STRAIN_RESEARCH_TIMEOUT = 300.0


def _bounded_strain_research_timeout() -> float:
    raw = os.getenv(
        STRAIN_RESEARCH_TIMEOUT_ENV,
        str(DEFAULT_STRAIN_RESEARCH_TIMEOUT),
    )
    try:
        timeout = float(raw)
    except (TypeError, ValueError):
        timeout = DEFAULT_STRAIN_RESEARCH_TIMEOUT
    return min(max(timeout, 120.0), 900.0)


class KushwellAgent:
    """
    FINAL INTEGRATION LAYER

    Semantic Parser
        → Deterministic Semantic Planner when supported
        → GPT Router only as a fallback
        → DAG Executor
        → Clean UI Output

    Typed commands bypass natural-language classification while still using the
    same deterministic planner, governed tool registry, DAG executor, and output
    reduction pipeline.
    """

    DETERMINISTIC_ACTIONS = {
        "answer",
        "acquisition_status",
        "acquisition_runs",
        "plan_acquisition",
        "run_acquisition",
        "research_strain",
        "recommend",
        "analyze_evidence",
        "search",
        "list",
        "read",
        "audit",
        "move",
        "delete",
        "write",
        "cleanup",
    }

    def __init__(self):
        self.mcp = MCPFilesystemClient()
        self.router = GPTRouterV8()
        self.memory = MemoryStore()
        self.executor = DAGExecutor(self.mcp, self.memory)
        self.strain_research_timeout = _bounded_strain_research_timeout()
        self.strain_research_executor = DAGExecutor(
            self.mcp,
            self.memory,
            config=ExecutorConfig(
                max_parallel_tasks=1,
                max_retries=0,
                retry_backoff=0.0,
                task_timeout=self.strain_research_timeout,
                fail_fast=True,
                debug=self.executor.config.debug,
            ),
        )
        self.trace_id = 0

    # =========================================================
    # DEBUG TRACE
    # =========================================================
    async def _trace(self, label: str, data=None):
        self.trace_id += 1
        stamp = datetime.utcnow().isoformat()

        print(f"\n🧩 [TRACE {self.trace_id}] {label}")

        if data is not None:
            print(json.dumps(data, indent=2, default=str))

        await self.memory.add(
            "trace",
            {
                "id": self.trace_id,
                "time": stamp,
                "label": label,
                "data": str(data),
            },
        )

    # =========================================================
    # START MCP
    # =========================================================
    async def start(self):
        await self._trace("MCP STARTING")
        await self.mcp.start()
        await self._trace("MCP READY")

    # =========================================================
    # GRAPH SELECTION
    # =========================================================
    async def _build_graph(
        self,
        user_input: str,
        semantic_request: dict,
    ) -> dict:
        """
        Use the deterministic semantic planner whenever the parser or typed
        command recognizes the operation.

        This prevents the GPT router from turning governed strain identity
        research into a recommendation task.
        """

        action = semantic_request.get("action")

        if action in self.DETERMINISTIC_ACTIONS:
            graph = semantic_planner.plan(semantic_request)

            await self._trace(
                "SEMANTIC PLANNER GRAPH",
                graph,
            )

            if graph and graph.get("nodes"):
                return graph

        await self._trace(
            "SEMANTIC PLANNER FALLBACK",
            {
                "reason": "No usable deterministic graph",
                "action": action,
            },
        )

        graph = await self.router.plan(user_input)

        await self._trace(
            "GPT ROUTER GRAPH",
            graph,
        )

        return graph

    # =========================================================
    # NATURAL-LANGUAGE ENTRY POINT
    # =========================================================
    async def run(self, user_input: str):
        user_input = str(user_input or "").strip()

        if not user_input:
            return self._empty_output("Please enter a request.")

        await self._trace("USER INPUT", user_input)
        await self.memory.add("user", user_input)

        semantic_request = semantic_parser.parse(user_input)

        return await self._execute_semantic_request(
            semantic_request=semantic_request,
            user_input=user_input,
            started_at=time.time(),
        )

    # =========================================================
    # TYPED COMMAND ENTRY POINT
    # =========================================================
    async def run_command(self, command: Mapping[str, Any]):
        command = dict(command or {})
        action = str(command.get("action") or "").strip()

        if action != "research_strain":
            raise ValueError(
                f"Unsupported typed Brain command: {action or 'missing action'}."
            )

        candidate_name = str(command.get("candidate_name") or "").strip()
        if not candidate_name:
            raise ValueError("research_strain requires candidate_name.")

        normalized_name = str(
            command.get("normalized_name") or candidate_name.casefold()
        ).strip()
        actor = str(command.get("requested_by") or "system").strip()

        semantic_request = SemanticRequest(
            action="research_strain",
            subject="strain_identity",
            source="governed:strain_research",
            destination=None,
            filters=["requires_sources", "uninfused_flower_only"],
            constraints={
                "operations": ["research_strain"],
                "deliverable": "strain_evidence_brief",
                "candidate_name": candidate_name,
                "normalized_name": normalized_name,
                "review_id": command.get("review_id"),
                "marketplace_mentions": int(
                    command.get("marketplace_mentions") or 0
                ),
                "research_queries": command.get("research_queries") or [],
                "requested_by": actor,
                "scope": str(
                    command.get("scope")
                    or "identity_lineage_flower_chemistry"
                ),
                "auto_promote": False,
                "overwrite": False,
                "dry_run": False,
                "outcomes": [],
                "search_term": None,
            },
            requires_confirmation=False,
            confidence=100,
            original_request=(
                f"Typed research_strain command for {candidate_name}"
            ),
        ).to_dict()

        await self._trace("TYPED COMMAND", command)
        await self.memory.add("command", command)

        return await self._execute_semantic_request(
            semantic_request=semantic_request,
            user_input=semantic_request["original_request"],
            started_at=time.time(),
        )

    # =========================================================
    # SHARED EXECUTION PIPELINE
    # =========================================================
    async def _execute_semantic_request(
        self,
        *,
        semantic_request: dict,
        user_input: str,
        started_at: float,
    ) -> dict:
        await self._trace(
            "SEMANTIC REQUEST",
            semantic_request,
        )

        knowledge_context = knowledge_registry.request_context(semantic_request)
        semantic_request["knowledge_context"] = knowledge_context

        await self._trace(
            "KNOWLEDGE CONTRACTS",
            knowledge_context,
        )

        graph = await self._build_graph(
            user_input=user_input,
            semantic_request=semantic_request,
        )

        if not graph or not graph.get("nodes"):
            final_output = self._empty_output(
                "The Brain understood the request but could not build an "
                "executable plan.",
                failed_count=1,
                raw={
                    "semantic_request": semantic_request,
                    "graph": graph or {},
                },
            )

            await self._trace("FINAL OUTPUT", final_output)
            await self.memory.add("final", final_output)
            return final_output

        graph.setdefault("request", semantic_request)

        await self._trace(
            "EXECUTION GRAPH",
            graph,
        )

        executor = (
            self.strain_research_executor
            if semantic_request.get("action") == "research_strain"
            else self.executor
        )
        execution_result = await executor.execute(
            graph,
            request=semantic_request,
        )

        if semantic_request.get("action") == "research_strain":
            self._normalize_strain_research_failure(execution_result)

        await self._trace(
            "EXECUTION RESULT",
            execution_result,
        )

        final_output = self._reduce_output(execution_result)
        final_output["duration"] = round(time.time() - started_at, 4)

        await self._trace(
            "FINAL OUTPUT",
            final_output,
        )
        await self.memory.add("final", final_output)

        await self._trace(
            "TOTAL EXECUTION TIME",
            final_output["duration"],
        )

        return final_output

    def _normalize_strain_research_failure(self, execution_result: Any) -> None:
        if not isinstance(execution_result, dict):
            return

        message = (
            "Strain research failed without a provider diagnostic. "
            f"The Brain execution limit is {self.strain_research_timeout:g} seconds."
        )
        for collection_name in ("results", "errors"):
            collection = execution_result.get(collection_name)
            if not isinstance(collection, dict):
                continue
            node = collection.get("strain_research")
            if not isinstance(node, dict):
                continue
            if node.get("status") == "failed" and not str(
                node.get("error") or ""
            ).strip():
                node["error"] = message

    # =========================================================
    # OUTPUT REDUCTION LAYER
    # =========================================================
    @staticmethod
    def _empty_output(
        answer: str,
        *,
        failed_count: int = 0,
        raw: Any = None,
    ) -> dict:
        return {
            "answer": answer,
            "summary": {
                "success_count": 0,
                "failed_count": failed_count,
                "nodes": [],
            },
            "raw": raw or {},
        }

    def _reduce_output(self, execution_result: dict):
        if not isinstance(execution_result, dict):
            return self._empty_output(
                "No valid execution result was returned.",
                failed_count=1,
                raw=execution_result or {},
            )

        execution_answer = str(
            execution_result.get("answer") or ""
        ).strip()

        execution_summary = (
            execution_result.get("summary") or {}
        )

        if execution_answer:
            return {
                "answer": execution_answer,
                "summary": {
                    "success_count": execution_summary.get(
                        "successful_nodes",
                        0,
                    ),
                    "failed_count": execution_summary.get(
                        "failed_nodes",
                        0,
                    ),
                    "nodes": [],
                },
                "raw": execution_result,
            }

        results = execution_result.get("results") or {}

        summary = {
            "success_count": 0,
            "failed_count": 0,
            "nodes": [],
        }

        readable_parts = []

        for node_id, result in results.items():
            status = (
                result.get("status")
                if isinstance(result, dict)
                else "unknown"
            )

            if status == "success":
                summary["success_count"] += 1
            else:
                summary["failed_count"] += 1

            summary["nodes"].append(
                {
                    "node": node_id,
                    "status": status,
                }
            )

            if not isinstance(result, dict):
                continue

            tool = result.get("tool")
            output = result.get("result")

            # -------------------------------------------------
            # Governed strain-research brief
            # -------------------------------------------------
            if (
                tool == "research_strain"
                and isinstance(output, dict)
            ):
                answer = str(output.get("answer") or "").strip()
                if answer:
                    readable_parts.append(answer)
                continue

            # -------------------------------------------------
            # Final synthesized answer
            # -------------------------------------------------
            if (
                tool == "answer_question"
                and isinstance(output, dict)
            ):
                answer = str(
                    output.get("answer") or ""
                ).strip()

                if answer:
                    readable_parts.append(answer)

                continue

            # -------------------------------------------------
            # Recursive literal text search
            # -------------------------------------------------
            if (
                tool == "search_files"
                and isinstance(output, dict)
            ):
                matches = output.get("matches") or []
                term = str(output.get("term") or "")
                count = output.get("count", len(matches))

                if not matches:
                    readable_parts.append(
                        f'No matches found for "{term}".'
                    )
                    continue

                lines = [
                    (
                        f'Search completed. Found {count} '
                        f'match(es) for "{term}".'
                    ),
                    "",
                ]

                for index, match in enumerate(
                    matches,
                    start=1,
                ):
                    path = match.get(
                        "path",
                        "Unknown file",
                    )
                    line_number = match.get(
                        "line",
                        "?",
                    )
                    text = str(
                        match.get("text") or ""
                    ).strip()

                    lines.append(
                        f"{index}. {path}"
                    )
                    lines.append(
                        f"   Line {line_number}: {text}"
                    )
                    lines.append("")

                readable_parts.append(
                    "\n".join(lines).strip()
                )

        if readable_parts:
            final_answer = "\n\n".join(
                readable_parts
            ).strip()
        else:
            final_answer = (
                "The execution completed, but no final answer was "
                "produced."
            )

        return {
            "answer": final_answer,
            "summary": summary,
            "raw": execution_result,
        }


# =========================================================
# CLI
# =========================================================
async def main():
    agent = KushwellAgent()
    await agent.start()

    print("\n🚀 KUSHWELL FINAL SYSTEM READY")

    while True:
        user_input = input("\nKushwell > ").strip()

        if user_input.lower() in {
            "exit",
            "quit",
        }:
            break

        output = await agent.run(user_input)

        print("\n✅ FINAL RESPONSE:\n")
        print(output.get("answer", ""))

        print("\nSUMMARY:")
        print(
            json.dumps(
                output.get("summary", {}),
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
