"""
Weak UCI bot worker (Stockfish Skill 0).
"""
from __future__ import annotations

import asyncio
import logging
import threading

import chess
import chess.engine

from .config import get_config

logger = logging.getLogger(__name__)

_engine: chess.engine.SimpleEngine | None = None
_engine_lock = threading.Lock()
_play_lock = asyncio.Lock()


def _ensure_engine() -> chess.engine.SimpleEngine:
    global _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        cfg = get_config()
        path = (getattr(cfg, "stockfish_path", "") or "/usr/games/stockfish").strip()
        logger.info("UCI bot: starting engine path=%s", path)
        _engine = chess.engine.SimpleEngine.popen_uci(path)
        opts: dict[str, object] = {"Skill Level": 0, "UCI_LimitStrength": True, "UCI_Elo": 1320, "Threads": 1, "Hash": 16}
        for key, val in opts.items():
            try:
                if key in _engine.options:
                    _engine.configure({key: val})
            except Exception as e:
                logger.warning("UCI bot: option set failed %s=%s: %s", key, val, e)
        return _engine


def _pick_move_blocking(fen: str) -> str | None:
    board = chess.Board(fen)
    if board.is_game_over():
        return None
    legal = list(board.legal_moves)
    if not legal:
        return None
    try:
        engine = _ensure_engine()
        result = engine.play(board, chess.engine.Limit(time=0.01))
        if result and result.move:
            return result.move.uci()
    except Exception as e:
        logger.warning("UCI bot: play failed, using fallback move: %s", e)
    return legal[0].uci()


async def pick_move_weak_uci(fen: str) -> str | None:
    async with _play_lock:
        return await asyncio.to_thread(_pick_move_blocking, fen)


def shutdown_uci_bot() -> None:
    global _engine
    with _engine_lock:
        if _engine is None:
            return
        try:
            _engine.quit()
        except Exception:
            pass
        _engine = None
