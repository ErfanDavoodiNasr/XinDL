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
from src.core.storage import cleanup_download_dir, remove_download_artifacts
from src.core.platforms import is_supported_url, unsupported_message, extract_url
from src.core.url_utils import normalize_url
from src.core.session_cache import create_session, get_session
from src.core.validator import get_media_metadata
from src.core.resources import runtime
from src.core.concurrency import (
    user_gate,
    download_registry,
    get_upload_sem,
    get_background_sem,
)
import shutil
from src.core.exceptions import ValidationError, RepairFailedError
import os
import time
import logging
import asyncio
import re
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.enums import ChatAction
from aiogram.methods import SendAudio, SendVideo
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
    user_id = getattr(message.from_user, "id", None)
    if await user_gate.check_request(user_id, action="help"):
        return
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
async def handle_url(message: Message, state: FSMContext, reference_id: str | None = None):
    user_id = getattr(message.from_user, "id", None)
    blocked = await user_gate.check_request(user_id)
    if blocked:
        await message.reply(blocked)
        return

    url = extract_url(message.text or "")
    if not url:
        await message.reply("No valid link found. Please send an https:// URL.")
        return

    url = normalize_url(url)

    logger.info(f"URL received | chat={message.chat.id} user={getattr(message.from_user, 'id', None)} url={url[:70]}")

    if not is_supported_url(url):
        await message.reply(unsupported_message())
        return

    cleanup_download_dir(max_age_seconds=runtime.DOWNLOAD_CLEANUP_AGE_SECONDS)
    msg = await message.reply("🔍 <i>Analyzing available qualities...</i>")
    
    # We await fetch_info directly here because it is fast (uses to_thread + caching)
    info, fetch_error = await fetch_info(url)
    if not info:
        detail = fetch_error or (
            "Please ensure it's a valid, public media link. Some SoundCloud tracks are "
            "preview-only (30s) or DRM-protected and cannot be fully downloaded."
        )
        await msg.edit_text(f"❌ <i>Could not extract information.</i>\n\n{detail}")
        return

    title = escape(info.get('title', 'Unknown Title') or 'Unknown Title')
    formats = info.get('formats', {})
    vcount = len(formats.get('video', []))
    acount = len(formats.get('audio', []))
    duration = info.get('duration') or 0
    preview_only = info.get('preview_only', False)
    logger.info(f"fetch done | title={title[:40]} video_options={vcount} audio_options={acount}")

    session_id = create_session(
        url=url,
        title=info.get('title', 'Unknown Title') or 'Unknown Title',
        formats=formats,
        reference_id=reference_id,
        duration=duration,
        preview_only=preview_only,
    )

    await state.update_data(url=url, msg_id=msg.message_id, reference_id=reference_id, session_id=session_id)
    await state.set_state(DownloadState.waiting_for_format)

    if preview_only:
        text = (
            f"⚠️ <b>{title}</b>\n\n"
            f"This SoundCloud track is only available as a <b>~30 second preview</b>. "
            f"The full version requires a SoundCloud Go account.\n\n"
            f"👇 <i>You can still download the preview below:</i>"
        )
    elif vcount == 0 and acount > 0:
        text = f"🎵 <b>{title}</b>\n\n👇 <i>Audio only — choose quality (low → high):</i>"
    else:
        text = f"🎥 <b>{title}</b>\n\n👇 <i>Choose quality (low → high):</i>"
    await msg.edit_text(text, reply_markup=download_format_keyboard(formats, session_id))

@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    await callback.answer()

# Non-link text: tell user only direct links are supported (search removed)
@router.message(F.text)
async def handle_non_link(message: Message, state: FSMContext):
    if message.text.strip() in ("ℹ️ Help",) or message.text.startswith("/"):
        return
    await message.reply(
        "Only YouTube, Instagram, and SoundCloud are supported. Please send a direct link."
    )

