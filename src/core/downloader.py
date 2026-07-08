import asyncio
import os
import uuid
import shutil
import subprocess
import yt_dlp
from typing import Dict, Any, Optional, Tuple, List
import logging
from src.core.config import settings
from src.core.platforms import is_supported_url
from src.core.validator import validate_and_prepare_media
from src.core.exceptions import ValidationError
from urllib.parse import urlparse
from cachetools import TTLCache

logger = logging.getLogger(__name__)

class YTDLLogger:
    """Forward yt-dlp logs into our structured logger for full debug trail."""
    def debug(self, msg):
        if msg:
            logging.getLogger('yt_dlp').debug(str(msg)[:500])
    def info(self, msg):
        if msg:
            logging.getLogger('yt_dlp').info(str(msg)[:500])
    def warning(self, msg):
        logging.getLogger('yt_dlp').warning(str(msg)[:500])
    def error(self, msg):
        logging.getLogger('yt_dlp').error(str(msg)[:500])

DOWNLOAD_DIR = "downloads"

# Separate semaphores: info fetch vs actual download (prevents pile-up on rapid links)
_info_sem: Optional[asyncio.Semaphore] = None
_download_sem: Optional[asyncio.Semaphore] = None

def _get_info_sem() -> asyncio.Semaphore:
    global _info_sem
    if _info_sem is None:
        _info_sem = asyncio.Semaphore(settings.MAX_CONCURRENT_INFO)
    return _info_sem

def _get_download_sem() -> asyncio.Semaphore:
    global _download_sem
    if _download_sem is None:
        _download_sem = asyncio.Semaphore(settings.MAX_CONCURRENT_DOWNLOADS)
    return _download_sem

_info_cache = TTLCache(maxsize=200, ttl=3600)
_cookies_copy_path: Optional[str] = None

# Standard height tiers — offered only when source supports them (ascending)
VIDEO_HEIGHT_TIERS = [144, 240, 360, 480, 720, 1080, 1440, 2160]

HEIGHT_LABELS = {
    144: "144p",
    240: "240p",
    360: "360p (SD)",
    480: "480p (SD)",
    720: "720p (HD)",
    1080: "1080p (Full HD)",
    1440: "1440p (2K)",
    2160: "4K (2160p)",
}

AUDIO_BITRATE_TIERS = [128, 192, 256, 320]

def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme in ['http', 'https'], result.netloc])
    except ValueError:
        return False

def _video_fmt_string(height: int) -> str:
    tiers = VIDEO_HEIGHT_TIERS
    idx = tiers.index(height) if height in tiers else len(tiers) - 1
    min_h = tiers[idx - 1] + 1 if idx > 0 else 0

    if height <= 480:
        return (
            f"best[height<={height}][height>={min_h}][ext=mp4]/"
            f"best[height<={height}][ext=mp4]/"
            f"bestvideo[height<={height}][height>={min_h}]+bestaudio/"
            f"bestvideo[height<={height}]+bestaudio/"
            f"best[height<={height}]/best"
        )
    return (
        f"bestvideo[height<={height}][height>={min_h}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={height}][height>={min_h}]+bestaudio/"
        f"bestvideo[height<={height}]+bestaudio/"
        f"best[height<={height}]/best"
    )

def build_video_formats(max_height: int) -> List[Dict[str, Any]]:
    """Build ascending quality list from lowest supported tier up to source max."""
    formats: List[Dict[str, Any]] = []
    effective_max = max_height if max_height > 0 else max(VIDEO_HEIGHT_TIERS)

    for h in VIDEO_HEIGHT_TIERS:
        if h <= effective_max:
            formats.append({
                "id": f"{h}p",
                "label": HEIGHT_LABELS.get(h, f"{h}p"),
                "height": h,
                "fmt": _video_fmt_string(h),
            })

    formats.append({
        "id": "best",
        "label": "Highest Available",
        "height": effective_max,
        "fmt": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
    })
    return formats

def build_audio_formats() -> List[Dict[str, Any]]:
    """Audio options ascending by bitrate."""
    formats = []
    for br in AUDIO_BITRATE_TIERS:
        formats.append({
            "id": f"audio{br}",
            "label": f"{br}kbps (MP3)",
            "fmt": "bestaudio/best",
            "ext": "mp3",
            "quality": str(br),
        })
    formats.append({
        "id": "bestaudio",
        "label": "Best Audio (MP3)",
        "fmt": "bestaudio/best",
        "ext": "mp3",
        "quality": "0",
    })
    return formats

# Lookup tables built once
_ALL_VIDEO = {f["id"]: f for f in build_video_formats(9999)}
_ALL_AUDIO = {f["id"]: f for f in build_audio_formats()}

def _is_audio_only(info: dict) -> bool:
    formats = info.get('formats', []) or []
    if not formats:
        return (info.get('vcodec') or 'none') == 'none'
    return not any((f.get('vcodec') or 'none') != 'none' for f in formats)

def _cookies_path() -> Optional[str]:
    global _cookies_copy_path
    src = settings.COOKIES_FILE
    if not src or not os.path.isfile(src) or os.path.getsize(src) <= 64:
        return None
    if _cookies_copy_path and os.path.isfile(_cookies_copy_path):
        return _cookies_copy_path
    dest = os.path.join("data", "cookies.txt")
    try:
        shutil.copy2(src, dest)
        _cookies_copy_path = dest
        logger.debug(f"Using writable cookies copy: {dest}")
        return dest
    except OSError as e:
        logger.warning(f"Could not copy cookies to writable path: {e}")
        return None

def _extract_max_height(info: dict) -> int:
    max_height = 0
    for f in info.get('formats', []) or []:
        h = f.get('height') or 0
        vcodec = f.get('vcodec') or ''
        if h > max_height and vcodec != 'none':
            max_height = h
    if max_height == 0:
        max_height = info.get('height') or 0
    return max_height

def _get_ydl_base_options() -> Dict[str, Any]:
    options: Dict[str, Any] = {
        'quiet': False,
        'no_warnings': False,
        'noplaylist': True,
        'restrictfilenames': True,
        'no_color': True,
        'cachedir': False,
        'logger': YTDLLogger(),
        'concurrent_fragment_downloads': settings.YTDLP_FRAGMENT_CONCURRENCY,
        'retries': 3,
        'fragment_retries': 3,
        'socket_timeout': 30,
        'remote_components': ['ejs:github'],
    }
    if settings.USE_COOKIES:
        cookies = _cookies_path()
        if cookies:
            options['cookiefile'] = cookies
            logger.debug(f"Using cookies file: {cookies}")
    return options

def _get_ydl_options(format_id: str, is_audio: bool, output_path: str, progress_callback=None) -> Dict[str, Any]:
    options = _get_ydl_base_options()
    options['outtmpl'] = output_path

    if progress_callback:
        options['progress_hooks'] = [progress_callback]

    if is_audio:
        audio_cfg = _ALL_AUDIO.get(format_id, build_audio_formats()[-1])
        options.update({
            'format': audio_cfg["fmt"],
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': audio_cfg["ext"],
                'preferredquality': audio_cfg["quality"],
            }],
        })
    else:
        video_cfg = _ALL_VIDEO.get(format_id)
        if not video_cfg:
            for f in build_video_formats(9999):
                if f["id"] == format_id:
                    video_cfg = f
                    break
        if not video_cfg:
            video_cfg = build_video_formats(9999)[-1]
        options.update({
            'format': video_cfg["fmt"],
            'merge_output_format': 'mp4',
        })

    return options

def _get_media_duration(file_path: str) -> float:
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path
    ]
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=30
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0

def split_large_file(file_path: str, max_size_bytes: int = 2 * 1024 * 1024 * 1024) -> list:
    file_size = os.path.getsize(file_path)
    if file_size <= max_size_bytes:
        return [file_path]

    duration = _get_media_duration(file_path)
    if duration <= 0:
        logger.warning(f"Cannot split {file_path}: no duration")
        return [file_path]

    bps = file_size / duration
    seg_time = max(30, int((max_size_bytes * 0.9) / bps))

    parts_dir = file_path + "_parts"
    os.makedirs(parts_dir, exist_ok=True)
    ext = os.path.splitext(file_path)[1] or ".mp4"
    part_pattern = os.path.join(parts_dir, f"part_%03d{ext}")

    cmd = [
        'ffmpeg', '-y', '-i', file_path,
        '-c', 'copy', '-map', '0',
        '-f', 'segment',
        '-segment_time', str(seg_time),
        '-reset_timestamps', '1',
        part_pattern
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10800)
    except Exception as e:
        logger.error(f"ffmpeg split failed for {file_path}: {e}")
        shutil.rmtree(parts_dir, ignore_errors=True)
        return [file_path]

    parts = [os.path.join(parts_dir, f) for f in sorted(os.listdir(parts_dir)) if f.startswith("part_")]
    if not parts:
        shutil.rmtree(parts_dir, ignore_errors=True)
        return [file_path]
    return parts

async def fetch_info(url: str) -> Optional[Dict[str, Any]]:
    if not is_valid_url(url) or not is_supported_url(url):
        logger.warning(f"Rejected URL: {url[:80]}")
        return None

    if url in _info_cache:
        return _info_cache[url]

    def _extract():
        ydl_opts = _get_ydl_base_options()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                max_height = _extract_max_height(info)
                audio_only = _is_audio_only(info)
                final_video = [] if audio_only else build_video_formats(max_height)
                final_audio = build_audio_formats()

                logger.info(
                    f"fetch_info: url={url[:60]} max_h={max_height} "
                    f"video_opts={len(final_video)} audio_opts={len(final_audio)}"
                )

                return {
                    "title": info.get('title', 'Unknown Title'),
                    "thumbnail": info.get('thumbnail', ''),
                    "duration": info.get('duration', 0),
                    "max_height": max_height,
                    "audio_only": audio_only,
                    "formats": {
                        "video": final_video,
                        "audio": final_audio,
                    }
                }
            except Exception as e:
                logger.error(f"Error extracting info for {url}: {e}")
                return None

    async with _get_info_sem():
        try:
            result = await asyncio.wait_for(asyncio.to_thread(_extract), timeout=settings.YTDLP_TIMEOUT)
            if result:
                _info_cache[url] = result
            return result
        except asyncio.TimeoutError:
            logger.error(f"Timeout extracting info for {url}")
            return None

async def download_media(url: str, format_id: str = 'best', is_audio: bool = False, progress_callback=None) -> Tuple[bool, str, str]:
    if not is_valid_url(url) or not is_supported_url(url):
        return False, "Unsupported platform.", ""

    file_id = str(uuid.uuid4())
    if is_audio:
        expected_final_path = os.path.join(DOWNLOAD_DIR, file_id)
    else:
        expected_final_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.mp4")

    def _download() -> Tuple[bool, str, str]:
        opts = _get_ydl_options(format_id, is_audio, expected_final_path, progress_callback=progress_callback)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Unknown Title')
                actual = expected_final_path
                if info.get('requested_downloads'):
                    actual = info['requested_downloads'][0].get('filepath') or info['requested_downloads'][0].get('_filename') or actual
                elif info.get('_filename'):
                    actual = info['_filename']
                actual_fmt = info.get('format') or info.get('format_id', 'unknown')
                actual_h = info.get('height') or (info.get('requested_formats') or [{}])[0].get('height')
                actual_w = info.get('width') or (info.get('requested_formats') or [{}])[0].get('width')
                fsize = info.get('filesize') or info.get('filesize_approx')
                logger.info(f"yt-dlp picked: fmt={actual_fmt} res={actual_w}x{actual_h} size={fsize} path={actual}")
                return True, actual, title
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Download error for {url}: {e}")
            return False, "Download failed or unsupported format for this URL.", ""
        except Exception as e:
            if str(e) == "DownloadCancelled":
                raise e
            logger.error(f"Unexpected error for {url}: {e}")
            return False, "An unexpected error occurred.", ""

    async with _get_download_sem():
        try:
            success, path, title = await asyncio.wait_for(asyncio.to_thread(_download), timeout=settings.YTDLP_TIMEOUT)

            if success:
                try:
                    path = await validate_and_prepare_media(path, is_audio)
                except ValidationError as ve:
                    if os.path.exists(path):
                        os.remove(path)
                    raise ve

            return success, path, title
        except asyncio.TimeoutError:
            logger.error(f"Download timeout for {url}")
            if os.path.exists(expected_final_path):
                os.remove(expected_final_path)
            return False, "Download timed out.", ""
        except Exception as e:
            if str(e) == "DownloadCancelled":
                raise e
            logger.error(f"Error during download for {url}: {e}")
            return False, f"Download failed: {e}", ""
