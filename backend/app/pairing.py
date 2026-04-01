"""
Очереди пейринга и создание партий (in-memory).
Этап 2: часы, ходы, валидация через python-chess.
"""
import random
import time
import uuid
import secrets
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

import chess
from chess import Board

from .constants import TIME_CONTROL_KEYS, TIME_CONTROLS, TimeControl
from .db import SessionLocal
from .models import GameMoveRecord, GameRecord, PrivateInviteRecord, User
from .config import get_config


@dataclass
class QueuedPlayer:
    user_id: str
    telegram_id: int
    username: str


@dataclass
class MoveRecord:
    san: str
    time_ms: int  # время на ход в миллисекундах


@dataclass
class Game:
    id: str
    time_control_key: str
    white_id: str
    black_id: str
    white_username: str
    black_username: str
    white_telegram_id: int
    black_telegram_id: int
    fen: str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    moves: list[MoveRecord] = field(default_factory=list)
    is_private: bool = False
    is_bot_game: bool = False
    bot_user_id: str | None = None
    human_user_id: str | None = None
    no_clock_user_id: str | None = None
    white_clock_started: bool = False
    black_clock_started: bool = False
    white_remaining_ms: int = 0
    black_remaining_ms: int = 0
    last_clock_at: float = 0.0  # unix timestamp когда часы последний раз обновлялись
    result: str | None = None  # None | "1-0" | "0-1" | "1/2-1/2"
    result_reason: str | None = None
    result_detail: str | None = None
    draw_offer_by: str | None = None
    draw_offer_ply: int | None = None
    white_last_draw_offer_ply: int | None = None
    black_last_draw_offer_ply: int | None = None
    tournament_id: str | None = None
    tournament_match_id: str | None = None

    @property
    def time_control(self) -> TimeControl:
        for tc in TIME_CONTROLS:
            if tc["key"] == self.time_control_key:
                return tc
        return TIME_CONTROLS[0]

    def _init_clocks(self) -> None:
        tc = self.time_control
        self.white_remaining_ms = tc["initial_seconds"] * 1000
        self.black_remaining_ms = tc["initial_seconds"] * 1000
        self.last_clock_at = time.monotonic()


# Глобальное состояние (in-memory)
_queues: dict[str, list[QueuedPlayer]] = defaultdict(list)
_games: dict[str, Game] = {}
_private_invites_mem: dict[str, str] = {}
BOT_USER_ID = "__bot_weak__"

BLITZ_KEYS = {"3+0", "3+2", "5+0", "5+3"}


def _side_clock_runs(g: Game, side_user_id: str) -> bool:
    """Whether this side's clock counts down. Bot games are untimed for both players."""
    if g.is_bot_game:
        return False
    if g.no_clock_user_id and side_user_id == g.no_clock_user_id:
        return False
    return True
RAPID_KEYS = {"10+0", "15+10"}


def _upsert_user(user_id: str, telegram_id: int, username: str, has_started_bot: bool | None = None) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        now = dt.datetime.utcnow()
        if not user:
            user = User(
                id=user_id,
                telegram_id=telegram_id,
                username=username or "",
                login_name=None,
                is_anonymous=True,
                blitz_rating=1500,
                rapid_rating=1500,
                games_played=0,
                has_started_bot=bool(has_started_bot),
                created_at=now,
                updated_at=now,
            )
            db.add(user)
        else:
            user.telegram_id = telegram_id
            user.username = username or user.username or ""
            if user.blitz_rating is None or int(user.blitz_rating) <= 0:
                user.blitz_rating = 1500
            if user.rapid_rating is None or int(user.rapid_rating) <= 0:
                user.rapid_rating = 1500
            if has_started_bot is not None:
                user.has_started_bot = has_started_bot
            user.updated_at = now
        db.commit()


def _expected_score(r_a: int, r_b: int) -> float:
    return 1.0 / (1.0 + pow(10.0, (r_b - r_a) / 400.0))


def _score_from_result(result: str, is_white: bool) -> float:
    if result == "1-0":
        return 1.0 if is_white else 0.0
    if result == "0-1":
        return 0.0 if is_white else 1.0
    return 0.5