@router.callback_query(F.data == "cancel_dl")
async def cancel_download(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    url = data.get("active_download_url")
    user_id = getattr(callback.from_user, "id", None)
    if url:
        cancelled_downloads.add(url)
    await user_gate.finish_download(user_id)
    
    await state.clear()
    await callback.message.edit_text("🛑 <b>Download Cancelled.</b>\n\nYou can send a new link whenever you're ready.")
    await callback.answer("Cancelled successfully.", show_alert=False)

def build_progress_bar(percent: float) -> str:
    filled = int(percent / 10)
    empty = 10 - filled
    return f"[{'█' * filled}{'░' * empty}] {percent:.1f}%"

def _upload_timeout_seconds(file_size_bytes: int) -> int:
    size_mb = file_size_bytes / (1024 * 1024)
    # ~5s per MB + 3 min floor; large local-API uploads need headroom.
    return max(180, int(size_mb * 5) + 120)


def _parse_download_callback(data: str) -> tuple[str, str, str] | None:
    """Parse dl:v:720p:sessionid or legacy dl_v_720p."""
    if data.startswith("dl:"):
        parts = data.split(":", 3)
        if len(parts) == 4:
            return parts[1], parts[2], parts[3]
        return None
    if data.startswith("dl_"):
        legacy = data.split("_", 2)
        if len(legacy) == 3:
            return legacy[1], legacy[2], ""
    return None


async def _send_video_file(message, file_uri: str, caption: str, upload_timeout: int) -> None:
    file_path = file_uri[7:] if file_uri.startswith("file://") else file_uri
    meta = await get_media_metadata(file_path)
    method_kwargs: dict = {
        "chat_id": message.chat.id,
        "video": file_uri,
        "caption": caption,
        "supports_streaming": True,
    }
    if meta.get("width"):
        method_kwargs["width"] = meta["width"]
    if meta.get("height"):
        method_kwargs["height"] = meta["height"]
    if meta.get("duration"):
        method_kwargs["duration"] = meta["duration"]
    await message.bot(SendVideo(**method_kwargs), request_timeout=upload_timeout)


async def _send_audio_file(message, file_uri: str, caption: str, upload_timeout: int) -> None:
    await message.bot(
        SendAudio(chat_id=message.chat.id, audio=file_uri, caption=caption),
        request_timeout=upload_timeout,
    )


@router.callback_query(F.data.startswith("dl:") | F.data.startswith("dl_"))
async def process_download(callback: CallbackQuery, state: FSMContext):
    parsed = _parse_download_callback(callback.data)
    if not parsed:
        await callback.answer("Invalid selection.", show_alert=True)
        return

    media_type, format_id, session_id = parsed
    is_audio = media_type == 'a'
    user_id = getattr(callback.from_user, "id", None)

    url = None
    ref_id = None
    expected_duration = 0.0

    if session_id:
        session = get_session(session_id)
        if session:
            url = session.url
            ref_id = session.reference_id
            expected_duration = session.duration or 0.0
        else:
            await callback.answer(
                "❌ Session expired (24h limit). Please send the link again.",
                show_alert=True,
            )
            return
    else:
        data = await state.get_data()
        url = data.get("url")
        ref_id = data.get("reference_id")

    if not url:
        await callback.answer("❌ Session expired. Please send the link again.", show_alert=True)
        await state.clear()
        return

    blocked = await user_gate.try_start_download(user_id)
    if blocked:
        await callback.answer(blocked, show_alert=True)
        return

    download_key = f"{url}|{format_id}|{'audio' if is_audio else 'video'}"
    if not await download_registry.try_acquire(download_key):
        await user_gate.finish_download(user_id)
        await callback.answer("⏳ This quality is already downloading. Please wait.", show_alert=True)
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

    async def _run_download() -> None:
        async with get_background_sem():
            await _background_download_task(
                callback, url, format_id, is_audio, state, loop, _schedule_progress,
                ref_id=ref_id, user_id=user_id, download_key=download_key,
                expected_duration=expected_duration,
            )

    asyncio.create_task(_run_download())
    
    await callback.answer("Download started in background!", show_alert=False)


async def _background_download_task(
    callback: CallbackQuery,
    url: str,
    format_id: str,
    is_audio: bool,
    state: FSMContext,
    loop: asyncio.AbstractEventLoop,
    schedule_progress,
    ref_id: str | None = None,
    user_id: int | None = None,
    download_key: str | None = None,
    expected_duration: float = 0.0,
):
    from src.core.logger import reference_id_var
    token = None
    if ref_id:
        token = reference_id_var.set(ref_id)
    logger.info(f"Starting download for URL: {url} | Format: {format_id}")
    last_update_time = time.time()
    file_prefix = ""
    
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

    result = None
    try:
        success, result, title = await download_media(
            url, format_id=format_id, is_audio=is_audio,
            progress_callback=progress_hook,
            expected_duration=expected_duration,
        )
        if success and result:
            file_prefix = os.path.splitext(os.path.basename(result))[0]

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

        async with get_upload_sem():
            if file_size_bytes > MAX_PART_BYTES:
                await callback.message.edit_text(
                    f"✂️ <b>Splitting into ~2GB parts...</b>\n<i>Total size: {file_size_mb:.1f} MB</i>"
                )
                parts = split_large_file(result, MAX_PART_BYTES)
                n = len(parts)
                for i, part_path in enumerate(parts, 1):
                    p_size_bytes = os.path.getsize(part_path)
                    p_size_mb = p_size_bytes / (1024 * 1024)
                    part_timeout = _upload_timeout_seconds(p_size_bytes)
                    part_cap = (
                        f"🎥 <b>{safe_title}</b>\n\n"
                        f"📊 Part {i}/{n} | Size: {p_size_mb:.1f} MB\n"
                        f"⚙️ Quality: {format_id}\n\n"
                        f"⚡️ <i>Downloaded via @XinDL</i>"
                    )
                    part_uri = f"file://{os.path.abspath(part_path)}"
                    if not is_audio:
                        await callback.message.bot.send_chat_action(
                            chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VIDEO
                        )
                        await _send_video_file(
                            callback.message, part_uri, part_cap, part_timeout
                        )
                    else:
                        await callback.message.bot.send_chat_action(
                            chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VOICE
                        )
                        await _send_audio_file(
                            callback.message, part_uri, part_cap, part_timeout
                        )
                    try:
                        os.remove(part_path)
                    except OSError:
                        pass
                try:
                    parts_dir = result + "_parts"
                    if os.path.isdir(parts_dir):
                        shutil.rmtree(parts_dir, ignore_errors=True)
                except OSError:
                    pass
                try:
                    os.remove(result)
                    result = None
                except OSError:
                    pass
                logger.info(f"Sent {n} parts for large file {url}")
            else:
                await callback.message.edit_text(
                    f"📤 <b>Uploading to Telegram...</b>\n<i>Size: {file_size_mb:.2f} MB</i>"
                )
                caption = (
                    f"🎥 <b>{safe_title}</b>\n\n"
                    f"📊 <b>Size:</b> {file_size_mb:.2f} MB\n"
                    f"⚙️ <b>Quality:</b> {format_id}\n\n"
                    f"⚡️ <i>Downloaded via @XinDL</i>"
                )
                local_uri = f"file://{os.path.abspath(result)}"
                if not is_audio:
                    await callback.message.bot.send_chat_action(
                        chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VIDEO
                    )
                    await _send_video_file(
                        callback.message, local_uri, caption, upload_timeout
                    )
                else:
                    await callback.message.bot.send_chat_action(
                        chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VOICE
                    )
                    await _send_audio_file(
                        callback.message, local_uri, caption, upload_timeout
                    )
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
        await callback.message.edit_text(
            f"❌ Rate limited by Telegram. Please try again after {e.retry_after} seconds."
        )
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
                err_msg += (
                    "\n\n💡 <i>The video is corrupted. Please tap 'Download Another' "
                    "and try the Audio Only option.</i>"
                )

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
        if download_key:
            await download_registry.release(download_key)
        await user_gate.finish_download(user_id)
        if token is not None:
            reference_id_var.reset(token)
        try:
            if result and os.path.exists(result):
                os.remove(result)
                logger.info(f"Cleaned up file: {result}")
        except Exception as e:
            logger.error(f"Failed to remove file: {e}")
        if file_prefix:
            remove_download_artifacts(file_prefix)
        cleanup_download_dir(max_age_seconds=runtime.DOWNLOAD_CLEANUP_AGE_SECONDS)
