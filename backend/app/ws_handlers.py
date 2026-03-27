"""
Обработка сообщений WebSocket: auth, join_queue, leave_queue.
При матче — создание партии и отправка matched обоим игрокам.
"""
import json
import logging
import asyncio
from typing import Any

import chess
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from .auth import validate_init_data
from .config import get_config
from .pairing import (
    apply_move,
    abort_game_and_requeue,
    game_state_payload,
    get_game_for_user,
    get_queue_counts,
    join_queue,
    leave_all_queues,
    leave_queue,
    resign_game,
    offer_draw,
    accept_draw_offer,
    claim_draw,
    get_active_game_for_user,
    forfeit_disconnected_player,
    materialize_live_clocks,
    turn_user_id,
    ensure_user_registered,
    create_private_invite,
    join_private_invite,
    get_history_by_invite_key,
    get_user_notification_target,
    activate_private_invite,
    get_history_by_game_id_for_user,
    create_bot_game,
    get_game_any,
    abort_unstarted_game,
    create_private_rematch,
)
from .ws_manager import manager
from .telegram_bot import send_webapp_message, send_game_result_message
from .uci_bot import pick_move_weak_uci
from .config import get_config

logger = logging.getLogger(__name__)
DISCONNECT_GRACE_SECONDS = 10
_disconnect_tasks: dict[str, asyncio.Task] = {}
_private_room_presence: dict[str, set[str]] = {}
_start_abort_tasks: dict[str, asyncio.Task] = {}
_rematch_votes: dict[str, set[str]] = {}
_bot_move_tasks: dict[str, asyncio.Task] = {}
_result_notified_games: set[str] = set()


def _user_id(telegram_id: int) -> str:
    return str(telegram_id)


def _cancel_start_abort_task(game_id: str) -> None:
    t = _start_abort_tasks.pop(game_id, None)
    if t:
        t.cancel()


async def _schedule_unstarted_abort(game_id: str) -> None:
    try:
        await asyncio.sleep(60)
        g = get_game_any(game_id)
        if not g or g.result is not None:
            return
        if len(g.moves) >= 2:
            return
        update = abort_unstarted_game(game_id)
        if not update:
            return
        payload = {
            "type": "game_update",
            "fen": update["fen"],
            "white_remaining_ms": update["white_remaining_ms"],
            "black_remaining_ms": update["black_remaining_ms"],
            "result": update["result"],
            "result_reason": update.get("result_reason"),
            "result_detail": update.get("result_detail"),
            "draw_offer_by": update.get("draw_offer_by"),
            "draw_offer_color": update.get("draw_offer_color"),
        }
        await manager.send_to_user(g.white_id, payload)
        await manager.send_to_user(g.black_id, payload)
        await manager.send_to_user(g.white_id, {"type": "rematch_offer_available", "game_id": game_id})
        await manager.send_to_user(g.black_id, {"type": "rematch_offer_available", "game_id": game_id})
        _notify_game_finished_once(g, update.get("result_reason"), update.get("result_detail"))
    finally:
        _start_abort_tasks.pop(game_id, None)


def _start_unstarted_abort_timer(game_id: str) -> None:
    _cancel_start_abort_task(game_id)
    _start_abort_tasks[game_id] = asyncio.create_task(_schedule_unstarted_abort(game_id))


def _build_result_message(g, reason: str | None, detail: str | None) -> str:
    san_line = " ".join(m.san for m in (g.moves or []))
    result = g.result or "?"
    reason_txt = reason or "-"
    detail_txt = detail or "-"
    return (
        "Партия завершена.\n"
        f"Результат: {result}\n"
        f"Причина: {reason_txt}\n"
        f"Детали: {detail_txt}\n\n"
        f"Ходы: {san_line or '—'}"
    )


def _notify_game_finished_once(g, reason: str | None, detail: str | None) -> None:
    if not g or not g.id or g.id in _result_notified_games:
        return
    _result_notified_games.add(g.id)
    for uid in (g.white_id, g.black_id):
        tid, started = get_user_notification_target(uid)
        if started and tid:
            send_game_result_message(tid, _build_result_message(g, reason, detail))


