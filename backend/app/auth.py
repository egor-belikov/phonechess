"""
Проверка Telegram Web App initData.
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
from urllib.parse import parse_qsl

from .config import get_config


def validate_init_data(init_data: str) -> dict | None:
    """
    Проверяет подпись initData и возвращает данные пользователя или None.
    init_data — строка в формате query string из Telegram.WebApp.initData.
    """
    if not init_data:
        return None
    config = get_config()
    token = config.telegram_bot_token
    if not token:
        if config.debug:
            # В режиме отладки без токена принимаем тестовые данные
            return _parse_init_data_unsafe(init_data)
        return None

    try:
        parsed = dict(parse_qsl(init_data))
    except Exception:
        return None

    hash_from_tg = parsed.pop("hash", None)
    if not hash_from_tg:
        return None

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        token.encode(),
        hashlib.sha256
    ).digest()
    calculated = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated, hash_from_tg):
        return None

    return _parse_user_from_parsed(parsed)


def _parse_init_data_unsafe(init_data: str) -> dict | None:
    """Парсит init_data без проверки подписи (только для debug)."""
    try:
        parsed = dict(parse_qsl(init_data))
        return _parse_user_from_parsed(parsed)
    except Exception:
        return None


def _parse_user_from_parsed(parsed: dict) -> dict | None:
    """Извлекает user из parsed (user — JSON строка)."""
    import json
    user_str = parsed.get("user")
    if not user_str:
        return None
    try:
        user = json.loads(user_str)
        return {
            "id": user.get("id"),
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "username": user.get("username", ""),
        }
    except (json.JSONDecodeError, TypeError):
        return None
