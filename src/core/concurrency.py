"""Per-user throttling, in-flight dedup, and global task caps."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Set, TypeVar

from src.core.resources import runtime

T = TypeVar("T")

_upload_sem: Optional[asyncio.Semaphore] = None
_background_sem: Optional[asyncio.Semaphore] = None
_inflight_info: Dict[str, asyncio.Task] = {}
_inflight_info_lock = asyncio.Lock()


def get_upload_sem() -> asyncio.Semaphore:
    global _upload_sem
    if _upload_sem is None:
        _upload_sem = asyncio.Semaphore(runtime.MAX_CONCURRENT_UPLOADS)
    return _upload_sem


def get_background_sem() -> asyncio.Semaphore:
    global _background_sem
    if _background_sem is None:
        _background_sem = asyncio.Semaphore(runtime.MAX_BACKGROUND_TASKS)
    return _background_sem


class UserGate:
    """Rate limit and per-user active download tracking."""

    def __init__(self) -> None:
        self._timestamps: Dict[int, Deque[float]] = defaultdict(deque)
        self._active_downloads: Dict[int, int] = defaultdict(int)
        self._help_last: Dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def check_request(self, user_id: Optional[int], action: str = "request") -> Optional[str]:
        if user_id is None:
            return None

        async with self._lock:
            now = time.monotonic()

            if action == "help":
                last = self._help_last.get(user_id, 0.0)
                if now - last < 1.0:
                    return "debounced"
                self._help_last[user_id] = now
                return None

            window = self._timestamps[user_id]
            cutoff = now - 60.0
            while window and window[0] < cutoff:
                window.popleft()

            if len(window) >= runtime.USER_RATE_LIMIT_PER_MINUTE:
                return "⏳ <i>Too many requests. Please wait a moment and try again.</i>"

            window.append(now)
            return None

    async def try_start_download(self, user_id: Optional[int]) -> Optional[str]:
        if user_id is None:
            return None

        async with self._lock:
            active = self._active_downloads[user_id]
            if active >= runtime.USER_MAX_ACTIVE_DOWNLOADS:
                return (
                    "⏳ <i>You already have a download in progress. "
                    "Wait for it to finish or cancel it first.</i>"
                )
            self._active_downloads[user_id] += 1
            return None

    async def finish_download(self, user_id: Optional[int]) -> None:
        if user_id is None:
            return
        async with self._lock:
            active = self._active_downloads[user_id]
            if active <= 1:
                self._active_downloads.pop(user_id, None)
            else:
                self._active_downloads[user_id] = active - 1


user_gate = UserGate()


async def dedupe_inflight(key: str, coro_factory) -> T:
    """Run one coroutine per key; concurrent callers share the same result."""
    async with _inflight_info_lock:
        existing = _inflight_info.get(key)
        if existing is not None:
            return await asyncio.shield(existing)

        task = asyncio.create_task(coro_factory())
        _inflight_info[key] = task

    try:
        return await task
    finally:
        async with _inflight_info_lock:
            if _inflight_info.get(key) is task:
                _inflight_info.pop(key, None)


class ActiveDownloadRegistry:
    """Prevent duplicate downloads for the same URL+format while one is running."""

    def __init__(self) -> None:
        self._keys: Set[str] = set()
        self._lock = asyncio.Lock()

    async def try_acquire(self, key: str) -> bool:
        async with self._lock:
            if key in self._keys:
                return False
            self._keys.add(key)
            return True

    async def release(self, key: str) -> None:
        async with self._lock:
            self._keys.discard(key)


download_registry = ActiveDownloadRegistry()