def _schedule_bot_move(game_id: str) -> None:
    old = _bot_move_tasks.pop(game_id, None)
    if old:
        old.cancel()
    _bot_move_tasks[game_id] = asyncio.create_task(_run_bot_move(game_id))


async def _run_bot_move(game_id: str) -> None:
    try:
        await asyncio.sleep(1)
        g = get_game_any(game_id)
        if not g or g.result is not None or not g.is_bot_game or not g.bot_user_id:
            return
        board = chess.Board(g.fen)
        turn_uid = g.white_id if board.turn else g.black_id
        if turn_uid != g.bot_user_id:
            return
        uci = await pick_move_weak_uci(g.fen)
        if not uci:
            return
        mv = chess.Move.from_uci(uci)
        update = apply_move(game_id, g.bot_user_id, mv.uci()[:2], mv.uci()[2:4], mv.uci()[4:] if len(mv.uci()) > 4 else None, is_premove=False)
        if not update:
            return
        payload = {
            "type": "game_update",
            "fen": update["fen"],
            "white_remaining_ms": update["white_remaining_ms"],
            "black_remaining_ms": update["black_remaining_ms"],
            "san": update["san"],
            "move_time_ms": 1000,
            "result": update["result"],
            "result_reason": update.get("result_reason"),
            "result_detail": update.get("result_detail"),
            "draw_offer_by": update.get("draw_offer_by"),
            "draw_offer_color": update.get("draw_offer_color"),
            "from": update.get("from"),
            "to": update.get("to"),
        }
        await manager.send_to_user(g.white_id, payload)
        await manager.send_to_user(g.black_id, payload)
        if g.result is not None:
            _notify_game_finished_once(g, update.get("result_reason"), update.get("result_detail"))
            return
        if len(g.moves) >= 2:
            _cancel_start_abort_task(game_id)
    finally:
        _bot_move_tasks.pop(game_id, None)


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
        conn = manager.get_any_connection(user_id)
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
                "is_bot_game": bool(game.is_bot_game),
                "no_clock_user_id": game.no_clock_user_id,
            }
            white_payload = {**base, "color": "white"}
            black_payload = {**base, "color": "black"}
            sent_white = await manager.send_to_user(game.white_id, white_payload)
            sent_black = await manager.send_to_user(game.black_id, black_payload)
            # If one side didn't receive "matched", rollback this pairing.
            if not (sent_white and sent_black):
                abort_game_and_requeue(game.id)
            else:
                _start_unstarted_abort_timer(game.id)
        await manager.broadcast_queue_counts()
        return True
    if t == "start_bot_game":
        time_control = data.get("time_control") or "3+0"
        conn = manager.get_any_connection(user_id)
        if not conn:
            return True
        game = create_bot_game(time_control, user_id, conn.telegram_id, conn.username or "")
        if not game:
            return True
        color = "white" if game.white_id == user_id else "black"
        await manager.send_to_user(
            user_id,
            {
                "type": "matched",
                "game_id": game.id,
                "time_control": game.time_control_key,
                "fen": game.fen,
                "white_username": game.white_username,
                "black_username": game.black_username,
                "white_remaining_ms": game.white_remaining_ms,
                "black_remaining_ms": game.black_remaining_ms,
                "color": color,
                "is_bot_game": True,
                "no_clock_user_id": user_id,
            },
        )
        _start_unstarted_abort_timer(game.id)
        if game.bot_user_id and turn_user_id(game) == game.bot_user_id:
            _schedule_bot_move(game.id)
        return True
    if t == "create_private_invite":
        time_control = data.get("time_control")
        conn = manager.get_any_connection(user_id)
        if not conn:
            return True
        created = create_private_invite(time_control, user_id, conn.telegram_id, conn.username or "")
        if not created:
            await manager.send_to_user(user_id, {"type": "private_invite_invalid"})
            return True
        await manager.send_to_user(
            user_id,
            {
                "type": "private_invite_created",
                "invite_key": created["invite_key"],
                "invite_link": created["invite_link"],
                "time_control": created["time_control"],
            },
        )
        tid, started = get_user_notification_target(user_id)
        if started and tid:
            cfg = get_config()
            sep = "&" if "?" in cfg.telegram_webapp_url else "?"
            launch_url = f"{cfg.telegram_webapp_url}{sep}startapp=private_{created['invite_key']}"
            send_webapp_message(
                tid,
                f"Вы создали приватную игру ({created['time_control']}). Ссылка:\n{created['invite_link']}",
                launch_url,
            )
        return True
    if t == "open_private_link":
        invite_key = (data.get("invite_key") or "").strip()
        conn = manager.get_any_connection(user_id)
        if not invite_key or not conn:
            await manager.send_to_user(user_id, {"type": "private_invite_invalid"})
            return True
        logger.info("WS: open_private_link user_id=%s invite_key=%s", user_id, invite_key)
        opened = join_private_invite(invite_key, user_id, conn.telegram_id, conn.username or "")
        if not opened:
            logger.info("WS: open_private_link result user_id=%s invite_key=%s status=invalid_none", user_id, invite_key)
            await manager.send_to_user(user_id, {"type": "private_invite_invalid"})
            return True
        status = opened.get("status")
        logger.info("WS: open_private_link result user_id=%s invite_key=%s status=%s", user_id, invite_key, status)
        if status == "invalid":
            await manager.send_to_user(user_id, {"type": "private_invite_invalid"})
            return True
        if status == "taken":
            await manager.send_to_user(user_id, {"type": "private_invite_taken"})
            return True
        if status == "pending_wait":
            invite_key = opened.get("invite_key") or invite_key
            room_users = _private_room_presence.setdefault(invite_key, set())
            room_users.add(user_id)
            creator_id = opened.get("creator_user_id")
            invited_id = opened.get("invited_user_id")
            role = "creator" if user_id == creator_id else "guest"
            await manager.send_to_user(
                user_id,
                {
                    "type": "private_invite_waiting",
                    "invite_key": invite_key,
                    "time_control": opened.get("time_control"),
                    "role": role,
                    "has_opponent": bool(invited_id and invited_id != creator_id),
                },
            )
            if creator_id and invited_id and creator_id != invited_id:
                for uid in (creator_id, invited_id):
                    await manager.send_to_user(
                        uid,
                        {
                            "type": "private_invite_waiting",
                            "invite_key": invite_key,
                            "time_control": opened.get("time_control"),
                            "role": "creator" if uid == creator_id else "guest",
                            "has_opponent": True,
                        },
                    )
            if (
                creator_id
                and invited_id
                and creator_id != invited_id
                and manager.has_user(creator_id)
                and manager.has_user(invited_id)
                and creator_id in room_users
                and invited_id in room_users
            ):
                activated = activate_private_invite(invite_key)
                if activated and activated.get("status") in ("matched", "active"):
                    g = activated.get("game")
                    if g:
                        base = {
                            "type": "matched",
                            "game_id": g.id,
                            "time_control": g.time_control_key,
                            "fen": g.fen,
                            "white_username": g.white_username,
                            "black_username": g.black_username,
                            "white_remaining_ms": g.white_remaining_ms,
                            "black_remaining_ms": g.black_remaining_ms,
                            "is_bot_game": bool(g.is_bot_game),
                            "no_clock_user_id": g.no_clock_user_id,
                        }
                        await manager.send_to_user(g.white_id, {**base, "color": "white"})
                        await manager.send_to_user(g.black_id, {**base, "color": "black"})
                        _start_unstarted_abort_timer(g.id)
                        cfg = get_config()
                        link = f"https://t.me/{cfg.bot_username}?startapp=private_{invite_key}" if cfg.bot_username else f"{cfg.telegram_webapp_url}?startapp=private_{invite_key}"
                        for uid in (g.white_id, g.black_id):
                            tid, started = get_user_notification_target(uid)
                            if started and tid:
                                send_webapp_message(tid, f"Приватная игра создана. Ссылка:\n{link}", link)
            return True
        if status == "history":
            history = get_history_by_invite_key(invite_key)
            if not history:
                await manager.send_to_user(user_id, {"type": "private_invite_invalid"})
                return True
            await manager.send_to_user(user_id, {"type": "private_game_history", **history, "invite_key": invite_key})
            return True
        if status == "active":
            g = opened.get("game")
            if not g:
                await manager.send_to_user(user_id, {"type": "private_invite_invalid"})
                return True
            color = opened.get("color") or "white"
            await manager.send_to_user(
                user_id,
                {
                    "type": "matched",
                    "game_id": g.id,
                    "time_control": g.time_control_key,
                    "fen": g.fen,
                    "white_username": g.white_username,
                    "black_username": g.black_username,
                    "white_remaining_ms": g.white_remaining_ms,
                    "black_remaining_ms": g.black_remaining_ms,
                    "color": color,
                    "is_bot_game": bool(g.is_bot_game),
                    "no_clock_user_id": g.no_clock_user_id,
                },
            )
            return True
        g = opened.get("game")
        if not g:
            await manager.send_to_user(user_id, {"type": "private_invite_invalid"})
            return True
        base = {
            "type": "matched",
            "game_id": g.id,
            "time_control": g.time_control_key,
            "fen": g.fen,
            "white_username": g.white_username,
            "black_username": g.black_username,
            "white_remaining_ms": g.white_remaining_ms,
            "black_remaining_ms": g.black_remaining_ms,
            "is_bot_game": bool(g.is_bot_game),
            "no_clock_user_id": g.no_clock_user_id,
        }
        await manager.send_to_user(g.white_id, {**base, "color": "white"})
        await manager.send_to_user(g.black_id, {**base, "color": "black"})
        _start_unstarted_abort_timer(g.id)
        cfg = get_config()
        link = f"https://t.me/{cfg.bot_username}?startapp=private_{invite_key}" if cfg.bot_username else f"{cfg.telegram_webapp_url}?startapp=private_{invite_key}"
        for uid in (g.white_id, g.black_id):
            tid, started = get_user_notification_target(uid)
            if started and tid:
                send_webapp_message(tid, f"Приватная игра создана. Ссылка:\n{link}", link)
        return True
    if t == "ping":
        client_ts = data.get("client_ts")
        await manager.send_to_user(user_id, {"type": "pong", "client_ts": client_ts})
        return True
    if t == "open_game_history":
        game_id = (data.get("game_id") or "").strip()
        if not game_id:
            await manager.send_to_user(user_id, {"type": "private_invite_invalid"})
            return True
        history = get_history_by_game_id_for_user(game_id, user_id)
        if not history:
            await manager.send_to_user(user_id, {"type": "private_invite_invalid"})
            return True
        await manager.send_to_user(user_id, {"type": "private_game_history", **history, "invite_key": ""})
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
        is_premove = bool(data.get("premove"))
        g = get_game_for_user(game_id, user_id) if game_id else None
        if g and from_sq and to_sq:
            update = apply_move(game_id, user_id, from_sq, to_sq, promotion, is_premove=is_premove)
            if update:
                payload = {
                    "type": "game_update",
                    "fen": update["fen"],
                    "white_remaining_ms": update["white_remaining_ms"],
                    "black_remaining_ms": update["black_remaining_ms"],
                    "san": update["san"],
                    "move_time_ms": update["move_time_ms"],
                    "result": update["result"],
                    "result_reason": update.get("result_reason"),
                    "result_detail": update.get("result_detail"),
                    "draw_offer_by": update.get("draw_offer_by"),
                    "draw_offer_color": update.get("draw_offer_color"),
                    "from": update.get("from"),
                    "to": update.get("to"),
                }
                await manager.send_to_user(g.white_id, payload)
                await manager.send_to_user(g.black_id, payload)
                if len(g.moves) >= 2:
                    _cancel_start_abort_task(g.id)
                if g.result is None:
                    _maybe_start_disconnect_task(g, turn_user_id(g))
                    if g.is_bot_game and g.bot_user_id and turn_user_id(g) == g.bot_user_id:
                        _schedule_bot_move(g.id)
                else:
                    _notify_game_finished_once(g, update.get("result_reason"), update.get("result_detail"))
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
                    "result_reason": update.get("result_reason"),
                    "result_detail": update.get("result_detail"),
                    "draw_offer_by": update.get("draw_offer_by"),
                    "draw_offer_color": update.get("draw_offer_color"),
                }
                await manager.send_to_user(g.white_id, payload)
                await manager.send_to_user(g.black_id, payload)
                _notify_game_finished_once(g, update.get("result_reason"), update.get("result_detail"))
        return True
    if t == "offer_draw":
        game_id = data.get("game_id")
        g = get_game_for_user(game_id, user_id) if game_id else None
        if g:
            offer = offer_draw(game_id, user_id)
            if offer:
                payload = {
                    "type": "draw_offer_state",
                    "game_id": game_id,
                    "draw_offer_by": offer["draw_offer_by"],
                    "draw_offer_ply": offer["draw_offer_ply"],
                    "draw_offer_color": offer.get("draw_offer_color"),
                }
                await manager.send_to_user(g.white_id, payload)
                await manager.send_to_user(g.black_id, payload)
        return True
    if t == "respond_draw":
        game_id = data.get("game_id")
        action = data.get("action")
        g = get_game_for_user(game_id, user_id) if game_id else None
        if not g:
            return True
        if action == "accept":
            update = accept_draw_offer(game_id, user_id)
            if update:
                payload = {
                    "type": "game_update",
                    "fen": update["fen"],
                    "white_remaining_ms": update["white_remaining_ms"],
                    "black_remaining_ms": update["black_remaining_ms"],
                    "result": update["result"],
                    "result_reason": update.get("result_reason"),
                    "result_detail": update.get("result_detail"),
                    "draw_offer_by": update.get("draw_offer_by"),
                    "draw_offer_color": update.get("draw_offer_color"),
                }
                await manager.send_to_user(g.white_id, payload)
                await manager.send_to_user(g.black_id, payload)
        return True
    if t == "rematch_request":
        game_id = data.get("game_id")
        g = get_game_for_user(game_id, user_id) if game_id else None
        if not g or not g.is_private:
            return True
        votes = _rematch_votes.setdefault(game_id, set())
        votes.add(user_id)
        for uid in (g.white_id, g.black_id):
            await manager.send_to_user(
                uid,
                {
                    "type": "rematch_vote_update",
                    "game_id": game_id,
                    "voted_user_ids": list(votes),
                    "ready_count": len(votes),
                },
            )
        if g.white_id in votes and g.black_id in votes:
            new_game = create_private_rematch(game_id)
            _rematch_votes.pop(game_id, None)
            if new_game:
                base = {
                    "type": "matched",
                    "game_id": new_game.id,
                    "time_control": new_game.time_control_key,
                    "fen": new_game.fen,
                    "white_username": new_game.white_username,
                    "black_username": new_game.black_username,
                    "white_remaining_ms": new_game.white_remaining_ms,
                    "black_remaining_ms": new_game.black_remaining_ms,
                    "is_bot_game": False,
                    "no_clock_user_id": None,
                }
                await manager.send_to_user(new_game.white_id, {**base, "color": "white"})
                await manager.send_to_user(new_game.black_id, {**base, "color": "black"})
                _start_unstarted_abort_timer(new_game.id)
        return True
    if t == "claim_draw":
        game_id = data.get("game_id")
        claim_type = data.get("claim_type")
        g = get_game_for_user(game_id, user_id) if game_id else None
        if g and claim_type in ("threefold", "fifty_move"):
            update = claim_draw(game_id, user_id, claim_type)
            if update:
                payload = {
                    "type": "game_update",
                    "fen": update["fen"],
                    "white_remaining_ms": update["white_remaining_ms"],
                    "black_remaining_ms": update["black_remaining_ms"],
                    "result": update["result"],
                    "result_reason": update.get("result_reason"),
                    "result_detail": update.get("result_detail"),
                    "draw_offer_by": update.get("draw_offer_by"),
                    "draw_offer_color": update.get("draw_offer_color"),
                }
                await manager.send_to_user(g.white_id, payload)
                await manager.send_to_user(g.black_id, payload)
        return True
    return True


