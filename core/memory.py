import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, List, Dict


class MemoryStore:
    """
    V8 Memory Layer
    - JSON file persistence
    - thread-safe async wrapper
    - corruption-safe reads
    - structured logs
    """

    def __init__(self, path: str = "C:/kushwell-agent/memory.json"):
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self.data: List[Dict[str, Any]] = self._load()

    # =========================================================
    # LOAD (SAFE)
    # =========================================================
    def _load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []

        try:
            raw = self.path.read_text(encoding="utf-8")
            return json.loads(raw) if raw else []
        except Exception:
            # corrupted memory fallback
            return []

    # =========================================================
    # SAVE (SAFE WRITE)
    # =========================================================
    def _save(self):
        tmp_path = self.path.with_suffix(".tmp")

        tmp_path.write_text(
            json.dumps(self.data, indent=2, default=str),
            encoding="utf-8"
        )

        tmp_path.replace(self.path)

    # =========================================================
    # ADD ENTRY (ASYNC SAFE)
    # =========================================================
    async def add(self, role: str, content: Any):
        async with self._lock:
            self.data.append({
                "time": datetime.utcnow().isoformat(),
                "role": role,
                "content": content
            })
            self._save()

    # =========================================================
    # READ LAST N
    # =========================================================
    def last(self, n: int = 10):
        return self.data[-n:]

    # =========================================================
    # GET ALL
    # =========================================================
    def get_all(self):
        return self.data

    # =========================================================
    # CLEAR MEMORY
    # =========================================================
    async def clear(self):
        async with self._lock:
            self.data = []
            self._save()