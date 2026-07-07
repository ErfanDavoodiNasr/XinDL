from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from src.bot.keyboards import (
    download_format_keyboard, 
    cancel_keyboard, 
    post_download_keyboard, 
    main_menu_keyboard,
    search_results_keyboard
)
from src.core.downloader import download_media, fetch_info, search_media
import os
import time
import logging
import asyncio
import re
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.enums import ChatAction

logger = logging.getLogger(__name__)
router = Router()

class DownloadState(StatesGroup):
    waiting_for_format = State()
    downloading = State() # To track active downloads for cancellation
    searching = State() # Viewing search results

# Soft-cancel registry (In-memory flag to stop uploads if cancelled)
cancelled_downloads = set()

def get_welcome_text() -> str:
    return (
        "👋 <b>Welcome to XinDL!</b>\n\n"
        "I am your lightning-fast, premium media downloader.\n"
        "Simply send me a link from <b>YouTube</b>, <b>Instagram</b>, <b>TikTok</b>, or <b>Twitter/X</b>, "
        "and I will fetch it for you in the highest quality available.\n\n"
        "You can also <b>type any text</b> to search for media!\n\n"
        "👇 <i>Just paste a link or type a search below to get started!</i>"
    )

def get_help_text() -> str:
    return (
        "ℹ️ <b>XinDL Help Center</b>\n\n"
        "<b>How to use:</b>\n"
        "1. Copy a link from a supported platform (YouTube, Insta, TikTok, X) and paste it.\n"
        "2. OR simply type what you want to search for.\n"
        "3. Choose your preferred video resolution or audio format.\n"
        "4. Wait a moment, and the file will be sent directly to you!\n\n"
        "💡 <i>Tip:</i> The 'Best Quality' button automatically picks the absolute highest resolution available."
    )

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(get_welcome_text(), reply_markup=main_menu_keyboard())