async def _schedule_disconnect_forfeit(game_id: str, disconnected_user_id: str) -> None:
    try:
        await asyncio.sleep(DISCONNECT_GRACE_SECONDS)
        g = get_game_for_user(game_id, disconnected_user_id)
        if not g or g.result is not None:
            return
        # Bot has no WebSocket; never treat it as a disconnected human.
        if g.is_bot_game and g.bot_user_id and disconnected_user_id == g.bot_user_id:
            return
        materialize_live_clocks(g)
        if g.result is not None:
            payload = {
                "type": "game_update",
                "fen": g.fen,
                "white_remaining_ms": g.white_remaining_ms,
                "black_remaining_ms": g.black_remaining_ms,
                "result": g.result,
                "result_reason": g.result_reason,
                "result_detail": g.result_detail,
                "draw_offer_by": g.draw_offer_by,
                "draw_offer_color": None,
            }
            await manager.send_to_user(g.white_id, payload)
            await manager.send_to_user(g.black_id, payload)
            _notify_game_finished_once(g, g.result_reason, g.result_detail)
            return
        # User returned in time.
        if manager.has_user(disconnected_user_id):
            return
        if turn_user_id(g) != disconnected_user_id:
            return
        update = forfeit_disconnected_player(game_id, disconnected_user_id)
        if not update:
            return
        update["result_reason"] = "disconnect_turn_timeout"
        update["result_detail"] = "Игрок не вернулся в течение 10 секунд после начала своего хода."
        payload = {
            "type": "game_update",
            "fen": update["fen"],
            "white_remaining_ms": update["white_remaining_ms"],
            "black_remaining_ms": update["black_remaining_ms"],
            "result": update["result"],
            "result_reason": update.get("result_reason"),
            "result_detail": update.get("result_detail"),
            "draw_offer_by": update.get("draw_offer_by"),
            "draw_offer_color": update.get("draw_offer_color"),
        }
        await manager.send_to_user(g.white_id, payload)
        await manager.send_to_user(g.black_id, payload)
        _notify_game_finished_once(g, update.get("result_reason"), update.get("result_detail"))
    finally:
        _disconnect_tasks.pop(disconnected_user_id, None)