def _apply_finished_game_ratings(g: Game) -> None:
    if not g.result:
        return
    if g.tournament_id:
        return
    if g.time_control_key in BLITZ_KEYS:
        field = "blitz_rating"
    elif g.time_control_key in RAPID_KEYS:
        field = "rapid_rating"
    else:
        return
    with SessionLocal() as db:
        w = db.get(User, g.white_id)
        b = db.get(User, g.black_id)
        if not w or not b:
            return
        r_w = int(getattr(w, field) or 1500)
        r_b = int(getattr(b, field) or 1500)
        e_w = _expected_score(r_w, r_b)
        e_b = _expected_score(r_b, r_w)
        s_w = _score_from_result(g.result, True)
        s_b = _score_from_result(g.result, False)
        k = 20
        setattr(w, field, max(100, int(round(r_w + k * (s_w - e_w)))))
        setattr(b, field, max(100, int(round(r_b + k * (s_b - e_b)))))
        w.games_played = int(w.games_played or 0) + 1
        b.games_played = int(b.games_played or 0) + 1
        db.commit()


def mark_user_started_bot(telegram_id: int, username: str = "") -> None:
    user_id = str(telegram_id)
    _upsert_user(user_id, telegram_id, username, has_started_bot=True)


def ensure_user_registered(user_id: str, telegram_id: int, username: str) -> None:
    _upsert_user(user_id, telegram_id, username)


def _persist_game_created(g: Game) -> None:
    with SessionLocal() as db:
        rec = GameRecord(
            id=g.id,
            time_control_key=g.time_control_key,
            white_id=g.white_id,
            black_id=g.black_id,
            white_username=g.white_username,
            black_username=g.black_username,
            fen=g.fen,
            white_remaining_ms=g.white_remaining_ms,
            black_remaining_ms=g.black_remaining_ms,
            result=g.result,
            result_reason=g.result_reason,
            result_detail=g.result_detail,
            created_at=dt.datetime.utcnow(),
            finished_at=dt.datetime.utcnow() if g.result else None,
        )
        db.add(rec)
        db.commit()


def _persist_game_state(g: Game, from_sq: str | None = None, to_sq: str | None = None, promotion: str | None = None, san: str | None = None, move_time_ms: int | None = None) -> None:
    with SessionLocal() as db:
        rec = db.get(GameRecord, g.id)
        if not rec:
            rec = GameRecord(
                id=g.id,
                time_control_key=g.time_control_key,
                white_id=g.white_id,
                black_id=g.black_id,
                white_username=g.white_username,
                black_username=g.black_username,
                fen=g.fen,
                white_remaining_ms=g.white_remaining_ms,
                black_remaining_ms=g.black_remaining_ms,
                result=g.result,
                result_reason=g.result_reason,
                result_detail=g.result_detail,
                created_at=dt.datetime.utcnow(),
                finished_at=dt.datetime.utcnow() if g.result else None,
            )
            db.add(rec)
            db.flush()
        rec.fen = g.fen
        rec.white_remaining_ms = g.white_remaining_ms
        rec.black_remaining_ms = g.black_remaining_ms
        rec.result = g.result
        rec.result_reason = g.result_reason
        rec.result_detail = g.result_detail
        if g.result and rec.finished_at is None:
            rec.finished_at = dt.datetime.utcnow()
        if san and from_sq and to_sq and move_time_ms is not None:
            db.add(
                GameMoveRecord(
                    game_id=g.id,
                    ply=len(g.moves),
                    san=san,
                    uci_from=from_sq,
                    uci_to=to_sq,
                    promotion=promotion,
                    move_time_ms=move_time_ms,
                    fen_after=g.fen,
                    created_at=dt.datetime.utcnow(),
                )
            )
        db.commit()


def _maybe_tournament_hook(g: Game) -> None:
    if not g.tournament_id or g.result is None:
        return
    from . import tournaments as trn

    trn.schedule_on_game_finished(g)


def get_queue_counts() -> dict[str, int]:
    """Количество ожидающих по каждому режиму."""
    return {key: len(_queues[key]) for key in TIME_CONTROL_KEYS}


