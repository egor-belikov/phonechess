"""
Weak UCI bot worker (Stockfish Skill 0).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

import chess
import chess.engine

from .config import get_config

logger = logging.getLogger(__name__)

_engine: chess.engine.SimpleEngine | None = None
_engine_lock = threading.Lock()
_play_lock = asyncio.Lock()
_analysis_cache: dict[str, tuple[float, dict[str, object]]] = {}
_ANALYSIS_TTL_SEC = 120.0


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


def _analyze_fen_blocking(fen: str) -> dict[str, object]:
    now = time.monotonic()
    cached = _analysis_cache.get(fen)
    if cached and (now - cached[0]) < _ANALYSIS_TTL_SEC:
        return cached[1]
    board = chess.Board(fen)
    if board.is_game_over():
        payload = {"score_type": "cp", "score": 0, "pv": []}
        _analysis_cache[fen] = (now, payload)
        return payload
    engine = _ensure_engine()
    info = engine.analyse(board, chess.engine.Limit(depth=8, time=0.05))
    score_obj = info.get("score")
    score_cp = 0
    score_type = "cp"
    if score_obj is not None:
        rel = score_obj.white()
        mate = rel.mate()
        if mate is not None:
            score_type = "mate"
            score_cp = int(mate)
        else:
            score_type = "cp"
            score_cp = int(rel.score(mate_score=100000) or 0)
    pv = [m.uci() for m in (info.get("pv") or [])[:10]]
    payload = {"score_type": score_type, "score": score_cp, "pv": pv}
    _analysis_cache[fen] = (now, payload)
    return payload


async def analyze_fen_light(fen: str) -> dict[str, object]:
    async with _play_lock:
        return await asyncio.to_thread(_analyze_fen_blocking, fen)


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
    _analysis_cache.clear()
