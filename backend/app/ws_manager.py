"""
Менеджер WebSocket: подключения по user_id, рассылка очередей и событий игры.
"""
import json
import logging
from typing import Any

from fastapi import WebSocket

from .constants import TIME_CONTROL_KEYS
from .pairing import get_queue_counts

logger = logging.getLogger(__name__)


class Connection:
    def __init__(self, ws: WebSocket, user_id: str, telegram_id: int, username: str):
        self.ws = ws
        self.user_id = user_id
        self.telegram_id = telegram_id
        self.username = username


class WSManager:
    def __init__(self):
        self._by_user: dict[str, Connection] = {}
        self._all: list[Connection] = []

    async def connect(
        self,
        ws: WebSocket,
        user_id: str,
        telegram_id: int,
        username: str,
    ) -> None:
        if user_id in self._by_user:
            old = self._by_user[user_id]
            self._all.remove(old)
            try:
                await old.ws.close(code=4000)
            except Exception:
                pass
        conn = Connection(ws, user_id, telegram_id, username)
        self._by_user[user_id] = conn
        self._all.append(conn)

    def disconnect(self, user_id: str) -> None:
        if user_id in self._by_user:
            conn = self._by_user.pop(user_id)
            if conn in self._all:
                self._all.remove(conn)

    async def send_to_user(self, user_id: str, payload: dict[str, Any]) -> bool:
        conn = self._by_user.get(user_id)
        if not conn:
            return False
        try:
            await conn.ws.send_json(payload)
            return True
        except Exception as e:
            logger.warning("send_to_user %s: %s", user_id, e)
            return False

    async def broadcast_queue_counts(self) -> None:
        counts = get_queue_counts()
        msg = {"type": "queue_counts", "counts": counts}
        await self._broadcast(msg)

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        dead = []
        for conn in self._all:
            try:
                await conn.ws.send_json(payload)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn.user_id)


manager = WSManager()