def join_queue(time_control_key: str, user_id: str, telegram_id: int, username: str) -> Game | None:
    """
    Добавить в очередь или сразу создать партию, если есть ждущий.
    Возвращает Game если пара найдена, иначе None.
    """
    if time_control_key not in TIME_CONTROL_KEYS:
        return None
    _upsert_user(user_id, telegram_id, username)
    queue = _queues[time_control_key]
    # Prevent duplicate queue entries for the same user.
    for p in queue:
        if p.user_id == user_id:
            return None
    player = QueuedPlayer(user_id=user_id, telegram_id=telegram_id, username=username)
    if queue:
        # Match only against another user (never self-match).
        opponent_idx = next((i for i, p in enumerate(queue) if p.user_id != user_id), -1)
        if opponent_idx == -1:
            queue.append(player)
            return None
        opponent = queue.pop(opponent_idx)
        if random.random() < 0.5:
            game = _create_game(time_control_key, player, opponent)
        else:
            game = _create_game(time_control_key, opponent, player)
        _games[game.id] = game
        _persist_game_created(game)
        return game
    queue.append(player)
    return None


def leave_queue(time_control_key: str, user_id: str) -> bool:
    """Убрать из очереди. Возвращает True если был в очереди."""
    queue = _queues.get(time_control_key, [])
    for i, p in enumerate(queue):
        if p.user_id == user_id:
            queue.pop(i)
            return True
    return False


def leave_all_queues(user_id: str) -> None:
    """Убрать пользователя из всех очередей."""
    for key in TIME_CONTROL_KEYS:
        leave_queue(key, user_id)


def _create_game(time_control_key: str, white: QueuedPlayer, black: QueuedPlayer) -> Game:
    g = Game(
        id=str(uuid.uuid4()),
        time_control_key=time_control_key,
        white_id=white.user_id,
        black_id=black.user_id,
        white_username=white.username or f"user_{white.user_id[:8]}",
        black_username=black.username or f"user_{black.user_id[:8]}",
        white_telegram_id=white.telegram_id,
        black_telegram_id=black.telegram_id,
    )
    g._init_clocks()
    g.white_clock_started = False
    g.black_clock_started = False
    return g


def create_bot_game(time_control_key: str, user_id: str, telegram_id: int, username: str) -> Game | None:
    if time_control_key not in TIME_CONTROL_KEYS:
        return None
    _upsert_user(user_id, telegram_id, username)
    human = QueuedPlayer(user_id=user_id, telegram_id=telegram_id, username=username or f"user_{user_id[:8]}")
    bot = QueuedPlayer(user_id=BOT_USER_ID, telegram_id=0, username="Weak Bot")
    if random.random() < 0.5:
        g = _create_game(time_control_key, human, bot)
        g.human_user_id = human.user_id
        g.bot_user_id = bot.user_id
    else:
        g = _create_game(time_control_key, bot, human)
        g.human_user_id = human.user_id
        g.bot_user_id = bot.user_id
    g.is_bot_game = True
    g.no_clock_user_id = None
    _games[g.id] = g
    return g


def get_game_any(game_id: str) -> Game | None:
    return _games.get(game_id)


def create_tournament_game(
    time_control_key: str,
    white: QueuedPlayer,
    black: QueuedPlayer,
    tournament_id: str,
    tournament_match_id: str,
) -> Game:
    g = _create_game(time_control_key, white, black)
    g.tournament_id = tournament_id
    g.tournament_match_id = tournament_match_id
    _games[g.id] = g
    _persist_game_created(g)
    return g


def create_private_rematch(game_id: str) -> Game | None:
    prev = _games.get(game_id)
    if not prev:
        return None
    white = QueuedPlayer(prev.black_id, prev.black_telegram_id, prev.black_username)
    black = QueuedPlayer(prev.white_id, prev.white_telegram_id, prev.white_username)
    g = _create_game(prev.time_control_key, white, black)
    g.is_private = True
    _games[g.id] = g
    _persist_game_created(g)
    return g


