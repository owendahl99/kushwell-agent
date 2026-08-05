import asyncio
import json
import time
from datetime import datetime

from core.mcp_client import MCPFilesystemClient
from core.router import GPTRouterV8
from core.dag_executor import DAGExecutor
from core.memory import MemoryStore
from core.semantic_parser import semantic_parser
from core.semantic_planner import semantic_planner
from core.knowledge import knowledge_registry


class KushwellAgent:
    """
    FINAL INTEGRATION LAYER

    Semantic Parser
        → Deterministic Semantic Planner when supported
        → GPT Router only as a fallback
        → DAG Executor
        → Clean UI Output
    """

    DETERMINISTIC_ACTIONS = {
        "answer",
        "acquisition_status",
        "acquisition_runs",
        "plan_acquisition",
        "run_acquisition",
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
        Use the deterministic semantic planner whenever the parser
        recognizes the operation.

        This prevents the GPT router from turning a knowledge question
        into literal text-search nodes.
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
    # MAIN EXECUTION PIPELINE
    # =========================================================
    async def run(self, user_input: str):
        start_time = time.time()

        user_input = str(user_input or "").strip()

        if not user_input:
            return {
                "answer": "Please enter a request.",
                "summary": {
                    "success_count": 0,
                    "failed_count": 0,
                    "nodes": [],
                },
                "raw": {},
            }

        await self._trace("USER INPUT", user_input)
        await self.memory.add("user", user_input)

        # -----------------------------------------------------
        # 1. Parse the request once.
        # -----------------------------------------------------
        semantic_request = semantic_parser.parse(user_input)

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

        # -----------------------------------------------------
        # 2. Build one graph.
        #
        # Recognized operations use the deterministic semantic
        # planner. The GPT router is only a fallback.
        # -----------------------------------------------------
        graph = await self._build_graph(
            user_input=user_input,
            semantic_request=semantic_request,
        )

        if not graph or not graph.get("nodes"):
            final_output = {
                "answer": (
                    "The Brain understood the request but could not build "
                    "an executable plan."
                ),
                "summary": {
                    "success_count": 0,
                    "failed_count": 1,
                    "nodes": [],
                },
                "raw": {
                    "semantic_request": semantic_request,
                    "graph": graph or {},
                },
            }

            await self._trace(
                "FINAL OUTPUT",
                final_output,
            )

            await self.memory.add("final", final_output)
            return final_output

        # Keep the semantic request attached to the graph.
        graph.setdefault("request", semantic_request)

        await self._trace(
            "EXECUTION GRAPH",
            graph,
        )

        # -----------------------------------------------------
        # 3. Execute exactly once.
        #
        # DAGExecutor performs its own graph-expansion rounds.
        # -----------------------------------------------------
        execution_result = await self.executor.execute(
            graph,
            request=semantic_request,
        )

        await self._trace(
            "EXECUTION RESULT",
            execution_result,
        )

        # -----------------------------------------------------
        # 4. Package the DAG answer for the UI.
        # -----------------------------------------------------
        final_output = self._reduce_output(execution_result)

        await self._trace(
            "FINAL OUTPUT",
            final_output,
        )

        await self.memory.add("final", final_output)

        duration = round(time.time() - start_time, 4)

        final_output["duration"] = duration

        await self._trace(
            "TOTAL EXECUTION TIME",
            duration,
        )

        return final_output

    # =========================================================
    # OUTPUT REDUCTION LAYER
    # =========================================================
    def _reduce_output(self, execution_result: dict):
        if not isinstance(execution_result, dict):
            return {
                "answer": "No valid execution result was returned.",
                "summary": {
                    "success_count": 0,
                    "failed_count": 1,
                    "nodes": [],
                },
                "raw": execution_result or {},
            }

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