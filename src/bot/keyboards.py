from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from typing import Dict, List

def download_format_keyboard(formats_dict: Dict[str, List[Dict[str, str]]]) -> InlineKeyboardMarkup:
    """Highly polished dynamic keyboard for selecting download quality."""
    
    keyboard = []
    
    # 1. Prominent "Best Quality" recommendation at the top
    best_video = next((v for v in formats_dict.get("video", []) if v["id"] == "best"), None)
    if best_video:
        keyboard.append([InlineKeyboardButton(text="⭐️ Best Quality (Recommended)", callback_data=f"dl_v_{best_video['id']}")])
    
    # 2. Video Section
    video_options = [v for v in formats_dict.get("video", []) if v["id"] != "best"]
    if video_options:
        keyboard.append([InlineKeyboardButton(text="— 🎬 Video Qualities —", callback_data="ignore")])
        row = []
        for v in video_options:
            row.append(InlineKeyboardButton(text=v["label"], callback_data=f"dl_v_{v['id']}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
            
    # 3. Audio Section
    if "audio" in formats_dict:
        keyboard.append([InlineKeyboardButton(text="— 🎵 Audio Only —", callback_data="ignore")])
        row = []
        for a in formats_dict["audio"]:
            row.append(InlineKeyboardButton(text=a["label"], callback_data=f"dl_a_{a['id']}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
            
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def cancel_keyboard() -> InlineKeyboardMarkup:
    """Keyboard shown during active download."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel Download", callback_data="cancel_dl")]
        ]
    )

def post_download_keyboard() -> InlineKeyboardMarkup:
    """Keyboard shown after a successful download."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Download Another", callback_data="new_dl")],
            [InlineKeyboardButton(text="ℹ️ Help & Info", callback_data="help_menu")]
        ]
    )

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Persistent reply keyboard for easy access."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="ℹ️ Help")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

def search_results_keyboard(results_len: int, current_index: int, url: str) -> InlineKeyboardMarkup:
    """Keyboard for paginated search results."""
    buttons = []
    
    # Download button for current result
    buttons.append([InlineKeyboardButton(text="⬇️ Download This", callback_data=f"search_dl_{current_index}")])
    
    # Navigation row
    nav_row = []
    if current_index > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"search_nav_{current_index - 1}"))
    else:
        nav_row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
        
    nav_row.append(InlineKeyboardButton(text=f"{current_index + 1} / {results_len}", callback_data="ignore"))
    
    if current_index < results_len - 1:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"search_nav_{current_index + 1}"))
    else:
        nav_row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
        
    buttons.append(nav_row)
    
    # Cancel button
    buttons.append([InlineKeyboardButton(text="❌ Cancel Search", callback_data="cancel_search")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)