def abort_game_and_requeue(game_id: str) -> bool:
    """
    Cancel created game and return both players to the queue.
    Used when one of players didn't receive matched event.
    """
    g = _games.pop(game_id, None)
    if not g:
        return False
    q = _queues[g.time_control_key]
    # Put players back to front so they can be matched again quickly.
    q.insert(0, QueuedPlayer(g.black_id, g.black_telegram_id, g.black_username))
    q.insert(0, QueuedPlayer(g.white_id, g.white_telegram_id, g.white_username))
    return True


def get_game(game_id: str) -> Game | None:
    return _games.get(game_id)


def create_private_invite(time_control_key: str, user_id: str, telegram_id: int, username: str) -> dict | None:
    if time_control_key not in TIME_CONTROL_KEYS:
        return None
    _upsert_user(user_id, telegram_id, username)
    key = secrets.token_urlsafe(12).replace("-", "").replace("_", "")
    key = key[:20]
    cfg = get_config()
    link = f"https://t.me/{cfg.bot_username}?start=private_{key}" if getattr(cfg, "bot_username", "") else f"{cfg.telegram_webapp_url}?startapp=private_{key}"
    _private_invites_mem[key] = ""
    with SessionLocal() as db:
        db.add(
            PrivateInviteRecord(
                invite_key=key,
                creator_user_id=user_id,
                invited_user_id=None,
                time_control_key=time_control_key,
                game_id=None,
                status="pending",
                created_at=dt.datetime.utcnow(),
                used_at=None,
            )
        )
        db.commit()
    return {"invite_key": key, "invite_link": link, "time_control": time_control_key}


def join_private_invite(invite_key: str, user_id: str, telegram_id: int, username: str) -> dict | None:
    _upsert_user(user_id, telegram_id, username)
    with SessionLocal() as db:
        inv = db.get(PrivateInviteRecord, invite_key)
        if not inv:
            return {"status": "invalid"}
        if inv.status == "finished":
            return {"status": "history", "game_id": inv.game_id}
        if inv.status == "active" and inv.game_id:
            g = get_game(inv.game_id)
            if g:
                color = "white" if g.white_id == user_id else ("black" if g.black_id == user_id else None)
                return {"status": "active", "game": g, "color": color}
            hist = get_history_by_invite_key(invite_key)
            if hist:
                return {"status": "history", "game_id": inv.game_id}
        if inv.status != "pending":
            return {"status": "taken"}
        if inv.creator_user_id == user_id:
            return {
                "status": "pending_wait",
                "invite_key": invite_key,
                "creator_user_id": inv.creator_user_id,
                "invited_user_id": inv.invited_user_id,
                "time_control": inv.time_control_key,
            }
        if inv.invited_user_id and inv.invited_user_id != user_id:
            return {"status": "taken"}
        if not inv.invited_user_id:
            inv.invited_user_id = user_id
            inv.used_at = dt.datetime.utcnow()
            db.commit()
        return {
            "status": "pending_wait",
            "invite_key": invite_key,
            "creator_user_id": inv.creator_user_id,
            "invited_user_id": inv.invited_user_id,
            "time_control": inv.time_control_key,
        }


def activate_private_invite(invite_key: str) -> dict | None:
    with SessionLocal() as db:
        inv = db.get(PrivateInviteRecord, invite_key)
        if not inv:
            return None
        if inv.status == "active" and inv.game_id:
            g = get_game(inv.game_id)
            if g:
                return {"status": "active", "game": g}
            return None
        if inv.status != "pending":
            return None
        if not inv.invited_user_id or inv.invited_user_id == inv.creator_user_id:
            return None
        owner_user = db.get(User, inv.creator_user_id)
        guest_user = db.get(User, inv.invited_user_id)
        creator_username = owner_user.username if owner_user else ""
        creator_tid = owner_user.telegram_id if owner_user else 0
        guest_username = guest_user.username if guest_user else ""
        guest_tid = guest_user.telegram_id if guest_user else 0
        owner = QueuedPlayer(
            user_id=inv.creator_user_id,
            telegram_id=creator_tid,
            username=creator_username or f"user_{inv.creator_user_id[:8]}",
        )
        opener = QueuedPlayer(
            user_id=inv.invited_user_id,
            telegram_id=guest_tid,
            username=guest_username or f"user_{inv.invited_user_id[:8]}",
        )
        game = _create_game(inv.time_control_key, owner, opener)
        game.is_private = True
        _games[game.id] = game
        _persist_game_created(game)
        inv.status = "active"
        inv.game_id = game.id
        if inv.used_at is None:
            inv.used_at = dt.datetime.utcnow()
        db.commit()
        _private_invites_mem[invite_key] = game.id
        return {"status": "matched", "game": game, "invite_key": invite_key}


