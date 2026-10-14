"""
UCI bot (Stockfish) с ограничением силы: UCI_LimitStrength + UCI_Elo.
Уровень «кампании» задаётся с клиента (1100…2900); применяется с учётом min/max опции движка.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from collections import OrderedDict

import chess
import chess.engine

from .config import get_config

logger = logging.getLogger(__name__)

# Separate Stockfish processes: replay analysis must never delay bot moves.
_PLAY = "play"
_ANALYSIS = "analysis"
_engines: dict[str, chess.engine.SimpleEngine] = {}
_engine_lock = threading.Lock()
_play_lock = asyncio.Lock()
_analysis_lock = asyncio.Lock()
_analysis_cache: "OrderedDict[str, tuple[float, dict[str, object]]]" = OrderedDict()
_ANALYSIS_TTL_SEC = 120.0
_ANALYSIS_CACHE_MAX = 5000


def _uci_elo_clamped(engine: chess.engine.SimpleEngine, requested: int) -> int:
    opt = engine.options.get("UCI_Elo")
    if opt is not None:
        mn = getattr(opt, "min", None)
        mx = getattr(opt, "max", None)
        if mn is not None and mx is not None:
            return max(int(mn), min(int(mx), int(requested)))
    return max(1320, min(3190, int(requested)))


def _ensure_engine(kind: str = _PLAY) -> chess.engine.SimpleEngine:
    with _engine_lock:
        eng = _engines.get(kind)
        if eng is not None:
            return eng
        cfg = get_config()
        path = (getattr(cfg, "stockfish_path", "") or "/usr/games/stockfish").strip()
        logger.info("UCI %s: starting engine path=%s", kind, path)
        eng = chess.engine.SimpleEngine.popen_uci(path)
        opts: dict[str, object] = {"Threads": 1, "Hash": 16}
        if kind == _PLAY:
            opts["UCI_LimitStrength"] = True
        for key, val in opts.items():
            try:
                if key in eng.options:
                    eng.configure({key: val})
            except Exception as e:
                logger.warning("UCI %s: option set failed %s=%s: %s", kind, key, val, e)
        _engines[kind] = eng
        return eng


def _drop_engine(kind: str) -> None:
    """Forget a (possibly dead) engine so the next call starts a fresh process."""
    with _engine_lock:
        eng = _engines.pop(kind, None)
    if eng is not None:
        try:
            eng.quit()
        except Exception:
            try:
                eng.close()
            except Exception:
                pass


def _think_time_sec_for_campaign_elo(campaign_elo: int) -> float:
    """Чуть больше времени на более сильный уровень (в пределах разумного для онлайна)."""
    e = float(max(1100, min(2900, campaign_elo)))
    return 0.02 + (e - 1100) / 2900.0 * 0.18


def _pick_move_blocking_at_elo(fen: str, campaign_elo: int) -> str | None:
    board = chess.Board(fen)
    if board.is_game_over():
        return None
    legal = list(board.legal_moves)
    if not legal:
        return None
    for attempt in range(2):
        try:
            engine = _ensure_engine(_PLAY)
            eff_elo = _uci_elo_clamped(engine, campaign_elo)
            try:
                engine.configure({"UCI_LimitStrength": True, "UCI_Elo": eff_elo})
            except chess.engine.EngineTerminatedError:
                raise
            except Exception as e:
                logger.warning("UCI bot: configure UCI_Elo failed: %s", e)
            t = _think_time_sec_for_campaign_elo(campaign_elo)
            result = engine.play(board, chess.engine.Limit(time=t))
            if result and result.move:
                return result.move.uci()
            break
        except Exception as e:
            # Dead/broken process: restart it once instead of playing fallback moves forever.
            logger.warning("UCI bot: play failed (attempt %d), restarting engine: %s", attempt + 1, e)
            _drop_engine(_PLAY)
    return random.choice(legal).uci()


async def pick_move_weak_uci(fen: str, campaign_elo: int = 1500) -> str | None:
    async with _play_lock:
        return await asyncio.to_thread(_pick_move_blocking_at_elo, fen, campaign_elo)


def _engine_multipv_cap(engine: chess.engine.SimpleEngine, want: int) -> int:
    want = max(1, min(3, want))
    opt = engine.options.get("MultiPV")
    if opt is None:
        return want
    mx = getattr(opt, "max", None)
    mn = getattr(opt, "min", None)
    if mx is not None:
        want = min(want, int(mx))
    if mn is not None:
        want = max(want, int(mn))
    return want


def _format_eval_white(score_obj: object | None) -> tuple[str, int]:
    if score_obj is None:
        return "cp", 0
    try:
        rel = score_obj.white()  # type: ignore[attr-defined]
        mate = rel.mate()
        if mate is not None:
            return "mate", int(mate)
        return "cp", int(rel.score(mate_score=100000) or 0)
    except Exception:
        return "cp", 0


def _pv_to_numbered_san(board: chess.Board, pv_moves: list[chess.Move]) -> tuple[str, int]:
    """SAN с номерами полных ходов (1. e4 e5 2. Nf3 ...) и число показанных полуходов."""
    parts: list[str] = []
    b = board.copy()
    played = 0
    for mv in pv_moves[:20]:
        if mv not in b.legal_moves:
            break
        if b.turn == chess.WHITE:
            parts.append(f"{b.fullmove_number}.")
        parts.append(b.san(mv))
        b.push(mv)
        played += 1
    return " ".join(parts), played


def _info_to_analysis_line(board: chess.Board, info: dict[str, object], line_no: int) -> dict[str, object] | None:
    pv_m = info.get("pv") or []
    pv_moves = [m for m in pv_m if isinstance(m, chess.Move)]
    if not pv_moves:
        return None
    score_type, score_val = _format_eval_white(info.get("score"))
    moves_text, plies_shown = _pv_to_numbered_san(board, pv_moves)
    return {
        "line": line_no,
        "score_type": score_type,
        "score": score_val,
        "san": moves_text,
        "plies": plies_shown,
    }


def _analyze_multipv_blocking(board: chess.Board, engine: chess.engine.SimpleEngine, lines_wanted: int) -> list[dict[str, object]]:
    cap = _engine_multipv_cap(engine, lines_wanted)
    limit = chess.engine.Limit(depth=14, time=0.42)
    by_mp: dict[int, dict[str, object]] = {}
    opt_mp = engine.options.get("MultiPV")
    prev_mp = int(getattr(opt_mp, "default", 1) or 1)
    try:
        if cap > 1 and "MultiPV" in engine.options:
            try:
                engine.configure({"MultiPV": cap})
            except Exception:
                pass
        try:
            with engine.analysis(board, limit, multipv=cap) as analysis:
                for info in analysis:
                    mp_i = info.get("multipv")
                    mp = int(mp_i) if mp_i is not None else 1
                    by_mp[mp] = info
        except Exception:
            raw = engine.analyse(board, limit, multipv=cap)
            items = raw if isinstance(raw, list) else [raw]
            by_mp = {}
            for idx, inf in enumerate(items[:cap], start=1):
                by_mp[idx] = inf if isinstance(inf, dict) else {}
    finally:
        if cap > 1 and "MultiPV" in engine.options:
            try:
                engine.configure({"MultiPV": prev_mp})
            except Exception:
                pass

    ordered: list[dict[str, object]] = []
    for mp_i in sorted(by_mp.keys()):
        inf = by_mp[mp_i]
        if not inf:
            continue
        ln = _info_to_analysis_line(board, inf, len(ordered) + 1)
        if ln:
            ordered.append(ln)
    return ordered


def _cache_put(fen: str, now: float, payload: dict[str, object]) -> None:
    _analysis_cache[fen] = (now, payload)
    _analysis_cache.move_to_end(fen)
    while len(_analysis_cache) > _ANALYSIS_CACHE_MAX:
        _analysis_cache.popitem(last=False)


def _analyze_fen_blocking(fen: str) -> dict[str, object]:
    try:
        return _analyze_fen_once(fen)
    except (chess.engine.EngineTerminatedError, chess.engine.EngineError, BrokenPipeError, OSError) as e:
        logger.warning("UCI analysis: engine failure, restarting: %s", e)
        _drop_engine(_ANALYSIS)
        return _analyze_fen_once(fen)


def _analyze_fen_once(fen: str) -> dict[str, object]:
    now = time.monotonic()
    cached = _analysis_cache.get(fen)
    if cached and (now - cached[0]) < _ANALYSIS_TTL_SEC:
        _analysis_cache.move_to_end(fen)
        return cached[1]
    board = chess.Board(fen)
    if board.is_game_over():
        payload = {"lines": [], "fen": fen, "score_type": "cp", "score": 0, "pv": []}
        _cache_put(fen, now, payload)
        return payload
    engine = _ensure_engine(_ANALYSIS)
    lines_payload: list[dict[str, object]] = []
    try:
        lines_payload = _analyze_multipv_blocking(board, engine, 3)
    except chess.engine.EngineTerminatedError:
        raise
    except Exception as e:
        logger.warning("UCI analyse multipv failed, fallback single: %s", e)

    if not lines_payload:
        info = engine.analyse(board, chess.engine.Limit(depth=12, time=0.2))
        if isinstance(info, list):
            info = info[0] if info else {}
        ln = _info_to_analysis_line(board, info, 1)
        lines_payload = [ln] if ln else []

    first = lines_payload[0] if lines_payload else None
    if isinstance(first, dict):
        st = str(first.get("score_type", "cp") or "cp")
        sc = int(first.get("score", 0) or 0)
    else:
        st = "cp"
        sc = 0
    payload: dict[str, object] = {
        "lines": lines_payload,
        "fen": fen,
        "score_type": st,
        "score": sc,
        "pv": [],
    }
    _cache_put(fen, now, payload)
    return payload


async def analyze_fen_light(fen: str) -> dict[str, object]:
    async with _analysis_lock:
        return await asyncio.to_thread(_analyze_fen_blocking, fen)


def shutdown_uci_bot() -> None:
    for kind in (_PLAY, _ANALYSIS):
        _drop_engine(kind)
    _analysis_cache.clear()
