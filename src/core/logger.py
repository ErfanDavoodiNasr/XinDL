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
    """Configure structured JSON logging."""
    logger = logging.getLogger()
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(log_level)
    
    logHandler = logging.StreamHandler(sys.stdout)
    
    # Define JSON formatter
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s',
        rename_fields={"levelname": "level", "asctime": "timestamp"}
    )
    
    logHandler.setFormatter(formatter)
    
    # Add filter to inject reference_id
    logHandler.addFilter(ReferenceIdFilter())
    
    logger.addHandler(logHandler)
    
    return logger
