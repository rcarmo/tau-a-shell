"""Detect and normalize files dragged or pasted into the terminal."""

from __future__ import annotations

import shlex
from pathlib import Path
from urllib.parse import unquote, urlparse

__all__ = ["normalize_dropped_paths"]


def normalize_dropped_paths(text: str) -> str | None:
    """Return normalized prompt text when *text* looks like a file drop."""
    stripped = text.strip()
    if not stripped:
        return None

    whole = _token_to_path(stripped)
    if whole is not None:
        return _quote_path(whole)

    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError:
        return None
    if not tokens:
        return None

    paths: list[str] = []
    for token in tokens:
        path = _token_to_path(token)
        if path is None:
            return None
        paths.append(path)
    return " ".join(_quote_path(path) for path in paths)


def _token_to_path(token: str) -> str | None:
    candidate = token
    if candidate.startswith("file://"):
        parsed = urlparse(candidate)
        if parsed.netloc not in ("", "localhost"):
            return None
        candidate = unquote(parsed.path)
    path = Path(candidate)
    if not path.is_absolute() or not path.exists():
        return None
    return candidate


def _quote_path(path: str) -> str:
    if not any(char.isspace() for char in path):
        return path
    escaped = path.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
