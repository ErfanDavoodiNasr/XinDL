import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    # Application Settings
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # Telegram Bot Settings
    BOT_TOKEN: str = "default_token_override_me"
    ADMIN_IDS: str = ""
    
    USE_LOCAL_API: bool = False
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = "" # Comma-separated
    
    # Download Settings
    MAX_FILESIZE_BYTES: int = 2000 * 1024 * 1024 # 2000MB
    MAX_CONCURRENT_DOWNLOADS: int = 5
    YTDLP_TIMEOUT: int = 300 # 5 minutes timeout per download step
    
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

# Ensure directories exist
os.makedirs("data", exist_ok=True)
os.makedirs("downloads", exist_ok=True)
