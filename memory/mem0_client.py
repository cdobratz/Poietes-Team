"""
memory/mem0_client.py — Shared Mem0 memory layer.

Supports both:
  - mem0ai cloud (MEMORY_PROVIDER=cloud, MEM0_API_KEY set)
  - self-hosted Mem0 MCP server (MEMORY_PROVIDER=mcp)
  - in-process stub when neither is available (for local testing)
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ─── Try importing mem0ai ─────────────────────────────────────────────────────
try:
    from mem0 import MemoryClient as _Mem0Cloud   # type: ignore
    MEM0_AVAILABLE = True
except ImportError:
    MEM0_AVAILABLE = False


class InMemoryFallback:
    """Simple dict-based memory for local/testing use."""

    def __init__(self):
        self._store: list[dict] = []

    def add(self, messages: list[dict], user_id: str = "", metadata: dict | None = None) -> dict:
        content = messages[-1]["content"] if messages else ""
        entry = {"memory": content, "user_id": user_id, "metadata": metadata or {}}
        self._store.append(entry)
        return entry

    def search(self, query: str, user_id: str = "", filters: dict | None = None) -> dict:
        """Naive substring search over stored memories."""
        results = []
        for entry in self._store:
            if user_id and entry.get("user_id") != user_id:
                continue
            if query.lower() in entry.get("memory", "").lower():
                results.append(entry)
        return {"results": results[:5]}

    def get_all(self, user_id: str = "") -> list[dict]:
        return [e for e in self._store if not user_id or e.get("user_id") == user_id]


class MCPMemoryClient:
    """Wraps a Mem0 MCP server via HTTP."""

    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"

    def _call(self, tool: str, params: dict) -> dict:
        import httpx
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": params},
        }
        try:
            r = httpx.post(f"{self.base_url}/mcp", json=payload, headers=self._headers, timeout=15)
            r.raise_for_status()
            return r.json().get("result", {})
        except Exception as e:
            logger.warning(f"Mem0 MCP call failed ({tool}): {e}")
            return {}

    def add(self, messages: list[dict], user_id: str = "", metadata: dict | None = None) -> dict:
        content = messages[-1]["content"] if messages else ""
        return self._call("add_memory", {
            "content": content,
            "user_id": user_id,
            "metadata": metadata or {},
        })

    def search(self, query: str, user_id: str = "", filters: dict | None = None) -> dict:
        return self._call("search_memory", {
            "query": query,
            "user_id": user_id,
            "filters": filters or {},
        })

    def get_all(self, user_id: str = "") -> list[dict]:
        result = self._call("get_all_memories", {"user_id": user_id})
        return result.get("memories", [])


def build_memory_client(settings) -> Any:
    """
    Factory: returns the best available memory client based on config.
    Priority: Mem0 cloud > MCP server > in-process fallback
    """
    mem0_cfg = settings.mcp.mem0

    if MEM0_AVAILABLE and mem0_cfg.api_key:
        logger.info("Using Mem0 cloud client")
        return _Mem0Cloud(api_key=mem0_cfg.api_key)

    if mem0_cfg.enabled and mem0_cfg.url:
        logger.info(f"Using Mem0 MCP client at {mem0_cfg.url}")
        return MCPMemoryClient(mem0_cfg.url, mem0_cfg.api_key)

    logger.info("Using in-process memory fallback (ephemeral)")
    return InMemoryFallback()
