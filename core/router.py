import json
import re
import asyncio
from typing import Any, Dict, List
from openai import AsyncOpenAI
from core.intent_parser import intent_parser
from core.intents.intent_planner import intent_planner
from core.semantic_parser import semantic_parser
from core.semantic_planner import semantic_planner


class GPTRouterV8:
    """
    Brain V8 Router (Seed Graph Generator)

    Responsibilities:
    - Convert user input → initial execution graph
    - Provide fallback deterministic graph if LLM fails
    - Ensure strict JSON safety
    - NEVER execute tools (executor does that)
    """

    def __init__(self, model: str = "gpt-4o-mini"):
        self.client = AsyncOpenAI()
        self.model = model

    # =========================================================
    # PUBLIC ENTRYPOINT
    # =========================================================
    async def plan(self, user_input: str) -> Dict[str, Any]:
        print("\n🧠 [V8 ROUTER] planning started")

        try:
            raw = await self._call_llm(user_input)
            parsed = self._safe_json_parse(raw)
            graph = self._normalize_graph(parsed)

            print("🧠 [V8 ROUTER] LLM graph created")
            return graph

        except Exception as e:
            print("⚠️ [V8 ROUTER] LLM FAILED → OFFLINE MODE:", e)
            return self._offline_seed_graph(user_input)

    # =========================================================
    # LLM CALL (ASYNC SAFE)
    # =========================================================
    async def _call_llm(self, user_input: str) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Brain V8 Graph Router. "
                        "Return ONLY valid JSON. No markdown. No text. "
                        "Output must be a SEED GRAPH with nodes."
                    )
                },
                {
                    "role": "user",
                    "content": f"""
Convert this request into a minimal execution graph.

RULES:
- Output JSON ONLY
- Must follow schema:

{{
  "nodes": [
    {{
      "id": "A",
      "tool": "tool_name",
      "args": {{}},
      "deps": []
    }}
  ]
}}

AVAILABLE TOOLS:
- list_directory
- read_text_file
- write_file
- search_files
- get_file_info
- move_file

USER REQUEST:
{user_input}
"""
                }
            ],
            temperature=0.2,
        )

        text = (response.choices[0].message.content or "").strip()
        print("🧠 [V8 ROUTER] RAW LLM OUTPUT:\n", text)
        return text

    # =========================================================
    # SAFE JSON PARSER (HARDENED)
    # =========================================================
    def _safe_json_parse(self, text: str) -> Dict[str, Any]:
        if not text:
            raise ValueError("Empty LLM response")

        # remove code fences if model breaks rules
        text = re.sub(r"```json|```", "", text).strip()

        return json.loads(text)

    # =========================================================
    # GRAPH NORMALIZER (CRITICAL SAFETY LAYER)
    # =========================================================
    def _normalize_graph(self, graph: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(graph, dict):
            raise ValueError("Graph must be dict")

        nodes = graph.get("nodes", [])
        if not isinstance(nodes, list):
            nodes = []

        cleaned_nodes = []

        for n in nodes:
            if not isinstance(n, dict):
                continue

            node_id = n.get("id")
            tool = n.get("tool")

            if not node_id or not tool:
                continue

            cleaned_nodes.append({
                "id": str(node_id),
                "tool": str(tool),
                "args": n.get("args", {}) or {},
                "deps": n.get("deps", []) or []
            })

        return {
            "nodes": cleaned_nodes
        }

    # =========================================================
    # OFFLINE SEED GRAPH (NO LLM)
    # =========================================================
    
    def _offline_seed_graph(self, user_input: str) -> dict:
        print("🧠 [V8 ROUTER] OFFLINE BRAIN ACTIVE")

        request = semantic_parser.parse(user_input)
        print("🧠 [V8 ROUTER] SEMANTIC REQUEST:", request)

        graph = semantic_planner.plan(request)
        print("🧠 [V8 ROUTER] SEMANTIC GRAPH:", graph)

        return graph