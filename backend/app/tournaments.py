"""
Автотурниры: Swiss (интервал запуска) и KO classic (min 16, bo2 + tie-break).
Состояние активных турниров в памяти; завершённые — в БД.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import models
from .constants import TIME_CONTROL_KEYS
from .db import SessionLocal
from .pairing import Game, QueuedPlayer, create_tournament_game, get_active_game_for_user, get_game_any
from .ws_manager import manager

logger = logging.getLogger(__name__)

SWISS_MIN_PLAYERS = int(os.environ.get("SWISS_MIN_PLAYERS", "8"))
KO_MIN_PLAYERS = int(os.environ.get("KO_MIN_PLAYERS", "16"))
TOURNAMENT_INTERVAL_SEC = int(os.environ.get("TOURNAMENT_INTERVAL_SEC", "1800"))
SWISS_MAX_ROUNDS = int(os.environ.get("SWISS_MAX_ROUNDS", "5"))

_swiss_waiting: dict[str, list[QueuedPlayer]] = {k: [] for k in TIME_CONTROL_KEYS}
_ko_waiting: dict[str, list[QueuedPlayer]] = {k: [] for k in TIME_CONTROL_KEYS}

_runtimes: dict[str, Any] = {}
_lock = asyncio.Lock()


def _user_rating(user_id: str, tc: str) -> int:
    from .pairing import BLITZ_KEYS, RAPID_KEYS

    with SessionLocal() as db:
        u = db.get(models.User, user_id)
        if not u:
            return 1500
        if tc in BLITZ_KEYS:
            return int(u.blitz_rating or 1500)
        if tc in RAPID_KEYS:
            return int(u.rapid_rating or 1500)
    return 1500


def register_waiting(fmt: str, time_control_key: str, user_id: str, telegram_id: int, username: str) -> None:
    if time_control_key not in TIME_CONTROL_KEYS:
        return
    if get_active_game_for_user(user_id):
        return
    q = QueuedPlayer(user_id=user_id, telegram_id=telegram_id, username=username or f"user_{user_id[:8]}")
    room = _swiss_waiting if fmt == "swiss" else _ko_waiting
    if time_control_key not in room:
        room[time_control_key] = []
    lst = room[time_control_key]
    lst[:] = [p for p in lst if p.user_id != user_id]
    lst.append(q)


def leave_waiting(fmt: str, time_control_key: str, user_id: str) -> None:
    room = _swiss_waiting if fmt == "swiss" else _ko_waiting
    lst = room.get(time_control_key) or []
    room[time_control_key] = [p for p in lst if p.user_id != user_id]


def waiting_counts() -> dict[str, Any]:
    return {
        "swiss": {k: len(v) for k, v in _swiss_waiting.items()},
        "ko": {k: len(v) for k, v in _ko_waiting.items()},
    }


@dataclass
class SwissPlayer:
    user_id: str
    telegram_id: int
    username: str
    rating: int
    score: float = 0.0
    opponents: set[str] = field(default_factory=set)


@dataclass
class SwissMatch:
    id: str
    white_id: str
    black_id: str
    game_id: str | None = None


@dataclass
class SwissRuntime:
    t_id: str
    time_control_key: str
    players: dict[str, SwissPlayer]
    round_no: int = 1
    max_rounds: int = 3
    open_matches: dict[str, SwissMatch] = field(default_factory=dict)
    game_to_match: dict[str, str] = field(default_factory=dict)


def _pair_swiss(players: list[SwissPlayer]) -> list[tuple[str, str]]:
    ps = sorted(players, key=lambda p: (-p.score, -p.rating, p.user_id))
    pool = list(ps)
    pairs: list[tuple[str, str]] = []
    while len(pool) >= 2:
        a = pool.pop(0)
        opp_i = None
        for j, b in enumerate(pool):
            if b.user_id not in a.opponents:
                opp_i = j
                break
        if opp_i is None:
            opp_i = 0
        b = pool.pop(opp_i)
        a.opponents.add(b.user_id)
        b.opponents.add(a.user_id)
        pairs.append((a.user_id, b.user_id))
    return pairs


async def _broadcast_matched(g: Game) -> None:
    base = {
        "type": "matched",
        "game_id": g.id,
        "time_control": g.time_control_key,
        "fen": g.fen,
        "white_username": g.white_username,
        "black_username": g.black_username,
        "white_remaining_ms": g.white_remaining_ms,
        "black_remaining_ms": g.black_remaining_ms,
        "is_bot_game": False,
        "no_clock_user_id": g.no_clock_user_id,
        "tournament_id": g.tournament_id,
    }
    await manager.send_to_user(g.white_id, {**base, "color": "white"})
    await manager.send_to_user(g.black_id, {**base, "color": "black"})


async def _start_swiss_round(rt: SwissRuntime) -> None:
    plist = list(rt.players.values())
    pairs = _pair_swiss(plist)
    rt.open_matches.clear()
    rt.game_to_match.clear()
    for w_id, b_id in pairs:
        w = rt.players[w_id]
        b = rt.players[b_id]
        mid = str(uuid.uuid4())[:12]
        sm = SwissMatch(id=mid, white_id=w_id, black_id=b_id)
        rt.open_matches[mid] = sm
        g = create_tournament_game(
            rt.time_control_key,
            QueuedPlayer(w.user_id, w.telegram_id, w.username),
            QueuedPlayer(b.user_id, b.telegram_id, b.username),
            rt.t_id,
            mid,
        )
        sm.game_id = g.id
        rt.game_to_match[g.id] = mid
        await _broadcast_matched(g)


async def _finish_swiss(rt: SwissRuntime) -> None:
    plist = sorted(rt.players.values(), key=lambda p: (-p.score, -p.rating, p.user_id))
    for i, p in enumerate(plist):
        place = i + 1
        reward = place if place <= 3 else None
        _persist_participant(rt.t_id, p.user_id, float(p.score), place, reward)

    with SessionLocal() as db:
        tr = db.get(models.TournamentRecord, rt.t_id)
        if tr:
            tr.status = "finished"
            tr.finished_at = dt.datetime.utcnow()
            db.commit()
    del _runtimes[rt.t_id]
    payload = {"type": "tournament_finished", "tournament_id": rt.t_id, "format": "swiss"}
    for uid in rt.players:
        await manager.send_to_user(uid, payload)


def _persist_participant(tid: str, user_id: str, score: float, place: int, reward_rank: int | None) -> None:
    with SessionLocal() as db:
        db.add(
            models.TournamentParticipantRecord(
                tournament_id=tid,
                user_id=user_id,
                place=place,
                score=score,
                buchholz=0.0,
                reward_rank=reward_rank,
            )
        )
        db.commit()


async def _handle_swiss_game_finished(rt: SwissRuntime, g: Game) -> None:
    mid = rt.game_to_match.get(g.id)
    if not mid or mid not in rt.open_matches:
        return
    sm = rt.open_matches[mid]
    w = rt.players[sm.white_id]
    b = rt.players[sm.black_id]
    res = g.result or ""
    if res == "1-0":
        w.score += 1.0
    elif res == "0-1":
        b.score += 1.0
    else:
        w.score += 0.5
        b.score += 0.5
    del rt.open_matches[mid]

    if not rt.open_matches:
        rt.round_no += 1
        if rt.round_no > rt.max_rounds:
            await _finish_swiss(rt)
        else:
            await _start_swiss_round(rt)


@dataclass
class KoMatch:
    id: str
    round_idx: int
    slot_idx: int
    white_id: str
    black_id: str
    phase: int = 0
    games: list[str] = field(default_factory=list)
    w_pts: float = 0.0
    b_pts: float = 0.0
    white_seed_rank: int = 0
    black_seed_rank: int = 0


@dataclass
class KoRuntime:
    t_id: str
    time_control_key: str
    seeds: list[str]
    seed_order: dict[str, int]
    active: dict[str, KoMatch] = field(default_factory=dict)
    game_to_match: dict[str, str] = field(default_factory=dict)
    r16_winners: list[str | None] = field(default_factory=lambda: [None] * 8)
    qf_winners: list[str | None] = field(default_factory=lambda: [None] * 4)
    sf_winners: list[str | None] = field(default_factory=lambda: [None] * 2)
    sf_losers: list[str | None] = field(default_factory=lambda: [None] * 2)
    bronze_done: bool = False
    final_done: bool = False


def _ko_r16_pairs() -> list[tuple[int, int]]:
    return [(0, 15), (1, 14), (2, 13), (3, 12), (4, 11), (5, 10), (6, 9), (7, 8)]


async def _start_ko_g1(rt: KoRuntime, m: KoMatch) -> None:
    w = QueuedPlayer(m.white_id, 0, "")
    b = QueuedPlayer(m.black_id, 0, "")
    with SessionLocal() as db:
        uw = db.get(models.User, m.white_id)
        ub = db.get(models.User, m.black_id)
        if uw:
            w.telegram_id = int(uw.telegram_id)
            w.username = uw.username or w.username
        if ub:
            b.telegram_id = int(ub.telegram_id)
            b.username = ub.username or b.username
    g = create_tournament_game(rt.time_control_key, w, b, rt.t_id, m.id)
    m.games.append(g.id)
    m.phase = 0
    rt.game_to_match[g.id] = m.id
    rt.active[m.id] = m
    await _broadcast_matched(g)


async def _start_ko_g2(rt: KoRuntime, m: KoMatch) -> None:
    w = QueuedPlayer(m.black_id, 0, "")
    b = QueuedPlayer(m.white_id, 0, "")
    with SessionLocal() as db:
        uw = db.get(models.User, m.black_id)
        ub = db.get(models.User, m.white_id)
        if uw:
            w.telegram_id = int(uw.telegram_id)
            w.username = uw.username or w.username
        if ub:
            b.telegram_id = int(ub.telegram_id)
            b.username = ub.username or b.username
    g = create_tournament_game(rt.time_control_key, w, b, rt.t_id, m.id)
    m.games.append(g.id)
    m.phase = 1
    rt.game_to_match[g.id] = m.id
    await _broadcast_matched(g)


async def _start_ko_tb(rt: KoRuntime, m: KoMatch) -> None:
    ws = m.white_seed_rank
    bs = m.black_seed_rank
    if ws <= bs:
        first, second = m.white_id, m.black_id
        tw, tb = m.white_id, m.black_id
    else:
        first, second = m.black_id, m.white_id
        tw, tb = m.black_id, m.white_id
    w = QueuedPlayer(first, 0, "")
    b = QueuedPlayer(second, 0, "")
    with SessionLocal() as db:
        u1 = db.get(models.User, first)
        u2 = db.get(models.User, second)
        if u1:
            w.telegram_id = int(u1.telegram_id)
            w.username = u1.username or w.username
        if u2:
            b.telegram_id = int(u2.telegram_id)
            b.username = u2.username or b.username
    g = create_tournament_game(rt.time_control_key, w, b, rt.t_id, m.id)
    m.games.append(g.id)
    m.phase = 2
    rt.game_to_match[g.id] = m.id
    await _broadcast_matched(g)


def _result_points_for_white(res: str) -> tuple[float, float]:
    if res == "1-0":
        return (1.0, 0.0)
    if res == "0-1":
        return (0.0, 1.0)
    return (0.5, 0.5)


async def _ko_create_pair_match(rt: KoRuntime, round_idx: int, slot_idx: int, w1: str, w2: str) -> None:
    mid = str(uuid.uuid4())[:12]
    sr1 = rt.seed_order.get(w1, 99)
    sr2 = rt.seed_order.get(w2, 99)
    if sr1 <= sr2:
        wid, bid = w1, w2
        wr, br = sr1, sr2
    else:
        wid, bid = w2, w1
        wr, br = sr2, sr1
    m = KoMatch(
        id=mid,
        round_idx=round_idx,
        slot_idx=slot_idx,
        white_id=wid,
        black_id=bid,
        white_seed_rank=wr,
        black_seed_rank=br,
    )
    await _start_ko_g1(rt, m)


async def _ko_begin_qf(rt: KoRuntime) -> None:
    w8 = [rt.r16_winners[i] for i in range(8)]
    pairs = [(0, 1), (2, 3), (4, 5), (6, 7)]
    for slot, (a, b) in enumerate(pairs):
        await _ko_create_pair_match(rt, 1, slot, w8[a], w8[b])


async def _ko_begin_sf(rt: KoRuntime) -> None:
    w4 = [rt.qf_winners[i] for i in range(4)]
    await _ko_create_pair_match(rt, 2, 0, w4[0], w4[1])
    await _ko_create_pair_match(rt, 2, 1, w4[2], w4[3])


async def _ko_begin_finals(rt: KoRuntime) -> None:
    w0, w1 = rt.sf_winners[0], rt.sf_winners[1]
    l0, l1 = rt.sf_losers[0], rt.sf_losers[1]
    await _ko_create_pair_match(rt, 3, 0, w0, w1)
    await _ko_create_pair_match(rt, 4, 0, l0, l1)


async def _handle_ko_game_finished(rt: KoRuntime, g: Game) -> None:
    mid = rt.game_to_match.pop(g.id, None)
    if not mid:
        return
    m = rt.active.get(mid)
    if not m:
        return
    res = g.result or ""
    if m.phase == 0:
        pw, pb = _result_points_for_white(res)
        m.w_pts += pw
        m.b_pts += pb
        await _start_ko_g2(rt, m)
        return
    if m.phase == 1:
        pw, pb = _result_points_for_white(res)
        m.w_pts += pb
        m.b_pts += pw
        if m.w_pts == m.b_pts:
            await _start_ko_tb(rt, m)
            return
        await _finalize_ko_match(rt, m)
        return
    if m.phase == 2:
        await _finalize_ko_match(rt, m)


async def _finalize_ko_match(rt: KoRuntime, m: KoMatch) -> None:
    if m.id in rt.active:
        del rt.active[m.id]
    g = get_game_any(m.games[-1]) if m.games else None
    r = g.result if g else ""
    if m.phase == 2:
        win = m.white_id if r == "1-0" else m.black_id
    elif m.w_pts > m.b_pts:
        win = m.white_id
    elif m.b_pts > m.w_pts:
        win = m.black_id
    else:
        win = m.white_id if m.white_seed_rank <= m.black_seed_rank else m.black_id
    lose = m.black_id if win == m.white_id else m.white_id

    if m.round_idx == 0:
        rt.r16_winners[m.slot_idx] = win
        if all(x is not None for x in rt.r16_winners):
            await _ko_begin_qf(rt)
        return

    if m.round_idx == 1:
        rt.qf_winners[m.slot_idx] = win
        if all(x is not None for x in rt.qf_winners):
            await _ko_begin_sf(rt)
        return

    if m.round_idx == 2:
        rt.sf_winners[m.slot_idx] = win
        rt.sf_losers[m.slot_idx] = lose
        if all(x is not None for x in rt.sf_winners) and all(x is not None for x in rt.sf_losers):
            await _ko_begin_finals(rt)
        return

    if m.round_idx == 3:
        _persist_participant(rt.t_id, win, 3.0, 1, 1)
        _persist_participant(rt.t_id, lose, 2.0, 2, 2)
        rt.final_done = True
        await _ko_maybe_finish(rt)
        return
    if m.round_idx == 4:
        _persist_participant(rt.t_id, win, 1.0, 3, 3)
        rt.bronze_done = True
        await _ko_maybe_finish(rt)


async def _ko_maybe_finish(rt: KoRuntime) -> None:
    if not (rt.final_done and rt.bronze_done):
        return
    with SessionLocal() as db:
        tr = db.get(models.TournamentRecord, rt.t_id)
        if tr:
            tr.status = "finished"
            tr.finished_at = dt.datetime.utcnow()
            db.commit()
    del _runtimes[rt.t_id]
    for uid in rt.seeds:
        await manager.send_to_user(uid, {"type": "tournament_finished", "tournament_id": rt.t_id, "format": "ko"})


async def start_swiss_tournament(time_control_key: str, players: list[QueuedPlayer]) -> None:
    tid = str(uuid.uuid4())[:12]
    n = len(players)
    max_r = min(SWISS_MAX_ROUNDS, max(1, n - 1))
    plist: dict[str, SwissPlayer] = {}
    for p in players:
        plist[p.user_id] = SwissPlayer(
            p.user_id,
            p.telegram_id,
            p.username,
            _user_rating(p.user_id, time_control_key),
        )
    rt = SwissRuntime(t_id=tid, time_control_key=time_control_key, players=plist, round_no=1, max_rounds=max_r)
    _runtimes[tid] = rt
    with SessionLocal() as db:
        db.add(
            models.TournamentRecord(
                id=tid,
                format="swiss",
                time_control_key=time_control_key,
                status="active",
                min_players=n,
                swiss_rounds=max_r,
                started_at=dt.datetime.utcnow(),
            )
        )
        db.commit()
    await _start_swiss_round(rt)


async def start_ko_tournament(time_control_key: str, players: list[QueuedPlayer]) -> None:
    tid = str(uuid.uuid4())[:12]
    ranked = sorted(players, key=lambda p: -_user_rating(p.user_id, time_control_key))
    seeds = [p.user_id for p in ranked[:KO_MIN_PLAYERS]]
    order = {uid: i for i, uid in enumerate(seeds)}
    rt = KoRuntime(t_id=tid, time_control_key=time_control_key, seeds=seeds, seed_order=order)
    _runtimes[tid] = rt
    with SessionLocal() as db:
        db.add(
            models.TournamentRecord(
                id=tid,
                format="ko",
                time_control_key=time_control_key,
                status="active",
                min_players=KO_MIN_PLAYERS,
                swiss_rounds=0,
                started_at=dt.datetime.utcnow(),
            )
        )
        db.commit()
    pairs = _ko_r16_pairs()
    for slot, (a, b) in enumerate(pairs):
        w1, w2 = seeds[a], seeds[b]
        mid = str(uuid.uuid4())[:12]
        wr, br = order[w1], order[w2]
        if wr <= br:
            wid, bid = w1, w2
            srw, srb = wr, br
        else:
            wid, bid = w2, w1
            srw, srb = br, wr
        m = KoMatch(
            id=mid,
            round_idx=0,
            slot_idx=slot,
            white_id=wid,
            black_id=bid,
            white_seed_rank=srw,
            black_seed_rank=srb,
        )
        await _start_ko_g1(rt, m)


async def try_flush_waiting() -> None:
    async with _lock:
        for tc in TIME_CONTROL_KEYS:
            sw = _swiss_waiting.get(tc) or []
            if len(sw) >= SWISS_MIN_PLAYERS:
                chunk = sw[:SWISS_MIN_PLAYERS]
                _swiss_waiting[tc] = sw[SWISS_MIN_PLAYERS:]
                good = [p for p in chunk if not get_active_game_for_user(p.user_id)]
                if len(good) < SWISS_MIN_PLAYERS:
                    _swiss_waiting[tc] = good + (_swiss_waiting.get(tc) or [])
                    continue
                await start_swiss_tournament(tc, good[:SWISS_MIN_PLAYERS])
            ko = _ko_waiting.get(tc) or []
            if len(ko) >= KO_MIN_PLAYERS:
                chunk = ko[:KO_MIN_PLAYERS]
                _ko_waiting[tc] = ko[KO_MIN_PLAYERS:]
                good = [p for p in chunk if not get_active_game_for_user(p.user_id)]
                if len(good) < KO_MIN_PLAYERS:
                    _ko_waiting[tc] = good + (_ko_waiting.get(tc) or [])
                    continue
                await start_ko_tournament(tc, good[:KO_MIN_PLAYERS])


def schedule_on_game_finished(g: Game) -> None:
    if not g.tournament_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_handle_game_finished_async(g))


async def _handle_game_finished_async(g: Game) -> None:
    tid = g.tournament_id
    if not tid:
        return
    rt = _runtimes.get(tid)
    if not rt:
        return
    try:
        if isinstance(rt, SwissRuntime):
            await _handle_swiss_game_finished(rt, g)
        elif isinstance(rt, KoRuntime):
            await _handle_ko_game_finished(rt, g)
    except Exception:
        logger.exception("tournament handle failed tid=%s game=%s", tid, g.id)


async def scheduler_loop() -> None:
    while True:
        await asyncio.sleep(TOURNAMENT_INTERVAL_SEC)
        try:
            await try_flush_waiting()
        except Exception:
            logger.exception("tournament scheduler tick failed")


def user_tournament_history(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = (
            db.query(models.TournamentParticipantRecord)
            .filter(models.TournamentParticipantRecord.user_id == user_id)
            .order_by(models.TournamentParticipantRecord.id.desc())
            .limit(limit)
            .all()
        )
        out = []
        for r in rows:
            tr = db.get(models.TournamentRecord, r.tournament_id)
            out.append(
                {
                    "tournament_id": r.tournament_id,
                    "format": tr.format if tr else "?",
                    "time_control": tr.time_control_key if tr else "?",
                    "place": r.place,
                    "score": r.score,
                    "reward_rank": r.reward_rank,
                }
            )
        return out