def mark_invite_finished_by_game(game_id: str) -> None:
    with SessionLocal() as db:
        inv = db.query(PrivateInviteRecord).filter(PrivateInviteRecord.game_id == game_id).first()
        if not inv:
            return
        inv.status = "finished"
        db.commit()


def get_history_by_game_id_for_user(game_id: str, user_id: str) -> dict | None:
    with SessionLocal() as db:
        game = db.get(GameRecord, game_id)
        if not game:
            return None
        if game.white_id != user_id and game.black_id != user_id:
            return None
        moves = (
            db.query(GameMoveRecord)
            .filter(GameMoveRecord.game_id == game.id)
            .order_by(GameMoveRecord.ply.asc())
            .all()
        )
        return {
            "game_id": game.id,
            "fen": game.fen,
            "time_control": game.time_control_key,
            "white_username": game.white_username,
            "black_username": game.black_username,
            "result": game.result,
            "result_reason": game.result_reason,
            "result_detail": game.result_detail,
            "moves": [{"san": m.san, "time_ms": m.move_time_ms, "from": m.uci_from, "to": m.uci_to, "fen_after": m.fen_after} for m in moves],
        }


def get_history_by_invite_key(invite_key: str) -> dict | None:
    with SessionLocal() as db:
        inv = db.get(PrivateInviteRecord, invite_key)
        if not inv or not inv.game_id:
            return None
        game = db.get(GameRecord, inv.game_id)
        if not game:
            return None
        moves = (
            db.query(GameMoveRecord)
            .filter(GameMoveRecord.game_id == game.id)
            .order_by(GameMoveRecord.ply.asc())
            .all()
        )
        return {
            "game_id": game.id,
            "fen": game.fen,
            "time_control": game.time_control_key,
            "white_username": game.white_username,
            "black_username": game.black_username,
            "result": game.result,
            "result_reason": game.result_reason,
            "result_detail": game.result_detail,
            "moves": [{"san": m.san, "time_ms": m.move_time_ms, "from": m.uci_from, "to": m.uci_to, "fen_after": m.fen_after} for m in moves],
        }


def get_user_notification_target(user_id: str) -> tuple[int, bool]:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return (0, False)
        return (user.telegram_id, bool(user.has_started_bot))


def game_state_payload(g: Game) -> dict:
    """Собрать payload game_state для отправки клиенту."""
    white_ms, black_ms = _live_remaining_ms(g)
    return {
        "type": "game_state",
        "fen": g.fen,
        "white_remaining_ms": white_ms,
        "black_remaining_ms": black_ms,
        "moves": [{"san": m.san, "time_ms": m.time_ms} for m in g.moves],
        "result": g.result,
        "result_reason": g.result_reason,
        "result_detail": g.result_detail,
        "draw_offer_by": g.draw_offer_by,
        "draw_offer_color": _draw_offer_color(g),
        "server_time_ms": int(time.time() * 1000),
        "is_bot_game": bool(g.is_bot_game),
        "no_clock_user_id": g.no_clock_user_id,
        "tournament_id": g.tournament_id,
    }


def _draw_offer_color(g: Game) -> str | None:
    if not g.draw_offer_by:
        return None
    if g.draw_offer_by == g.white_id:
        return "white"
    if g.draw_offer_by == g.black_id:
        return "black"
    return None


def get_game_for_user(game_id: str, user_id: str) -> Game | None:
    """Партия существует и пользователь в ней участник."""
    g = _games.get(game_id)
    if not g or (g.white_id != user_id and g.black_id != user_id):
        return None
    return g


