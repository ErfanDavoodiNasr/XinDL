"""Supported platform detection — YouTube, Instagram, SoundCloud only."""
import re
from urllib.parse import urlparse
from typing import Optional

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")

PLATFORM_DOMAINS = {
    "youtube": ("youtube.com", "youtu.be", "music.youtube.com"),
    "instagram": ("instagram.com",),
    "soundcloud": ("soundcloud.com",),
}

PLATFORM_LABELS = {
    "youtube": "YouTube",
    "instagram": "Instagram",
    "soundcloud": "SoundCloud",
}


def extract_url(text: str) -> Optional[str]:
    match = URL_PATTERN.search(text.strip())
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)")


def detect_platform(url: str) -> Optional[str]:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return None
    for name, domains in PLATFORM_DOMAINS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return name
    return None


def is_supported_url(url: str) -> bool:
    return detect_platform(url) is not None


def unsupported_message() -> str:
    return (
        "❌ <b>پلتفرم پشتیبانی نمی‌شود.</b>\n\n"
        "فقط این ۳ پلتفرم ساپورت می‌شن:\n"
        "<b>YouTube</b> | <b>Instagram</b> | <b>SoundCloud</b>\n\n"
        "لینک مستقیم یکی از این‌ها بفرست."
    )
