"""Session storage protocols and JSONL implementation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from tau_agent.session.entries import SessionEntry
from tau_agent.session.jsonl import entries_from_json_lines, entry_to_json_line


class SessionStorage(Protocol):
    """Append-only session storage interface."""

    async def append(self, entry: SessionEntry) -> None:
        """Append one entry to storage."""
        ...

    async def read_all(self) -> list[SessionEntry]:
        """Read all entries in storage order."""
        ...


class JsonlSessionStorage:
    """Local append-only JSONL session storage."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    async def append(self, entry: SessionEntry) -> None:
        """Append one entry, creating parent directories if needed."""
        await asyncio.to_thread(self._append_sync, entry)

    def _append_sync(self, entry: SessionEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(entry_to_json_line(entry))

    async def read_all(self) -> list[SessionEntry]:
        """Read all entries in file order. Missing files are empty sessions."""
        return await asyncio.to_thread(self._read_all_sync)

    def _read_all_sync(self) -> list[SessionEntry]:
        if not self.path.exists():
            return []
        return entries_from_json_lines(self.path.read_text(encoding="utf-8").split("\n"))