def resign_game(game_id: str, user_id: str) -> dict | None:
    """Сдача партии. Возвращает payload для broadcast или None."""
    g = get_game_for_user(game_id, user_id)
    if not g or g.result is not None:
        return None
    g.result = "0-1" if user_id == g.white_id else "1-0"
    g.result_reason = "resign"
    g.result_detail = None
    g.draw_offer_by = None
    _persist_game_state(g)
    mark_invite_finished_by_game(g.id)
    _apply_finished_game_ratings(g)
    _maybe_tournament_hook(g)
    return {
        "fen": g.fen,
        "white_remaining_ms": g.white_remaining_ms,
        "black_remaining_ms": g.black_remaining_ms,
        "result": g.result,
        "result_reason": g.result_reason,
        "result_detail": g.result_detail,
        "draw_offer_by": g.draw_offer_by,
    }


def _insufficient_material_detail(board: Board) -> str:
    pieces = board.piece_map().values()
    white = [p for p in pieces if p.color == chess.WHITE and p.piece_type != chess.KING]
    black = [p for p in pieces if p.color == chess.BLACK and p.piece_type != chess.KING]

    def label(side: list[chess.Piece]) -> str:
        if not side:
            return "король"
        t = sorted(p.piece_type for p in side)
        if t == [chess.BISHOP]:
            return "король и слон"
        if t == [chess.KNIGHT]:
            return "король и конь"
        return "король и фигуры"

    return f"Недостаточно материала: {label(white)} против {label(black)}."


def _apply_result(g: Game, board: Board) -> None:
    if board.is_checkmate():
        g.result = "1-0" if board.turn == chess.BLACK else "0-1"
        g.result_reason = "checkmate"
        g.result_detail = None
    elif board.is_stalemate():
        g.result = "1/2-1/2"
        g.result_reason = "stalemate"
        g.result_detail = "Пат."
    elif board.is_insufficient_material():
        g.result = "1/2-1/2"
        g.result_reason = "insufficient_material"
        g.result_detail = _insufficient_material_detail(board)
    elif board.is_repetition(3):
        g.result = "1/2-1/2"
        g.result_reason = "draw_claim_threefold"
        g.result_detail = "Ничья автоматически: троекратное повторение позиции."
    elif board.halfmove_clock >= 100:
        g.result = "1/2-1/2"
        g.result_reason = "draw_claim_fifty_move"
        g.result_detail = "Ничья автоматически: 50 ходов без взятия и хода пешкой."
    elif board.is_fivefold_repetition():
        g.result = "1/2-1/2"
        g.result_reason = "draw_auto_fivefold"
        g.result_detail = "Ничья автоматически: пятикратное повторение позиции."
    elif board.is_seventyfive_moves():
        g.result = "1/2-1/2"
        g.result_reason = "draw_auto_75move"
        g.result_detail = "Ничья автоматически: 75 ходов без взятия и хода пешкой."
    elif (
        (_side_clock_runs(g, g.white_id) and g.white_remaining_ms <= 0)
        or (_side_clock_runs(g, g.black_id) and g.black_remaining_ms <= 0)
    ):
        g.result = "0-1" if g.white_remaining_ms <= 0 else "1-0"
        g.result_reason = "timeout"
        g.result_detail = None


def _live_remaining_ms(g: Game) -> tuple[int, int]:
    white = g.white_remaining_ms
    black = g.black_remaining_ms
    if g.result is not None:
        return white, black
    now = time.monotonic()
    elapsed = int(max(0.0, now - g.last_clock_at) * 1000)
    board = Board(g.fen)
    if board.turn == chess.WHITE:
        if g.white_clock_started and _side_clock_runs(g, g.white_id):
            white = max(0, white - elapsed)
    else:
        if g.black_clock_started and _side_clock_runs(g, g.black_id):
            black = max(0, black - elapsed)
    return white, black


def materialize_live_clocks(g: Game) -> None:
    """
    Commit live clock snapshot into stored game state.
    """
    if g.result is not None:
        return
    white, black = _live_remaining_ms(g)
    g.white_remaining_ms = white
    g.black_remaining_ms = black
    g.last_clock_at = time.monotonic()
    if (
        (_side_clock_runs(g, g.white_id) and white <= 0)
        or (_side_clock_runs(g, g.black_id) and black <= 0)
    ):
        g.result = "0-1" if white <= 0 else "1-0"
        g.result_reason = "timeout"
        g.result_detail = None


