"""Конфигурация приложения."""
import os
from functools import lru_cache


@lru_cache
def get_config():
    return type("Config", (), {
        "telegram_bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "bot_username": os.environ.get("TELEGRAM_BOT_USERNAME", ""),
        "telegram_webapp_url": os.environ.get("TELEGRAM_WEBAPP_URL", "https://chess.apichatpong.online/"),
        "database_url": os.environ.get("DATABASE_URL", "sqlite+pysqlite:///./phonechess.db"),
        "stockfish_path": os.environ.get("STOCKFISH_PATH", "/usr/games/stockfish"),
        "debug": os.environ.get("DEBUG", "0").lower() in ("1", "true", "yes"),
        "allowed_origins": os.environ.get("ALLOWED_ORIGINS", "*").split(","),
    })()
