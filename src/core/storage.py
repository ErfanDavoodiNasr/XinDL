"""Disk hygiene helpers for download workspace."""
from __future__ import annotations

import logging
import os
import shutil
import time
from typing import Tuple

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "downloads"
MIN_FREE_BYTES = 256 * 1024 * 1024


def disk_free_bytes(path: str = DOWNLOAD_DIR) -> int:
    target = path if os.path.exists(path) else "."
    usage = shutil.disk_usage(target)
    return usage.free


def cleanup_download_dir(max_age_seconds: int = 3600) -> Tuple[int, int]:
    """Remove stale files from downloads/. Returns (files_removed, bytes_freed)."""
    if not os.path.isdir(DOWNLOAD_DIR):
        return 0, 0

    now = time.time()
    removed = 0
    freed = 0
    for name in os.listdir(DOWNLOAD_DIR):
        path = os.path.join(DOWNLOAD_DIR, name)
        try:
            if not os.path.isfile(path):
                continue
            age = now - os.path.getmtime(path)
            if age < max_age_seconds:
                continue
            size = os.path.getsize(path)
            os.remove(path)
            removed += 1
            freed += size
        except OSError as exc:
            logger.warning("Could not remove stale download %s: %s", path, exc)

    if removed:
        logger.info("Cleaned %s stale download file(s), freed %.1f MB", removed, freed / (1024 * 1024))
    return removed, freed


def ensure_download_space(required_bytes: int = 0) -> None:
    """Purge old downloads then fail fast if disk is still too tight."""
    cleanup_download_dir()
    needed = max(required_bytes, MIN_FREE_BYTES)
    free = disk_free_bytes()
    if free < needed:
        raise OSError(
            f"Not enough free disk space ({free // (1024 * 1024)} MB free, "
            f"need at least {needed // (1024 * 1024)} MB)."
        )


def remove_download_artifacts(prefix: str) -> int:
    """Delete all files and folders created for one download prefix."""
    if not os.path.isdir(DOWNLOAD_DIR):
        return 0

    removed = 0
    for name in os.listdir(DOWNLOAD_DIR):
        if not name.startswith(prefix):
            continue

        path = os.path.join(DOWNLOAD_DIR, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
            removed += 1
        except OSError as exc:
            logger.warning("Could not remove download artifact %s: %s", path, exc)

    return removed
