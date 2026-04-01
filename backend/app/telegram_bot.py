"""
Простой webhook-обработчик Telegram-бота:
- приветствие на /start
- кнопка открытия Web App
"""
import html
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


def send_webapp_message(chat_id: int, text: str, webapp_url: str | None = None) -> int | None:
    """Отправить сообщение с кнопкой WebApp. Возвращает message_id при успехе."""
    target = webapp_url or _webapp_link_for_start_param(None)
    res = _bot_api(
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
    if not res or not res.get("ok"):
        return None
    msg = res.get("result") or {}
    mid = msg.get("message_id")
    return int(mid) if mid is not None else None


def format_game_finished_html(result: str, reason: str | None, detail: str | None, san_moves: list[str]) -> str:
    """HTML-текст с блоком <pre> для списка ходов (копирование в Telegram)."""
    reason_txt = html.escape(reason or "—")
    detail_txt = html.escape(detail or "—")
    res_txt = html.escape(result or "?")
    lines: list[str] = []
    sans = san_moves or []
    for i in range(0, len(sans), 2):
        n = i // 2 + 1
        w = sans[i]
        b = sans[i + 1] if i + 1 < len(sans) else ""
        if b:
            lines.append(f"{n}. {w} {b}")
        else:
            lines.append(f"{n}. {w}")
    pgn_block = "\n".join(lines) if lines else "—"
    pre_body = html.escape(pgn_block)
    return (
        "Партия завершена.\n\n"
        f"Результат: <b>{res_txt}</b>\n"
        f"Причина: {reason_txt}\n"
        f"Детали: {detail_txt}\n\n"
        f"Ходы:\n<pre>{pre_body}</pre>"
    )


def send_game_result_message(chat_id: int, text: str) -> None:
    webapp_url = _webapp_link_for_start_param(None)
    target = webapp_url
    _bot_api(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
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


def edit_webapp_message_html(chat_id: int, message_id: int, html_text: str) -> bool:
    """Редактировать текст сообщения (HTML). Кнопка WebApp сохраняется через reply_markup."""
    webapp_url = _webapp_link_for_start_param(None)
    res = _bot_api(
        "editMessageText",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": html_text,
            "parse_mode": "HTML",
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
    return bool(res and res.get("ok"))


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
