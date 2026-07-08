from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from src.bot.keyboards import (
    download_format_keyboard, 
    cancel_keyboard, 
    post_download_keyboard, 
    main_menu_keyboard
)
from src.core.downloader import download_media, fetch_info, split_large_file
from src.core.platforms import is_supported_url, unsupported_message, extract_url
import shutil
from src.core.exceptions import ValidationError, RepairFailedError
import os
import time
import logging
import asyncio
import re
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.enums import ChatAction
from html import escape

logger = logging.getLogger(__name__)
router = Router()

class DownloadState(StatesGroup):
    waiting_for_format = State()
    downloading = State() # To track active downloads for cancellation

# Soft-cancel registry (In-memory flag to stop uploads if cancelled)
cancelled_downloads = set()

def get_welcome_text() -> str:
    return (
        "👋 <b>Welcome to XinDL!</b>\n\n"
        "Fast media downloader for <b>YouTube</b>, <b>Instagram</b>, and <b>SoundCloud</b>.\n"
        "Paste a direct link and pick quality from lowest to highest available.\n\n"
        "👇 <i>Send a link to get started!</i>"
    )

def get_help_text() -> str:
    return (
        "ℹ️ <b>XinDL Help</b>\n\n"
        "<b>Supported platforms:</b>\n"
        "• YouTube (videos, shorts, music)\n"
        "• Instagram (reels, posts, stories)\n"
        "• SoundCloud (tracks, playlists)\n\n"
        "<b>How to use:</b>\n"
        "1. Paste a direct link.\n"
        "2. Pick video quality (lowest → highest) or audio only.\n"
        "3. Wait — file arrives in chat.\n\n"
        "💡 <i>Tip:</i> Lower quality = faster download & smaller file."
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
    await callback.message.edit_text("👇 <i>Please send me a direct media link.</i>")

# Handle URLs
@router.message(F.text.regexp(r'https?://'))
async def handle_url(message: Message, state: FSMContext):
    url = extract_url(message.text or "")
    if not url:
        await message.reply("لینک معتبر پیدا نشد. یک لینک https:// بفرست.")
        return

    logger.info(f"URL received | chat={message.chat.id} user={getattr(message.from_user, 'id', None)} url={url[:70]}")

    if not is_supported_url(url):
        await message.reply(unsupported_message())
        return

    msg = await message.reply("🔍 <i>Analyzing available qualities...</i>")
    
    # We await fetch_info directly here because it is fast (uses to_thread + caching)
    info = await fetch_info(url)
    if not info:
        await msg.edit_text("❌ <i>Could not extract information.</i> Please ensure it's a valid, public media link.")
        return

    title = escape(info.get('title', 'Unknown Title') or 'Unknown Title')
    formats = info.get('formats', {})
    vcount = len(formats.get('video', []))
    acount = len(formats.get('audio', []))
    logger.info(f"fetch done | title={title[:40]} video_options={vcount} audio_options={acount}")

    await state.update_data(url=url, msg_id=msg.message_id)
    await state.set_state(DownloadState.waiting_for_format)

    if vcount == 0 and acount > 0:
        text = f"🎵 <b>{title}</b>\n\n👇 <i>Audio only — choose quality (low → high):</i>"
    else:
        text = f"🎥 <b>{title}</b>\n\n👇 <i>Choose quality (low → high):</i>"
    await msg.edit_text(text, reply_markup=download_format_keyboard(formats))

@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    await callback.answer()

# Non-link text: tell user only direct links are supported (search removed)
@router.message(F.text)
async def handle_non_link(message: Message, state: FSMContext):
    if message.text.strip() in ("ℹ️ Help",) or message.text.startswith("/"):
        return
    await message.reply("فقط YouTube، Instagram و SoundCloud ساپورت می‌شن. لینک مستقیم بفرست.")

@router.callback_query(F.data == "cancel_dl")
async def cancel_download(callback: CallbackQuery, state: FSMContext):
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

def _upload_timeout_seconds(file_size_bytes: int) -> int:
    size_mb = file_size_bytes / (1024 * 1024)
    return max(120, int(size_mb * 3))

@router.callback_query(F.data.startswith("dl_"), DownloadState.waiting_for_format)
async def process_download(callback: CallbackQuery, state: FSMContext):
    data_parts = callback.data.split("_", 2)
    media_type = data_parts[1]
    format_id = data_parts[2]
    
    is_audio = media_type == 'a'
    
    data = await state.get_data()
    url = data.get("url")
    
    if not url:
        await callback.answer("❌ Session expired. Please send the link again.", show_alert=True)
        await state.clear()
        return
        
    await state.update_data(active_download_url=url)
    await state.set_state(DownloadState.downloading)
    
    if url in cancelled_downloads:
        cancelled_downloads.remove(url)
        
    logger.info(f"download start | format={format_id} audio={is_audio} chat={callback.message.chat.id}")
    await callback.message.edit_text(
        "⏳ <b>Downloading... Please wait.</b>\n<i>(This may take a moment depending on file size)</i>",
        reply_markup=cancel_keyboard()
    )
    
    loop = asyncio.get_running_loop()

    async def _update_progress_ui(text: str) -> None:
        try:
            await callback.message.edit_text(text, reply_markup=cancel_keyboard())
        except Exception:
            pass

    def _schedule_progress(text: str) -> None:
        asyncio.run_coroutine_threadsafe(_update_progress_ui(text), loop)

    asyncio.create_task(_background_download_task(callback, url, format_id, is_audio, state, loop, _schedule_progress))
    
    await callback.answer("Download started in background!", show_alert=False)


async def _background_download_task(callback: CallbackQuery, url: str, format_id: str, is_audio: bool, state: FSMContext, loop: asyncio.AbstractEventLoop, schedule_progress):
    from src.core.logger import reference_id_var
    ref_id = reference_id_var.get()
    logger.info(f"Starting download for URL: {url} | Format: {format_id}")
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
                    schedule_progress(text)
                except Exception as e:
                    logger.warning(f"Error scheduling progress UI update: {e}")

    try:
        success, result, title = await download_media(url, format_id=format_id, is_audio=is_audio, progress_callback=progress_hook)
        
        if url in cancelled_downloads:
            cancelled_downloads.remove(url)
            if result and os.path.exists(result):
                os.remove(result)
            logger.info(f"Download cancelled by user after completion: {url}")
            return
            
        await state.clear()
        
        if not success:
            logger.error(f"Failed to download {url}: {result}")
            err_text = f"❌ <b>Error downloading:</b>\n{result}"
            if ref_id:
                err_text += f"\n\n<i>Reference ID: {ref_id}</i>"
                
            await callback.message.edit_text(
                err_text,
                reply_markup=post_download_keyboard()
            )
            return
            
        file_size_bytes = os.path.getsize(result) if os.path.exists(result) else 0
        file_size_mb = file_size_bytes / (1024 * 1024)
        logger.info(f"Download successful: {url} | File: {result} | Size: {file_size_mb:.2f} MB")

        MAX_PART_BYTES = 2 * 1024 * 1024 * 1024
        upload_timeout = _upload_timeout_seconds(file_size_bytes)
        safe_title = escape(title or 'media')

        if file_size_bytes > MAX_PART_BYTES:
            await callback.message.edit_text(f"✂️ <b>Splitting into ~2GB parts...</b>\n<i>Total size: {file_size_mb:.1f} MB</i>")
            parts = split_large_file(result, MAX_PART_BYTES)
            n = len(parts)
            for i, part_path in enumerate(parts, 1):
                p_size_mb = os.path.getsize(part_path) / (1024 * 1024)
                part_cap = (
                    f"🎥 <b>{safe_title}</b>\n\n"
                    f"📊 Part {i}/{n} | Size: {p_size_mb:.1f} MB\n"
                    f"⚙️ Quality: {format_id}\n\n"
                    f"⚡️ <i>Downloaded via @XinDL</i>"
                )
                part_uri = f"file://{os.path.abspath(part_path)}"
                if not is_audio:
                    await callback.message.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VIDEO)
                    await callback.message.answer_video(video=part_uri, caption=part_cap, request_timeout=upload_timeout)
                else:
                    await callback.message.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_DOCUMENT)
                    await callback.message.answer_audio(audio=part_uri, caption=part_cap, request_timeout=upload_timeout)
                try:
                    os.remove(part_path)
                except:
                    pass
            # cleanup parts dir and original
            try:
                parts_dir = result + "_parts"
                if os.path.isdir(parts_dir):
                    shutil.rmtree(parts_dir, ignore_errors=True)
            except:
                pass
            try:
                os.remove(result)
            except:
                pass
            logger.info(f"Sent {n} parts for large file {url}")
        else:
            await callback.message.edit_text(f"📤 <b>Uploading to Telegram...</b>\n<i>Size: {file_size_mb:.2f} MB</i>")
            caption = (
                f"🎥 <b>{safe_title}</b>\n\n"
                f"📊 <b>Size:</b> {file_size_mb:.2f} MB\n"
                f"⚙️ <b>Quality:</b> {format_id}\n\n"
                f"⚡️ <i>Downloaded via @XinDL</i>"
            )
            local_uri = f"file://{os.path.abspath(result)}"
            if not is_audio:
                await callback.message.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VIDEO)
                await callback.message.answer_video(video=local_uri, caption=caption, request_timeout=upload_timeout)
            else:
                await callback.message.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_DOCUMENT)
                await callback.message.answer_audio(audio=local_uri, caption=caption, request_timeout=upload_timeout)
            logger.info(f"Successfully sent {result} to chat {callback.message.chat.id}")
        
        try:
            await callback.message.delete()
        except Exception:
            pass
            
        await callback.message.answer(
            "✅ <b>Download Complete!</b>\n\nWhat would you like to do next?", 
            reply_markup=post_download_keyboard()
        )
            
    except TelegramRetryAfter as e:
        logger.warning(f"Rate limited by Telegram. Retry after {e.retry_after}")
        await callback.message.edit_text(f"❌ Rate limited by Telegram. Please try again after {e.retry_after} seconds.")
    except Exception as e:
        if str(e) == "DownloadCancelled":
            if url in cancelled_downloads:
                cancelled_downloads.remove(url)
            logger.info(f"Download cancelled by user: {url}")
            return
            
        if isinstance(e, ValidationError):
            logger.warning(f"Validation Error caught for {url}: {e.message}")
            err_msg = f"❌ <b>Validation Failed:</b>\n{e.message}"
            if ref_id:
                err_msg += f"\n\n<i>Reference ID: {ref_id}</i>"
                
            if getattr(e, 'fallback_suggested', False) and not is_audio:
                err_msg += "\n\n💡 <i>The video is corrupted. Please tap 'Download Another' and try the Audio Only option.</i>"
                
            try:
                await callback.message.edit_text(err_msg, reply_markup=post_download_keyboard())
            except Exception:
                pass
            return
            
        logger.exception(f"Unexpected error in background download task for {url}: {e}")
        err_msg = "❌ An unexpected error occurred."
        if ref_id:
            err_msg += f"\n\n<i>Reference ID: {ref_id}</i>"
        try:
            await callback.message.edit_text(err_msg, reply_markup=post_download_keyboard())
        except Exception:
            pass
    finally:
        # Cleanup
        try:
            if 'result' in locals() and result and os.path.exists(result):
                os.remove(result)
                logger.info(f"Cleaned up file: {result}")
        except Exception as e:
            logger.error(f"Failed to remove file: {e}")
