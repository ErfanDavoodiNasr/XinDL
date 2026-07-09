"""Detect host resources and derive safe concurrency defaults."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


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


def compute_concurrency_limits(
    memory_bytes: Optional[int] = None,
    cpu_count: Optional[float] = None,
) -> Dict[str, int]:
    """Scale worker limits to available RAM and CPU."""
    mem = memory_bytes if memory_bytes is not None else detect_memory_bytes()
    cpu = cpu_count if cpu_count is not None else detect_cpu_count()
    mem_gb = mem / (1024 ** 3)

    if mem_gb <= 1.25:
        base = {
            "MAX_CONCURRENT_DOWNLOADS": 1,
            "MAX_CONCURRENT_INFO": 2,
            "YTDLP_FRAGMENT_CONCURRENCY": 2,
            "MAX_CONCURRENT_UPLOADS": 1,
            "MAX_BACKGROUND_TASKS": 3,
            "THREAD_POOL_WORKERS": 2,
            "USER_RATE_LIMIT_PER_MINUTE": 10,
            "USER_MAX_ACTIVE_DOWNLOADS": 1,
        }
    elif mem_gb <= 2.5:
        base = {
            "MAX_CONCURRENT_DOWNLOADS": 2,
            "MAX_CONCURRENT_INFO": 3,
            "YTDLP_FRAGMENT_CONCURRENCY": 4,
            "MAX_CONCURRENT_UPLOADS": 2,
            "MAX_BACKGROUND_TASKS": 6,
            "THREAD_POOL_WORKERS": 3,
            "USER_RATE_LIMIT_PER_MINUTE": 20,
            "USER_MAX_ACTIVE_DOWNLOADS": 2,
        }
    elif mem_gb <= 4.0:
        base = {
            "MAX_CONCURRENT_DOWNLOADS": 3,
            "MAX_CONCURRENT_INFO": 4,
            "YTDLP_FRAGMENT_CONCURRENCY": 6,
            "MAX_CONCURRENT_UPLOADS": 2,
            "MAX_BACKGROUND_TASKS": 8,
            "THREAD_POOL_WORKERS": 4,
            "USER_RATE_LIMIT_PER_MINUTE": 30,
            "USER_MAX_ACTIVE_DOWNLOADS": 2,
        }
    else:
        base = {
            "MAX_CONCURRENT_DOWNLOADS": 4,
            "MAX_CONCURRENT_INFO": 6,
            "YTDLP_FRAGMENT_CONCURRENCY": 8,
            "MAX_CONCURRENT_UPLOADS": 3,
            "MAX_BACKGROUND_TASKS": 12,
            "THREAD_POOL_WORKERS": 6,
            "USER_RATE_LIMIT_PER_MINUTE": 40,
            "USER_MAX_ACTIVE_DOWNLOADS": 3,
        }

    if cpu <= 1.0:
        base["MAX_CONCURRENT_DOWNLOADS"] = min(base["MAX_CONCURRENT_DOWNLOADS"], 1)
        base["YTDLP_FRAGMENT_CONCURRENCY"] = min(base["YTDLP_FRAGMENT_CONCURRENCY"], 2)
        base["THREAD_POOL_WORKERS"] = min(base["THREAD_POOL_WORKERS"], 2)
    elif cpu <= 2.0:
        base["MAX_CONCURRENT_DOWNLOADS"] = min(base["MAX_CONCURRENT_DOWNLOADS"], 2)
        base["YTDLP_FRAGMENT_CONCURRENCY"] = min(base["YTDLP_FRAGMENT_CONCURRENCY"], 4)

    logger.info(
        "Auto-tuned concurrency | mem_gb=%.2f cpu=%.1f downloads=%s info=%s fragments=%s",
        mem_gb,
        cpu,
        base["MAX_CONCURRENT_DOWNLOADS"],
        base["MAX_CONCURRENT_INFO"],
        base["YTDLP_FRAGMENT_CONCURRENCY"],
    )
    return base