def turn_user_id(g: Game) -> str:
    board = Board(g.fen)
    return g.white_id if board.turn == chess.WHITE else g.black_id


def get_active_game_for_user(user_id: str) -> Game | None:
    for g in _games.values():
        if g.result is not None:
            continue
        if g.white_id == user_id or g.black_id == user_id:
            return g
    return None


def offer_draw(game_id: str, user_id: str) -> dict | None:
    g = get_game_for_user(game_id, user_id)
    if not g or g.result is not None:
        return None
    if g.is_bot_game:
        return None
    if g.draw_offer_by is not None:
        return None
    ply = len(g.moves)
    # Product policy: no draw offers before move 15 and not more than once per 5 moves.
    if ply < 30:
        return None
    if user_id == g.white_id:
        last = g.white_last_draw_offer_ply
    else:
        last = g.black_last_draw_offer_ply
    if last is not None and ply - last < 10:
        return None
    g.draw_offer_by = user_id
    g.draw_offer_ply = ply
    if user_id == g.white_id:
        g.white_last_draw_offer_ply = ply
    else:
        g.black_last_draw_offer_ply = ply
    return {
        "draw_offer_by": g.draw_offer_by,
        "draw_offer_ply": g.draw_offer_ply,
        "draw_offer_color": _draw_offer_color(g),
    }


def accept_draw_offer(game_id: str, user_id: str) -> dict | None:
    g = get_game_for_user(game_id, user_id)
    if not g or g.result is not None or not g.draw_offer_by:
        return None
    if g.draw_offer_by == user_id:
        return None
    g.result = "1/2-1/2"
    g.result_reason = "draw_agreement"
    g.result_detail = "Ничья по соглашению сторон."
    g.draw_offer_by = None
    g.draw_offer_ply = None
    _persist_game_state(g)
    mark_invite_finished_by_game(g.id)
    _apply_finished_game_ratings(g)
    _maybe_tournament_hook(g)
    return {
        "fen": g.fen,
        "white_remaining_ms": g.white_remaining_ms,
        "black_remaining_ms": g.black_remaining_ms,
        "result": g.result,
        "result_reason": g.result_reason,
        "result_detail": g.result_detail,
        "draw_offer_by": g.draw_offer_by,
        "draw_offer_color": _draw_offer_color(g),
    }


def claim_draw(game_id: str, user_id: str, claim_type: str) -> dict | None:
    # Product policy: draw claims are disabled; eligible draw states are applied automatically.
    return None


def forfeit_disconnected_player(game_id: str, disconnected_user_id: str) -> dict | None:
    g = get_game_for_user(game_id, disconnected_user_id)
    if not g or g.result is not None:
        return None
    g.result = "0-1" if disconnected_user_id == g.white_id else "1-0"
    g.result_reason = "disconnect_forfeit"
    g.result_detail = "Соперник отключился и не вернулся вовремя."
    g.draw_offer_by = None
    g.draw_offer_ply = None
    _persist_game_state(g)
    mark_invite_finished_by_game(g.id)
    _apply_finished_game_ratings(g)
    _maybe_tournament_hook(g)
    return {
        "fen": g.fen,
        "white_remaining_ms": g.white_remaining_ms,
        "black_remaining_ms": g.black_remaining_ms,
        "result": g.result,
        "result_reason": g.result_reason,
        "result_detail": g.result_detail,
        "draw_offer_by": g.draw_offer_by,
        "draw_offer_color": _draw_offer_color(g),
    }


