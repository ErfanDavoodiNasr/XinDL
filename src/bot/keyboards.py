from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from typing import Dict, List


def _quality_callback(media_type: str, format_id: str, session_id: str) -> str:
    """Build callback_data with session id (max 64 bytes for Telegram)."""
    return f"dl:{media_type}:{format_id}:{session_id}"


def download_format_keyboard(
    formats_dict: Dict[str, List[Dict[str, str]]],
    session_id: str,
) -> InlineKeyboardMarkup:
    """Quality keyboard: lowest → highest, best at end."""
    keyboard = []

    video_options = formats_dict.get("video", [])
    if video_options:
        keyboard.append([InlineKeyboardButton(text="— 🎬 Video (low → high) —", callback_data="ignore")])
        row = []
        for v in video_options:
            row.append(InlineKeyboardButton(
                text=v["label"],
                callback_data=_quality_callback("v", v["id"], session_id),
            ))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

    audio_options = formats_dict.get("audio", [])
    if audio_options:
        keyboard.append([InlineKeyboardButton(text="— 🎵 Audio Only (low → high) —", callback_data="ignore")])
        row = []
        for a in audio_options:
            row.append(InlineKeyboardButton(
                text=a["label"],
                callback_data=_quality_callback("a", a["id"], session_id),
            ))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel Download", callback_data="cancel_dl")]
        ]
    )


def post_download_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Download Another", callback_data="new_dl")],
            [InlineKeyboardButton(text="ℹ️ Help & Info", callback_data="help_menu")]
        ]
    )


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="ℹ️ Help")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )
