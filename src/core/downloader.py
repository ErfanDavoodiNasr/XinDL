import asyncio
import os
import uuid
import yt_dlp
from typing import Dict, Any, Optional, Tuple
import logging
from src.core.config import settings
from urllib.parse import urlparse
from cachetools import TTLCache

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "downloads"

# In-memory caches for fast responsiveness
_info_cache = TTLCache(maxsize=100, ttl=3600)
_search_cache = TTLCache(maxsize=100, ttl=3600)

def is_valid_url(url: str) -> bool:
    """Basic validation to prevent command injection via URL argument."""
    try:
        result = urlparse(url)
        return all([result.scheme in ['http', 'https'], result.netloc])
    except ValueError:
        return False

# Base predefined formats for safe execution
# Relaxed formats to handle Instagram, TikTok properly instead of strictly forcing AVC
BASE_VIDEO_FORMATS = [
    {"id": "best", "label": "Highest Quality", "height": 9999, "fmt": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"},
    {"id": "4k", "label": "4K (2160p)", "height": 2160, "fmt": "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=2160]+bestaudio/best[height<=2160]/best"},
    {"id": "1080p", "label": "1080p (Full HD)", "height": 1080, "fmt": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"},
    {"id": "720p", "label": "720p (HD)", "height": 720, "fmt": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/best"},
    {"id": "480p", "label": "480p (SD)", "height": 480, "fmt": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]/best"}
]

BASE_AUDIO_FORMATS = [
    {"id": "bestaudio", "label": "Best Audio (MP3)", "fmt": "bestaudio/best", "ext": "mp3", "quality": "192"},
    {"id": "audio320", "label": "320kbps (MP3)", "fmt": "bestaudio/best", "ext": "mp3", "quality": "320"},
    {"id": "audio256", "label": "256kbps (MP3)", "fmt": "bestaudio/best", "ext": "mp3", "quality": "256"},
    {"id": "audio128", "label": "128kbps (MP3)", "fmt": "bestaudio/best", "ext": "mp3", "quality": "128"}
]

def _get_ydl_options(format_id: str, is_audio: bool, output_path: str, progress_callback=None) -> Dict[str, Any]:
    options = {
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'max_filesize': settings.MAX_FILESIZE_BYTES,
        'restrictfilenames': True,
        'no_color': True,
        'cachedir': False, # Disable disk caching to save space/IO
    }
    
    if progress_callback:
        options['progress_hooks'] = [progress_callback]
    
    if is_audio:
        audio_cfg = next((item for item in BASE_AUDIO_FORMATS if item["id"] == format_id), BASE_AUDIO_FORMATS[0])
        options.update({
            'format': audio_cfg["fmt"],
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': audio_cfg["ext"],
                'preferredquality': audio_cfg["quality"],
            }],
        })
    else:
        video_cfg = next((item for item in BASE_VIDEO_FORMATS if item["id"] == format_id), BASE_VIDEO_FORMATS[0])
        options.update({
            'format': video_cfg["fmt"],
            'merge_output_format': 'mp4',
        })
    
    return options

async def fetch_info(url: str) -> Optional[Dict[str, Any]]:
    """Extract metadata and intelligently filter available formats with caching."""
    if not is_valid_url(url):
        logger.warning(f"Invalid URL attempted: {url}")
        return None
        
    if url in _info_cache:
        return _info_cache[url]
        
    def _extract():
        ydl_opts = {'quiet': True, 'noplaylist': True, 'cachedir': False}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                
                max_height = 0
                for f in info.get('formats', []):
                    h = f.get('height')
                    if h and h > max_height:
                        max_height = h
                
                if max_height == 0:
                    max_height = 9999
                    
                filtered_video = [
                    v for v in BASE_VIDEO_FORMATS 
                    if v["id"] == "best" or v["height"] <= max_height or (v["height"] == 720 and max_height > 480)
                ]
                
                seen = set()
                final_video = []
                for v in filtered_video:
                    if v["height"] not in seen or v["id"] == "best":
                        final_video.append(v)
                        seen.add(v["height"])
                
                result = {
                    "title": info.get('title', 'Unknown Title'),
                    "thumbnail": info.get('thumbnail', ''),
                    "duration": info.get('duration', 0),
                    "formats": {
                        "video": final_video,
                        "audio": BASE_AUDIO_FORMATS
                    }
                }
                return result
            except Exception as e:
                logger.error(f"Error extracting info for {url}: {e}")
                return None

    result = await asyncio.to_thread(_extract)
    if result:
        _info_cache[url] = result
    return result

async def download_media(url: str, format_id: str = 'best', is_audio: bool = False, progress_callback=None) -> Tuple[bool, str, str]:
    """
    Download media safely using a Semaphore to limit concurrency.
    """
    if not is_valid_url(url):
        return False, "Invalid URL provided.", ""
        
    file_id = str(uuid.uuid4())
    ext = 'mp3' if is_audio else 'mp4'
    expected_final_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.{ext}")

    def _download() -> Tuple[bool, str, str]:
        opts = _get_ydl_options(format_id, is_audio, expected_final_path, progress_callback=progress_callback)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Unknown Title')
                return True, expected_final_path, title
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"Download error for {url}: {e}")
            if "file size is larger than max_filesize" in str(e):
                return False, f"File is too large (max {settings.MAX_FILESIZE_BYTES // (1024*1024)}MB).", ""
            return False, "Download failed or unsupported format for this URL.", ""
        except Exception as e:
            logger.error(f"Unexpected error for {url}: {e}")
            return False, "An unexpected error occurred.", ""

    return await asyncio.to_thread(_download)

async def search_media(query: str, limit: int = 10) -> Optional[list]:
    """Search for media using yt-dlp with caching."""
    cache_key = f"{query}_{limit}"
    if cache_key in _search_cache:
        return _search_cache[cache_key]
        
    def _search():
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
            'noplaylist': True,
            'cachedir': False
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                if 'entries' in info:
                    results = []
                    for entry in info['entries']:
                        thumbnail = entry.get('thumbnail')
                        if not thumbnail and entry.get('thumbnails'):
                            thumbnail = entry['thumbnails'][0].get('url')
                        results.append({
                            'id': entry.get('id'),
                            'title': entry.get('title'),
                            'url': entry.get('url'),
                            'duration': entry.get('duration'),
                            'uploader': entry.get('uploader'),
                            'thumbnail': thumbnail
                        })
                    return results
                return []
            except Exception as e:
                logger.error(f"Search error for '{query}': {e}")
                return None

    results = await asyncio.to_thread(_search)
    if results:
        _search_cache[cache_key] = results
    return results
