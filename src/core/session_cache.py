"""Persistent in-memory caches for download sessions and media info."""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from cachetools import TTLCache

from src.core.resources import runtime

_lock = threading.Lock()

_sessions: TTLCache = TTLCache(
    maxsize=runtime.SESSION_CACHE_MAX_SIZE,
    ttl=runtime.SESSION_TTL_SECONDS,
)
_info_cache: TTLCache = TTLCache(
    maxsize=runtime.INFO_CACHE_MAX_SIZE,
    ttl=runtime.INFO_CACHE_TTL_SECONDS,
)


@dataclass
class DownloadSession:
    url: str
    title: str
    reference_id: Optional[str] = None
    formats: Dict[str, Any] = field(default_factory=dict)
    duration: float = 0.0
    preview_only: bool = False


def create_session(
    url: str,
    title: str,
    formats: Dict[str, Any],
    *,
    reference_id: Optional[str] = None,
    duration: float = 0.0,
    preview_only: bool = False,
) -> str:
    session_id = secrets.token_hex(4)
    with _lock:
        _sessions[session_id] = DownloadSession(
            url=url,
            title=title,
            reference_id=reference_id,
            formats=formats,
            duration=duration,
            preview_only=preview_only,
        )
    return session_id


def get_session(session_id: str) -> Optional[DownloadSession]:
    with _lock:
        return _sessions.get(session_id)


def cache_info(url: str, info: Dict[str, Any]) -> None:
    with _lock:
        _info_cache[url] = info


def get_cached_info(url: str) -> Optional[Dict[str, Any]]:
    with _lock:
        return _info_cache.get(url)
