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
        self._by_user: dict[str, list[Connection]] = {}
        self._all: list[Connection] = []

    async def connect(
        self,
        ws: WebSocket,
        user_id: str,
        telegram_id: int,
        username: str,
    ) -> None:
        conn = Connection(ws, user_id, telegram_id, username)
        self._by_user.setdefault(user_id, []).append(conn)
        self._all.append(conn)
        logger.info("WS: connect user_id=%s (conns=%d total=%d)", user_id, len(self._by_user[user_id]), len(self._all))

    def disconnect(self, user_id: str, ws: WebSocket | None = None) -> bool:
        """
        Disconnect connection(s) for user.
        Returns True if user has no active connections left.
        """
        conns = self._by_user.get(user_id)
        if not conns:
            return True
        removed: list[Connection] = []
        if ws is None:
            removed = list(conns)
            self._by_user.pop(user_id, None)
        else:
            for c in conns:
                if c.ws is ws:
                    removed.append(c)
                    break
            if removed:
                conns.remove(removed[0])
            if not conns:
                self._by_user.pop(user_id, None)
        for c in removed:
            if c in self._all:
                self._all.remove(c)
        remaining = len(self._by_user.get(user_id, []))
        logger.info("WS: disconnect user_id=%s removed=%d remaining_user=%d total=%d", user_id, len(removed), remaining, len(self._all))
        return remaining == 0

    def has_user(self, user_id: str) -> bool:
        conns = self._by_user.get(user_id)
        return bool(conns)

    def get_any_connection(self, user_id: str) -> Connection | None:
        conns = self._by_user.get(user_id)
        if not conns:
            return None
        return conns[0]

    async def send_to_user(self, user_id: str, payload: dict[str, Any]) -> bool:
        conns = list(self._by_user.get(user_id, []))
        if not conns:
            return False
        sent = False
        for conn in conns:
            try:
                await conn.ws.send_json(payload)
                sent = True
            except Exception as e:
                logger.warning("send_to_user %s: %s", user_id, e)
                self.disconnect(user_id, conn.ws)
        return sent

    async def broadcast_queue_counts(self) -> None:
        counts = get_queue_counts()
        try:
            from .tournaments import waiting_counts

            tw = waiting_counts()
        except Exception:
            tw = {"swiss": {}, "ko": {}}
        msg = {"type": "queue_counts", "counts": counts, "tournament_waiting": tw}
        await self._broadcast(msg)

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        dead = []
        for conn in self._all:
            try:
                await conn.ws.send_json(payload)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn.user_id, conn.ws)


manager = WSManager()
