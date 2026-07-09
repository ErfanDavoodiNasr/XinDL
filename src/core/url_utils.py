"""URL normalization and short-link resolution."""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse, urlunparse

import requests

logger = logging.getLogger(__name__)

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "si", "feature", "fbclid", "igsh", "is",
})


def _strip_tracking_params(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.query:
        return url
    kept = [
        part for part in parsed.query.split("&")
        if part and part.split("=", 1)[0] not in _TRACKING_PARAMS
    ]
    return urlunparse(parsed._replace(query="&".join(kept)))


def normalize_url(url: str, *, resolve_short: bool = True) -> str:
    """Resolve short links and strip tracking parameters."""
    url = url.strip()
    if not resolve_short:
        return _strip_tracking_params(url)

    host = urlparse(url).netloc.lower().removeprefix("www.")
    if host == "on.soundcloud.com" or host.endswith(".on.soundcloud.com"):
        try:
            response = requests.head(
                url,
                allow_redirects=True,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (compatible; XinDL/1.0)"},
            )
            if response.url and response.url != url:
                logger.info("Resolved short URL %s -> %s", url[:60], response.url[:80])
                url = response.url
        except requests.RequestException as exc:
            logger.warning("Could not resolve short URL %s: %s", url[:60], exc)

    return _strip_tracking_params(url)
