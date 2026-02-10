"""Конфигурация приложения."""
import os
from functools import lru_cache


@lru_cache
def get_config():
    return type("Config", (), {
        "telegram_bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "debug": os.environ.get("DEBUG", "0").lower() in ("1", "true", "yes"),
        "allowed_origins": os.environ.get("ALLOWED_ORIGINS", "*").split(","),
    })()