def _cancel_disconnect_task(user_id: str) -> None:
    old = _disconnect_tasks.pop(user_id, None)
    if old:
        old.cancel()


def _maybe_start_disconnect_task(g, user_id: str) -> None:
    if not g or g.result is not None:
        return
    # After a human move it is the bot's turn; turn_user_id is the bot. The bot is never
    # "online" in manager, so we must not start a disconnect grace timer for it.
    if g.is_bot_game and g.bot_user_id and user_id == g.bot_user_id:
        return
    if manager.has_user(user_id):
        _cancel_disconnect_task(user_id)
        return
    if turn_user_id(g) != user_id:
        _cancel_disconnect_task(user_id)
        return
    if _disconnect_tasks.get(user_id):
        return
    _disconnect_tasks[user_id] = asyncio.create_task(_schedule_disconnect_forfeit(g.id, user_id))


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
        ensure_user_registered(user_id, telegram_id, username)
        if manager.has_user(user_id):
            logger.info("WS: reject second active client user_id=%s", user_id)
            await ws.close(code=4009, reason="another session is active; close previous tab")
            return
        await manager.connect(ws, user_id, telegram_id, username)
        # Reconnect inside active game: cancel forfeit timer and notify opponent.
        active = get_active_game_for_user(user_id)
        _cancel_disconnect_task(user_id)
        if active and active.result is None:
            opp_id = active.black_id if active.white_id == user_id else active.white_id
            await manager.send_to_user(
                opp_id,
                {
                    "type": "opponent_connection",
                    "game_id": active.id,
                    "status": "reconnected",
                    "user_id": user_id,
                },
            )
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
            for key in list(_private_room_presence.keys()):
                users = _private_room_presence.get(key) or set()
                if user_id in users:
                    users.discard(user_id)
                if not users:
                    _private_room_presence.pop(key, None)
            is_last = manager.disconnect(user_id, ws)
            if not is_last:
                logger.info("WS: user_id=%s still has active tabs", user_id)
                return
            active = get_active_game_for_user(user_id)
            if active and active.result is None:
                opp_id = active.black_id if active.white_id == user_id else active.white_id
                await manager.send_to_user(
                    opp_id,
                    {
                        "type": "opponent_connection",
                        "game_id": active.id,
                        "status": "disconnected",
                        "user_id": user_id,
                        "grace_seconds": DISCONNECT_GRACE_SECONDS,
                    },
                )
                _maybe_start_disconnect_task(active, user_id)
            leave_all_queues(user_id)
            await manager.broadcast_queue_counts()
            logger.info("WS: fully offline user_id=%s", user_id)
