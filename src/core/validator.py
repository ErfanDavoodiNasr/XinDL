import os
import json
import asyncio
import logging
from typing import Dict, Any, Tuple
from src.core.exceptions import ValidationError, RepairFailedError
from src.core.config import settings

logger = logging.getLogger(__name__)

async def _run_command(*cmd) -> Tuple[int, str, str]:
    """Runs a shell command and returns returncode, stdout, stderr."""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=180.0)
    return process.returncode, stdout.decode(), stderr.decode()

async def _get_ffprobe_data(file_path: str) -> Dict[str, Any]:
    """Extract deep metadata using ffprobe."""
    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        '-show_streams',
        file_path
    ]
    code, stdout, _ = await _run_command(*cmd)
    if code != 0:
        raise ValidationError("File container is severely corrupted (ffprobe failed).")
    return json.loads(stdout)

async def _estimate_frame_count(file_path: str, duration: float) -> int:
    """Fast frame estimate from stream metadata — no full decode."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=nb_frames,r_frame_rate,avg_frame_rate',
        '-of', 'json',
        file_path,
    ]
    code, stdout, _ = await _run_command(*cmd)
    if code != 0:
        return -1
    try:
        data = json.loads(stdout)
        streams = data.get('streams') or []
        if not streams:
            return -1
        stream = streams[0]
        nb = stream.get('nb_frames')
        if nb and str(nb).isdigit():
            return int(nb)
        rate = stream.get('avg_frame_rate') or stream.get('r_frame_rate') or ''
        if '/' in str(rate):
            num, den = str(rate).split('/', 1)
            fps = float(num) / float(den) if float(den) else 0.0
            if fps > 0 and duration > 0:
                return int(duration * fps)
    except (ValueError, json.JSONDecodeError, ZeroDivisionError):
        pass
    return -1

async def _attempt_repair(file_path: str, is_audio: bool) -> str:
    """Attempts to repair a broken file using ffmpeg."""
    logger.info(f"Attempting to repair corrupted file: {file_path}")
    repaired_path = f"{file_path}.repaired"
    
    # Level 1: Stream Copy (Fast container fix)
    logger.info("Repair Level 1: Stream Copy")
    cmd = [
        'ffmpeg', '-y', '-v', 'error',
        '-err_detect', 'ignore_err',
        '-i', file_path,
        '-c', 'copy',
        repaired_path
    ]
    
    code, _, stderr = await _run_command(*cmd)
    if code == 0 and os.path.exists(repaired_path) and os.path.getsize(repaired_path) > 0:
        logger.info("Level 1 Repair successful.")
        os.remove(file_path)
        os.rename(repaired_path, file_path)
        return file_path
        
    # Level 2: Transcode (Slow, heavy fix if copy fails)
    if os.path.exists(repaired_path):
        os.remove(repaired_path)
        
    logger.info("Repair Level 2: Transcode")
    cmd = ['ffmpeg', '-y', '-v', 'error', '-err_detect', 'ignore_err', '-i', file_path]
    
    if is_audio:
        cmd.extend(['-c:a', 'aac', '-b:a', '128k', repaired_path])
    else:
        cmd.extend(['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', '-c:a', 'aac', repaired_path])
        
    code, _, stderr = await _run_command(*cmd)
    if code == 0 and os.path.exists(repaired_path) and os.path.getsize(repaired_path) > 0:
        logger.info("Level 2 Repair successful.")
        os.remove(file_path)
        os.rename(repaired_path, file_path)
        return file_path
        
    raise RepairFailedError(f"Automated repair failed entirely. stderr: {stderr}")

async def validate_and_prepare_media(file_path: str, is_audio: bool) -> str:
    """
    Validates media deeply. If it fails, attempts repair.
    Throws ValidationError if the media is unsalvageable.
    Returns the path to the valid/repaired media.
    """
    logger.info(f"Validating file: {file_path}")
    
    if not os.path.exists(file_path):
        raise ValidationError("File does not exist.")
        
    if os.path.getsize(file_path) == 0:
        raise ValidationError("Downloaded file is empty (0 bytes).")
        
    try:
        metadata = await _get_ffprobe_data(file_path)
        
        duration = float(metadata.get('format', {}).get('duration', 0))
        if duration <= 0:
            raise ValidationError("File has zero or missing duration.")
            
        streams = metadata.get('streams', [])
        has_video = any(s.get('codec_type') == 'video' for s in streams)
        has_audio = any(s.get('codec_type') == 'audio' for s in streams)
        
        if is_audio and not has_audio:
            raise ValidationError("Requested audio, but no audio stream found.")
            
        if not is_audio and not has_video:
            raise ValidationError("Requested video, but no video stream found.", fallback_suggested=True)
            
        if not is_audio and has_video and not settings.SKIP_FRAME_DECODE_VALIDATION:
            if duration > 2.0:
                frame_count = await _estimate_frame_count(file_path, duration)
                if 0 < frame_count < 5:
                    raise ValidationError(
                        "Video appears to be a static image (stuck on single frame).",
                        fallback_suggested=True,
                    )

        return file_path
        
    except ValidationError as e:
        logger.warning(f"Validation failed: {e.message}. Triggering repair...")
        # If it's a structural error, try repair. 
        # If it's just missing video, repair won't create video, so just fail directly.
        if e.fallback_suggested:
            raise e
            
        try:
            repaired_path = await _attempt_repair(file_path, is_audio)
            logger.info("File successfully repaired. Running final validation pass...")
            
            # Re-validate the repaired file (without triggering infinite loop)
            # Basic sanity check on repaired file
            rep_metadata = await _get_ffprobe_data(repaired_path)
            if float(rep_metadata.get('format', {}).get('duration', 0)) <= 0:
                 raise RepairFailedError("Repaired file still has zero duration.")
                 
            return repaired_path
        except Exception as repair_e:
            logger.error(f"Repair process failed: {repair_e}")
            raise ValidationError("File is severely corrupted and automated repair failed.", fallback_suggested=True)
            
    except asyncio.TimeoutError:
        raise ValidationError("Validation process timed out.", fallback_suggested=True)
    except Exception as e:
        logger.error(f"Unexpected validation error: {e}")
        raise ValidationError(f"Unexpected validation error: {e}")