@router.message(Command("help"))
@router.message(F.text == "ℹ️ Help")
async def cmd_help(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(get_help_text())

@router.callback_query(F.data == "help_menu")
async def callback_help(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(get_help_text())
    
@router.callback_query(F.data == "new_dl")
async def callback_new_dl(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("👇 <i>Please send me the new link or search query.</i>")

# Handle URLs
@router.message(F.text.regexp(r'https?://[^\s]+'))
async def handle_url(message: Message, state: FSMContext):
    url = message.text.strip()
    
    msg = await message.reply("🔍 <i>Analyzing available qualities...</i>")
    
    # We await fetch_info directly here because it is fast (uses to_thread + caching)
    info = await fetch_info(url)
    if not info:
        await msg.edit_text("❌ <i>Could not extract information.</i> Please ensure it's a valid, public media link.")
        return

    title = info.get('title', 'Unknown Title')
    formats = info.get('formats', {})
    
    await state.update_data(url=url, msg_id=msg.message_id)
    await state.set_state(DownloadState.waiting_for_format)
    
    text = f"🎥 <b>{title}</b>\n\n👇 <i>Choose your preferred download quality:</i>"
    await msg.edit_text(text, reply_markup=download_format_keyboard(formats))

# Handle Search Text
@router.message(F.text)
async def handle_search(message: Message, state: FSMContext):
    query = message.text.strip()
    if query == "ℹ️ Help" or query.startswith("/"):
        return
        
    msg = await message.reply(f"🔍 <i>Searching for '{query}'...</i>")
    
    results = await search_media(query, limit=10)
    
    if not results:
        await msg.edit_text("❌ <i>No results found.</i> Please try a different search term.")
        return
        
    await state.update_data(search_results=results, current_index=0, msg_id=msg.message_id)
    await state.set_state(DownloadState.searching)
    
    await display_search_result(msg, results, 0)

async def display_search_result(msg: Message, results: list, index: int):
    result = results[index]
    title = result.get('title', 'Unknown Title')
    uploader = result.get('uploader', 'Unknown')
    duration = result.get('duration', 0)
    
    minutes, seconds = divmod(duration, 60)
    duration_str = f"{minutes}:{seconds:02d}"
    
    text = (
        f"🔎 <b>Search Result {index + 1}/{len(results)}</b>\n\n"
        f"🎥 <b>{title}</b>\n"
        f"👤 <i>{uploader}</i> | ⏱ <i>{duration_str}</i>"
    )
    
    try:
        await msg.edit_text(
            text, 
            reply_markup=search_results_keyboard(len(results), index, result.get('url'))
        )
    except Exception as e:
        logger.error(f"Error editing message: {e}")

@router.callback_query(F.data.startswith("search_nav_"), DownloadState.searching)
async def search_nav(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[2])
    data = await state.get_data()
    results = data.get("search_results", [])
    
    if not results or index < 0 or index >= len(results):
        await callback.answer("❌ Invalid navigation.", show_alert=True)
        return
        
    await state.update_data(current_index=index)
    await display_search_result(callback.message, results, index)
    await callback.answer()

@router.callback_query(F.data == "cancel_search", DownloadState.searching)
async def cancel_search(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🛑 <b>Search Cancelled.</b>\n\nYou can send a new link or search query.")
    await callback.answer()

@router.callback_query(F.data.startswith("search_dl_"), DownloadState.searching)
async def search_dl(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[2])
    data = await state.get_data()
    results = data.get("search_results", [])
    
    if not results or index < 0 or index >= len(results):
        await callback.answer("❌ Invalid selection.", show_alert=True)
        return
        
    url = results[index].get('url')
    
    await callback.message.edit_text("🔍 <i>Analyzing available qualities...</i>")
    
    info = await fetch_info(url)
    if not info:
        await callback.message.edit_text("❌ <i>Could not extract information.</i>")
        return

    title = info.get('title', 'Unknown Title')
    formats = info.get('formats', {})
    
    await state.update_data(url=url)
    await state.set_state(DownloadState.waiting_for_format)
    
    text = f"🎥 <b>{title}</b>\n\n👇 <i>Choose your preferred download quality:</i>"
    await callback.message.edit_text(text, reply_markup=download_format_keyboard(formats))


@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    await callback.answer()

@router.callback_query(F.data == "cancel_dl")
async def cancel_download(callback: CallbackQuery, state: FSMContext):
    # Read custom cancel data if available in FSM or pass from cb
    # Here we just use a generic cancel approach where we check if a download is active in the state
    data = await state.get_data()
    url = data.get("active_download_url")
    if url:
        cancelled_downloads.add(url)
    
    await state.clear()
    await callback.message.edit_text("🛑 <b>Download Cancelled.</b>\n\nYou can send a new link whenever you're ready.")
    await callback.answer("Cancelled successfully.", show_alert=False)

def build_progress_bar(percent: float) -> str:
    filled = int(percent / 10)
    empty = 10 - filled
    return f"[{'█' * filled}{'░' * empty}] {percent:.1f}%"

@router.callback_query(F.data.startswith("dl_"), DownloadState.waiting_for_format)
async def process_download(callback: CallbackQuery, state: FSMContext):
    data_parts = callback.data.split("_")
    media_type = data_parts[1]
    format_id = data_parts[2]
    
    is_audio = media_type == 'a'
    
    data = await state.get_data()
    url = data.get("url")
    
    if not url:
        await callback.answer("❌ Session expired. Please send the link again.", show_alert=True)
        await state.clear()
        return
        
    # Mark the URL as the active download so the cancel button works
    await state.update_data(active_download_url=url)
    await state.set_state(DownloadState.downloading)
    
    if url in cancelled_downloads:
        cancelled_downloads.remove(url)
        
    await callback.message.edit_text(
        "⏳ <b>Downloading... Please wait.</b>\n<i>(This may take a moment depending on file size)</i>",
        reply_markup=cancel_keyboard()
    )
    
    # Spawn background task to free up the event loop
    asyncio.create_task(_background_download_task(callback, url, format_id, is_audio, state))
    
    await callback.answer("Download started in background!", show_alert=False)


async def _background_download_task(callback: CallbackQuery, url: str, format_id: str, is_audio: bool, state: FSMContext):
    last_update_time = time.time()
    
    def progress_hook(d):
        nonlocal last_update_time
        if d['status'] == 'downloading':
            if url in cancelled_downloads:
                raise Exception("DownloadCancelled")
                
            current_time = time.time()
            if current_time - last_update_time > 2.0:
                last_update_time = current_time
                try:
                    percent_str = d.get('_percent_str', '0.0%').replace('%', '').strip()
                    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                    percent_str = ansi_escape.sub('', percent_str)
                    
                    try:
                        percent = float(percent_str)
                    except ValueError:
                        percent = 0.0
                    
                    speed = d.get('_speed_str', 'Unknown speed')
                    speed = ansi_escape.sub('', speed)
                    
                    eta = d.get('_eta_str', 'Unknown ETA')
                    eta = ansi_escape.sub('', eta)
                    
                    pbar = build_progress_bar(percent)
                    
                    text = (
                        f"⏳ <b>Downloading...</b>\n\n"
                        f"{pbar}\n\n"
                        f"⚡️ <b>Speed:</b> {speed}\n"
                        f"⏱ <b>ETA:</b> {eta}"
                    )
                    
                    # Fire and forget edit message to avoid blocking hook
                    asyncio.create_task(
                        callback.message.edit_text(
                            text,
                            reply_markup=cancel_keyboard()
                        )
                    )
                except Exception as e:
                    logger.warning(f"Error updating progress UI: {e}")

    try:
        success, result, title = await download_media(url, format_id=format_id, is_audio=is_audio, progress_callback=progress_hook)
    except Exception as e:
        if str(e) == "DownloadCancelled":
            if url in cancelled_downloads:
                cancelled_downloads.remove(url)
            return
        success, result, title = False, str(e), ""
    
    if url in cancelled_downloads:
        cancelled_downloads.remove(url)
        if result and os.path.exists(result):
            os.remove(result)
        return
        
    await state.clear()
    
    if not success:
        await callback.message.edit_text(
            f"❌ <b>Error downloading:</b> {result}",
            reply_markup=post_download_keyboard()
        )
        return
        
    await callback.message.edit_text("📤 <b>Uploading to Telegram...</b>")
    
    try:
        from aiogram.types import FSInputFile
        file = FSInputFile(result)
        
        caption = f"🎥 <b>{title}</b>\n\n⚡️ <i>Downloaded via @XinDL</i>"
        
        if not is_audio:
            await callback.message.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VIDEO)
            await callback.message.answer_video(video=file, caption=caption, request_timeout=300)
        else:
            await callback.message.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_DOCUMENT)
            await callback.message.answer_audio(audio=file, caption=caption, request_timeout=300)
            
        await callback.message.delete()
        await callback.message.answer(
            "✅ <b>Download Complete!</b>\n\nWhat would you like to do next?", 
            reply_markup=post_download_keyboard()
        )
            
    except TelegramRetryAfter as e:
        logger.warning(f"Rate limited by Telegram. Retry after {e.retry_after}")
        await callback.message.edit_text(f"❌ Rate limited by Telegram. Please try again after {e.retry_after} seconds.")
    except TelegramNetworkError as e:
        logger.error(f"Network error while uploading: {e}")
        await callback.message.edit_text("❌ Network error while uploading to Telegram. The file might be too large.")
    except Exception as e:
        logger.error(f"Error uploading to Telegram: {e}")
        await callback.message.edit_text("❌ An unexpected error occurred during upload.")
    finally:
        if os.path.exists(result):
            try:
                os.remove(result)
            except Exception as e:
                logger.error(f"Failed to remove file {result}: {e}")
