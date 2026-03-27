"""
Простой webhook-обработчик Telegram-бота:
- приветствие на /start
- кнопка открытия Web App
"""
import json
import logging
import urllib.error
import urllib.request
from typing import Any

from .config import get_config
from .pairing import mark_user_started_bot

logger = logging.getLogger(__name__)


def _webapp_link_for_start_param(start_param: str | None = None) -> str:
    cfg = get_config()
    base = (cfg.telegram_webapp_url or "").strip()
    if not start_param:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}startapp={start_param}"


def _bot_api(method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    cfg = get_config()
    token = cfg.telegram_bot_token
    if not token:
        logger.warning("Telegram bot token is empty, skip %s", method)
        return None
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        logger.warning("Telegram API %s failed: %s", method, e)
        return None


def send_start_message(chat_id: int) -> None:
    webapp_url = _webapp_link_for_start_param(None)
    text = (
        "Привет! Это PhoneChess.\n\n"
        "Нажми кнопку ниже, чтобы открыть веб-приложение и начать игру."
    )
    _bot_api(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {
                            "text": "Открыть PhoneChess",
                            "web_app": {"url": webapp_url},
                        }
                    ]
                ]
            },
        },
    )


def send_private_start_message(chat_id: int, invite_key: str) -> None:
    start_param = f"private_{invite_key}"
    webapp_url = _webapp_link_for_start_param(start_param)
    text = (
        "Вас пригласили в приватную игру PhoneChess.\n\n"
        "Нажмите «Начать игру», чтобы открыть матч."
    )
    _bot_api(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {
                            "text": "Начать игру",
                            "web_app": {"url": webapp_url},
                        }
                    ]
                ]
            },
        },
    )


def send_webapp_message(chat_id: int, text: str, webapp_url: str | None = None) -> None:
    target = webapp_url or _webapp_link_for_start_param(None)
    _bot_api(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {
                            "text": "Открыть PhoneChess",
                            "web_app": {"url": target},
                        }
                    ]
                ]
            },
        },
    )


def process_update(update: dict[str, Any]) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not isinstance(msg, dict):
        return
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return
    if text.startswith("/start"):
        user = msg.get("from") or {}
        username = user.get("username") or user.get("first_name") or ""
        mark_user_started_bot(int(chat_id), username=username)
        parts = text.split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""
        if payload.startswith("private_"):
            invite_key = payload[len("private_"):].strip()
            if invite_key:
                send_private_start_message(int(chat_id), invite_key)
                return
        send_start_message(int(chat_id))
