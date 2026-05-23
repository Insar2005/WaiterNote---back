import os
from functools import lru_cache


class Settings:
    BOT_TOKEN: str
    INIT_DATA_TTL: int  # seconds
    CORS_ORIGINS: list[str]
    DEBUG: bool

    def __init__(self) -> None:
        token = os.getenv("BOT_TOKEN")
        if not token:
            raise RuntimeError("BOT_TOKEN is not set")
        self.BOT_TOKEN = token

        # 24 hours by default — Telegram WebApp recommends 5 min, но в реальности
        # сессия может висеть дольше; делаем настраиваемо.
        self.INIT_DATA_TTL = int(os.getenv("INIT_DATA_TTL", "86400"))

        origins = os.getenv("CORS_ORIGINS", "")
        self.CORS_ORIGINS = [o.strip() for o in origins.split(",") if o.strip()]

        self.DEBUG = os.getenv("DEBUG", "").lower() in {"1", "true", "yes", "on"}


@lru_cache
def get_settings() -> Settings:
    return Settings()