def apply_move(
    game_id: str,
    user_id: str,
    from_sq: str,
    to_sq: str,
    promotion: str | None = None,
    is_premove: bool = False,
) -> dict | None:
    """
    Применить ход. Возвращает dict для broadcast (game_update) или None при ошибке.
    """
    g = get_game_for_user(game_id, user_id)
    if not g or g.result is not None:
        return None
    materialize_live_clocks(g)
    if g.result is not None:
        return {
            "fen": g.fen,
            "white_remaining_ms": g.white_remaining_ms,
            "black_remaining_ms": g.black_remaining_ms,
            "san": None,
            "move_time_ms": 0,
            "result": g.result,
            "result_reason": g.result_reason,
            "result_detail": g.result_detail,
            "draw_offer_by": g.draw_offer_by,
            "draw_offer_color": _draw_offer_color(g),
            "from": None,
            "to": None,
        }
    board = Board(g.fen)
    if board.turn != (chess.WHITE if user_id == g.white_id else chess.BLACK):
        return None
    uci = from_sq + to_sq + (promotion or "")
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return None
    if move not in board.legal_moves:
        return None
    # Opponent move declines pending draw offer.
    if g.draw_offer_by and g.draw_offer_by != user_id:
        g.draw_offer_by = None
        g.draw_offer_ply = None
    now = time.monotonic()
    elapsed_ms = 0 if is_premove else int((now - g.last_clock_at) * 1000)
    tc = g.time_control
    inc_ms = tc["increment_seconds"] * 1000
    move_no = (len(g.moves) // 2) + 1
    if board.turn == chess.WHITE:
        if g.white_clock_started and _side_clock_runs(g, g.white_id):
            white_used = min(g.white_remaining_ms, elapsed_ms)
        else:
            white_used = 0
        white_inc = 0 if move_no == 1 else inc_ms
        g.white_remaining_ms = max(0, g.white_remaining_ms - white_used + white_inc)
        move_time_ms = white_used
        if not g.black_clock_started:
            g.black_clock_started = True
    else:
        if g.black_clock_started and _side_clock_runs(g, g.black_id):
            black_used = min(g.black_remaining_ms, elapsed_ms)
        else:
            black_used = 0
        g.black_remaining_ms = max(0, g.black_remaining_ms - black_used + inc_ms)
        move_time_ms = black_used
        if not g.white_clock_started:
            g.white_clock_started = True
    g.last_clock_at = now
    san = board.san(move)
    board.push(move)
    g.fen = board.fen()
    if g.is_bot_game and not is_premove:
        # Untimed game: still record wall time since previous move for move list / UX.
        move_time_ms = min(max(0, elapsed_ms), 600_000)
    g.moves.append(MoveRecord(san=san, time_ms=move_time_ms))
    _apply_result(g, board)
    if not g.is_bot_game:
        _persist_game_state(g, from_sq=from_sq, to_sq=to_sq, promotion=promotion, san=san, move_time_ms=move_time_ms)
    if g.result is not None:
        mark_invite_finished_by_game(g.id)
        if not g.is_bot_game:
            _apply_finished_game_ratings(g)
        _maybe_tournament_hook(g)
    uci = move.uci()
    return {
        "fen": g.fen,
        "white_remaining_ms": g.white_remaining_ms,
        "black_remaining_ms": g.black_remaining_ms,
        "san": san,
        "move_time_ms": move_time_ms,
        "result": g.result,
        "result_reason": g.result_reason,
        "result_detail": g.result_detail,
        "draw_offer_by": g.draw_offer_by,
        "draw_offer_color": _draw_offer_color(g),
        "from": uci[:2],
        "to": uci[2:4],
    }


def abort_unstarted_game(game_id: str) -> dict | None:
    g = _games.get(game_id)
    if not g or g.result is not None:
        return None
    if len(g.moves) >= 2:
        return None
    g.result = "1/2-1/2"
    g.result_reason = "aborted_unstarted"
    g.result_detail = "Партия не состоялась: первый ход белых и черных не был сделан за 60 секунд."
    g.draw_offer_by = None
    if not g.is_bot_game:
        _persist_game_state(g)
        mark_invite_finished_by_game(g.id)
    return {
        "fen": g.fen,
        "white_remaining_ms": g.white_remaining_ms,
        "black_remaining_ms": g.black_remaining_ms,
        "result": g.result,
        "result_reason": g.result_reason,
        "result_detail": g.result_detail,
        "draw_offer_by": g.draw_offer_by,
        "draw_offer_color": _draw_offer_color(g),
    }
