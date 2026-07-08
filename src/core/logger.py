import logging
import sys
import contextvars
from pythonjsonlogger import jsonlogger
from src.core.config import settings

# Context variable for request reference ID
reference_id_var = contextvars.ContextVar('reference_id', default=None)

class ReferenceIdFilter(logging.Filter):
    """Injects reference_id into log records."""
    def filter(self, record):
        ref_id = reference_id_var.get()
        if ref_id:
            record.reference_id = ref_id
        return True

def setup_logger():
    """Configure structured JSON logging. Much richer for debug."""
    root = logging.getLogger()
    
    # Remove existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root.setLevel(log_level)
    
    logHandler = logging.StreamHandler(sys.stdout)
    
    # Define JSON formatter - include extra fields, ref always if set
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s',
        rename_fields={"levelname": "level", "asctime": "timestamp"},
        json_ensure_ascii=False
    )
    
    logHandler.setFormatter(formatter)
    
    # Add filter to inject reference_id
    logHandler.addFilter(ReferenceIdFilter())
    
    root.addHandler(logHandler)
    
    # yt_dlp gets same handler + level for complete trace (SABR, format skips etc)
    yt_logger = logging.getLogger('yt_dlp')
    yt_logger.setLevel(log_level)
    yt_logger.addHandler(logHandler)
    yt_logger.propagate = False
    
    # Reduce noise from libs in prod
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('aiogram').setLevel(logging.WARNING)
    
    return root
