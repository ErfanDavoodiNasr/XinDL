"""Detect host resources and derive all runtime performance limits automatically."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeLimits:
    MAX_CONCURRENT_DOWNLOADS: int
    MAX_CONCURRENT_INFO: int
    MAX_CONCURRENT_UPLOADS: int
    MAX_BACKGROUND_TASKS: int
    THREAD_POOL_WORKERS: int
    USER_RATE_LIMIT_PER_MINUTE: int
    USER_MAX_ACTIVE_DOWNLOADS: int
    YTDLP_FRAGMENT_CONCURRENCY: int
    YTDLP_TIMEOUT: int
    SESSION_TTL_SECONDS: int
    SESSION_CACHE_MAX_SIZE: int
    INFO_CACHE_TTL_SECONDS: int
    INFO_CACHE_MAX_SIZE: int
    DOWNLOAD_CLEANUP_AGE_SECONDS: int


def _read_int_file(path: Path) -> Optional[int]:
    try:
        if not path.exists():
            return None
        raw = path.read_text().strip()
        if not raw or raw == "max":
            return None
        return int(raw)
    except (OSError, ValueError):
        return None


def detect_memory_bytes() -> int:
    """Best-effort RAM limit: cgroup cap, then MemTotal, else 1 GiB."""
    for path in (
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ):
        limit = _read_int_file(path)
        if limit and limit < (1 << 62):
            return limit

    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemTotal:"):
                try:
                    return int(line.split()[1]) * 1024
                except (IndexError, ValueError):
                    break

    return 1024 * 1024 * 1024


def detect_cpu_count() -> float:
    """CPU cores available to this process (cgroup quota aware)."""
    cpu_count = os.cpu_count() or 1

    cgroup_v2 = Path("/sys/fs/cgroup/cpu.max")
    if cgroup_v2.exists():
        try:
            quota, period = cgroup_v2.read_text().strip().split()
            if quota != "max":
                return max(0.5, int(quota) / int(period))
        except (OSError, ValueError, ZeroDivisionError):
            pass

    cgroup_v1 = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    period_path = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    quota = _read_int_file(cgroup_v1)
    period = _read_int_file(period_path) or 100_000
    if quota and quota > 0:
        return max(0.5, quota / period)

    return float(cpu_count)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def compute_runtime_limits(
    memory_bytes: Optional[int] = None,
    cpu_count: Optional[float] = None,
) -> RuntimeLimits:
    """
    Scale every performance knob from detected RAM and CPU.

    Info/metadata work is lightweight — we bias toward higher info concurrency
    for snappy button responses. Heavy download/upload work is capped by memory.
    """
    mem = memory_bytes if memory_bytes is not None else detect_memory_bytes()
    cpu = cpu_count if cpu_count is not None else detect_cpu_count()
    mem_gb = mem / (1024 ** 3)

    # Metadata fetches are cheap — prioritize responsiveness.
    info = _clamp(int(cpu * 5 + mem_gb * 4), 3, 16)
    downloads = _clamp(int(cpu * 1.5 + mem_gb * 0.75), 1, 6)
    uploads = _clamp(int(cpu * 0.75 + 0.5), 1, 4)
    fragments = _clamp(int(cpu * 4 + mem_gb * 3), 2, 16)
    thread_pool = _clamp(downloads + info // 2 + 1, 2, 12)
    background = _clamp(info + downloads + uploads + 2, 6, 24)
    rate_limit = _clamp(int(cpu * 40 + mem_gb * 30), 30, 200)
    user_active = _clamp(int(cpu + 0.5), 1, 4)
    ytdlp_timeout = _clamp(int(300 + mem_gb * 180), 300, 1800)

    # Tighten on very small hosts so OOM is unlikely.
    if mem_gb <= 1.25:
        downloads = 1
        uploads = 1
        fragments = min(fragments, 4)
        thread_pool = min(thread_pool, 4)
        background = min(background, 8)
        user_active = 1
    elif mem_gb <= 2.5:
        downloads = min(downloads, 2)
        fragments = min(fragments, 8)
        thread_pool = min(thread_pool, 6)

    if cpu <= 1.0:
        downloads = min(downloads, 1)
        fragments = min(fragments, 4)
        thread_pool = min(thread_pool, 4)
    elif cpu <= 2.0:
        downloads = min(downloads, 2)

    session_cache = _clamp(int(mem_gb * 400 + cpu * 100), 500, 5000)
    info_cache = _clamp(int(mem_gb * 100 + cpu * 50), 200, 2000)
    cleanup_age = _clamp(int(900 + mem_gb * 300), 900, 3600)

    limits = RuntimeLimits(
        MAX_CONCURRENT_DOWNLOADS=downloads,
        MAX_CONCURRENT_INFO=info,
        MAX_CONCURRENT_UPLOADS=uploads,
        MAX_BACKGROUND_TASKS=background,
        THREAD_POOL_WORKERS=thread_pool,
        USER_RATE_LIMIT_PER_MINUTE=rate_limit,
        USER_MAX_ACTIVE_DOWNLOADS=user_active,
        YTDLP_FRAGMENT_CONCURRENCY=fragments,
        YTDLP_TIMEOUT=ytdlp_timeout,
        SESSION_TTL_SECONDS=86400,
        SESSION_CACHE_MAX_SIZE=session_cache,
        INFO_CACHE_TTL_SECONDS=3600,
        INFO_CACHE_MAX_SIZE=info_cache,
        DOWNLOAD_CLEANUP_AGE_SECONDS=cleanup_age,
    )

    logger.info(
        "Auto-tuned runtime | mem_gb=%.2f cpu=%.1f "
        "downloads=%s info=%s uploads=%s background=%s threads=%s fragments=%s timeout=%ss",
        mem_gb,
        cpu,
        limits.MAX_CONCURRENT_DOWNLOADS,
        limits.MAX_CONCURRENT_INFO,
        limits.MAX_CONCURRENT_UPLOADS,
        limits.MAX_BACKGROUND_TASKS,
        limits.THREAD_POOL_WORKERS,
        limits.YTDLP_FRAGMENT_CONCURRENCY,
        limits.YTDLP_TIMEOUT,
    )
    return limits


# Singleton computed once at import — no manual .env tuning required.
runtime = compute_runtime_limits()


# Backward-compatible alias used by tests.
def compute_concurrency_limits(
    memory_bytes: Optional[int] = None,
    cpu_count: Optional[float] = None,
) -> Dict[str, int]:
    limits = compute_runtime_limits(memory_bytes, cpu_count)
    return {
        "MAX_CONCURRENT_DOWNLOADS": limits.MAX_CONCURRENT_DOWNLOADS,
        "MAX_CONCURRENT_INFO": limits.MAX_CONCURRENT_INFO,
        "MAX_CONCURRENT_UPLOADS": limits.MAX_CONCURRENT_UPLOADS,
        "MAX_BACKGROUND_TASKS": limits.MAX_BACKGROUND_TASKS,
        "THREAD_POOL_WORKERS": limits.THREAD_POOL_WORKERS,
        "USER_RATE_LIMIT_PER_MINUTE": limits.USER_RATE_LIMIT_PER_MINUTE,
        "USER_MAX_ACTIVE_DOWNLOADS": limits.USER_MAX_ACTIVE_DOWNLOADS,
        "YTDLP_FRAGMENT_CONCURRENCY": limits.YTDLP_FRAGMENT_CONCURRENCY,
    }
