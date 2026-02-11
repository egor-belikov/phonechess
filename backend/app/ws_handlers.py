"""
Обработка сообщений WebSocket: auth, join_queue, leave_queue.
При матче — создание партии и отправка matched обоим игрокам.
"""
import json
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from .auth import validate_init_data
from .config import get_config
from .pairing import (
    apply_move,
    game_state_payload,
    get_game_for_user,
    get_queue_counts,
    join_queue,
    leave_all_queues,
    leave_queue,
    resign_game,
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
    except json.JSONDecodeError as e:
        logger.warning("WS: invalid JSON from %s: %s", user_id, e)
        return True
    t = data.get("type")
    logger.info("WS: msg from %s type=%s", user_id, t)
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
            # Отправить обоим игрокам matched (с начальными часами)
            base = {
                "type": "matched",
                "game_id": game.id,
                "time_control": game.time_control_key,
                "fen": game.fen,
                "white_username": game.white_username,
                "black_username": game.black_username,
                "white_remaining_ms": game.white_remaining_ms,
                "black_remaining_ms": game.black_remaining_ms,
            }
            white_payload = {**base, "color": "white"}
            black_payload = {**base, "color": "black"}
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
    if t == "subscribe_game":
        game_id = data.get("game_id")
        g = get_game_for_user(game_id, user_id) if game_id else None
        if g:
            await manager.send_to_user(user_id, game_state_payload(g))
        return True
    if t == "make_move":
        game_id = data.get("game_id")
        from_sq = data.get("from")
        to_sq = data.get("to")
        promotion = data.get("promotion")
        g = get_game_for_user(game_id, user_id) if game_id else None
        if g and from_sq and to_sq:
            update = apply_move(game_id, user_id, from_sq, to_sq, promotion)
            if update:
                payload = {
                    "type": "game_update",
                    "fen": update["fen"],
                    "white_remaining_ms": update["white_remaining_ms"],
                    "black_remaining_ms": update["black_remaining_ms"],
                    "san": update["san"],
                    "move_time_ms": update["move_time_ms"],
                    "result": update["result"],
                    "from": update.get("from"),
                    "to": update.get("to"),
                }
                await manager.send_to_user(g.white_id, payload)
                await manager.send_to_user(g.black_id, payload)
        return True
    if t == "resign":
        game_id = data.get("game_id")
        g = get_game_for_user(game_id, user_id) if game_id else None
        if g:
            update = resign_game(game_id, user_id)
            if update:
                payload = {
                    "type": "game_update",
                    "fen": update["fen"],
                    "white_remaining_ms": update["white_remaining_ms"],
                    "black_remaining_ms": update["black_remaining_ms"],
                    "result": update["result"],
                }
                await manager.send_to_user(g.white_id, payload)
                await manager.send_to_user(g.black_id, payload)
        return True
    return True


async def ws_auth_and_loop(ws: WebSocket) -> None:
    """
    Первое сообщение — auth с init_data. Дальше цикл приёма сообщений.
    """
    config = get_config()
    user_id = None
    try:
        await ws.accept()
        logger.info("WS: accepted, waiting for auth")
        raw = await ws.receive_text()
        data = json.loads(raw)
        msg_type = data.get("type")
        logger.info("WS: first message type=%s", msg_type)
        if msg_type != "auth":
            logger.warning("WS: expected auth, got %s, closing 4001", msg_type)
            await ws.close(code=4001)
            return
        init_data = data.get("init_data", "")
        if config.debug and not init_data:
            uid = data.get("debug_uid", 0)
            user = {"id": uid, "first_name": "Dev", "username": f"dev{uid}"}
            logger.info("WS: debug auth, uid=%s", uid)
        else:
            user = validate_init_data(init_data)
        if not user:
            logger.warning("WS: auth failed (invalid init_data or not debug)")
            await ws.close(code=4003)
            return
        telegram_id = int(user["id"])
        user_id = _user_id(telegram_id)
        username = user.get("username") or user.get("first_name") or ""
        await manager.connect(ws, user_id, telegram_id, username)
        logger.info("WS: auth ok user_id=%s username=%s", user_id, username)
        await manager.send_to_user(
            user_id,
            {"type": "queue_counts", "counts": get_queue_counts()},
        )
        logger.info("WS: queue_counts sent to %s", user_id)
        while True:
            msg = await ws.receive_text()
            if not await handle_ws_message(ws, msg, user_id):
                break
    except WebSocketDisconnect as e:
        logger.info("WS: client disconnected code=%s reason=%s user_id=%s", e.code, e.reason or "", user_id)
    except Exception as e:
        logger.exception("WS: error user_id=%s: %s", user_id, e)
    finally:
        if user_id:
            leave_all_queues(user_id)
            manager.disconnect(user_id)
            await manager.broadcast_queue_counts()
            logger.info("WS: disconnected user_id=%s", user_id)
