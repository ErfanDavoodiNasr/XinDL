import os
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    # Application Settings
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    AUTO_TUNE_RESOURCES: bool = True

    # Telegram Bot Settings
    BOT_TOKEN: str = "default_token_override_me"
    ADMIN_IDS: str = ""
    
    USE_LOCAL_API: bool = False
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ""
    TELEGRAM_LOCAL_API_URL: str = "http://127.0.0.1:8081"
    LOCAL_API_STARTUP_TIMEOUT: int = 120
    
    # Download Settings
    MAX_FILESIZE_BYTES: int = 2000 * 1024 * 1024 # legacy, not enforced (large files auto-split into 2GB parts)
    MAX_CONCURRENT_DOWNLOADS: int = 3
    MAX_CONCURRENT_INFO: int = 5
    MAX_CONCURRENT_UPLOADS: int = 2
    MAX_BACKGROUND_TASKS: int = 8
    THREAD_POOL_WORKERS: int = 4
    USER_RATE_LIMIT_PER_MINUTE: int = 20
    USER_MAX_ACTIVE_DOWNLOADS: int = 2
    YTDLP_TIMEOUT: int = 300
    YTDLP_FRAGMENT_CONCURRENCY: int = 8
    COOKIES_FILE: str = "cookies/cookies.txt"
    USE_COOKIES: bool = False
    SKIP_FRAME_DECODE_VALIDATION: bool = True
    
    @property
    def admin_ids_list(self) -> List[int]:
        if not self.ADMIN_IDS:
            return []
        try:
            return [int(admin_id.strip()) for admin_id in self.ADMIN_IDS.split(",") if admin_id.strip()]
        except ValueError:
            return []

    # Database Configuration
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/xindl.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

if settings.AUTO_TUNE_RESOURCES:
    from src.core.resources import compute_concurrency_limits

    tuned = compute_concurrency_limits()
    for key, value in tuned.items():
        if hasattr(settings, key):
            object.__setattr__(settings, key, value)

# Ensure directories exist
os.makedirs("data", exist_ok=True)
os.makedirs("downloads", exist_ok=True)
