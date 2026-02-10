"""
Обработка сообщений WebSocket: auth, join_queue, leave_queue.
При матче — создание партии и отправка matched обоим игрокам.
"""
import json
import logging
from typing import Any

from fastapi import WebSocket

from .auth import validate_init_data
from .config import get_config
from .pairing import (
    get_queue_counts,
    join_queue,
    leave_all_queues,
    leave_queue,
)
from .ws_manager import manager

logger = logging.getLogger(__name__)


def _user_id(telegram_id: int) -> str:
    return str(telegram_id)


async def handle_ws_message(ws: WebSocket, raw: str, user_id: str) -> bool:
    """
    Обрабатывает одно сообщение от уже авторизованного клиента.
    Возвращает False если соединение нужно закрыть.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return True
    t = data.get("type")
    if t == "join_queue":
        time_control = data.get("time_control")
        if time_control not in get_queue_counts():
            return True
        conn = manager._by_user.get(user_id)
        if not conn:
            return True
        game = join_queue(
            time_control,
            user_id,
            conn.telegram_id,
            conn.username or "",
        )
        if game:
            # Отправить обоим игрокам matched
            white_payload = {
                "type": "matched",
                "game_id": game.id,
                "color": "white",
                "time_control": game.time_control_key,
                "fen": game.fen,
                "white_username": game.white_username,
                "black_username": game.black_username,
            }
            black_payload = {
                "type": "matched",
                "game_id": game.id,
                "color": "black",
                "time_control": game.time_control_key,
                "fen": game.fen,
                "white_username": game.white_username,
                "black_username": game.black_username,
            }
            await manager.send_to_user(game.white_id, white_payload)
            await manager.send_to_user(game.black_id, black_payload)
        await manager.broadcast_queue_counts()
        return True
    if t == "leave_queue":
        time_control = data.get("time_control")
        if time_control:
            leave_queue(time_control, user_id)
        else:
            leave_all_queues(user_id)
        await manager.broadcast_queue_counts()
        return True
    return True


async def ws_auth_and_loop(ws: WebSocket) -> None:
    """
    Первое сообщение — auth с init_data. Дальше цикл приёма сообщений.
    """
    config = get_config()
    user_id = None
    try:
        # Обязательный handshake перед получением/отправкой данных
        await ws.accept()
        raw = await ws.receive_text()
        data = json.loads(raw)
        if data.get("type") != "auth":
            await ws.close(code=4001)
            return
        init_data = data.get("init_data", "")
        if config.debug and not init_data:
            # Для тестов без Telegram: auth с тестовым user (debug_uid для двух вкладок)
            uid = data.get("debug_uid", 0)
            user = {"id": uid, "first_name": "Dev", "username": f"dev{uid}"}
        else:
            user = validate_init_data(init_data)
        if not user:
            await ws.close(code=4003)
            return
        telegram_id = int(user["id"])
        user_id = _user_id(telegram_id)
        username = user.get("username") or user.get("first_name") or ""
        await manager.connect(ws, user_id, telegram_id, username)
        # Отправить текущие счётчики очередей
        await manager.send_to_user(
            user_id,
            {"type": "queue_counts", "counts": get_queue_counts()},
        )
        while True:
            msg = await ws.receive_text()
            if not await handle_ws_message(ws, msg, user_id):
                break
    except Exception as e:
        logger.exception("ws loop: %s", e)
    finally:
        if user_id:
            leave_all_queues(user_id)
            manager.disconnect(user_id)
            await manager.broadcast_queue_counts()
