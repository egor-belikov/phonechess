"""
Очереди пейринга и создание партий (in-memory).
Этап 2: часы, ходы, валидация через python-chess.
"""
import random
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

import chess
from chess import Board

from .constants import TIME_CONTROL_KEYS, TIME_CONTROLS, TimeControl


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
    elif board.is_fivefold_repetition():
        g.result = "1/2-1/2"
        g.result_reason = "draw_auto_fivefold"
        g.result_detail = "Ничья автоматически: пятикратное повторение позиции."
    elif board.is_seventyfive_moves():
        g.result = "1/2-1/2"
        g.result_reason = "draw_auto_75move"
        g.result_detail = "Ничья автоматически: 75 ходов без взятия и хода пешкой."
    elif g.white_remaining_ms <= 0 or g.black_remaining_ms <= 0:
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
        white = max(0, white - elapsed)
    else:
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
    if white <= 0 or black <= 0:
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
    g = get_game_for_user(game_id, user_id)
    if not g or g.result is not None:
        return None
    board = Board(g.fen)
    is_white_turn = board.turn == chess.WHITE
    if (is_white_turn and user_id != g.white_id) or ((not is_white_turn) and user_id != g.black_id):
        return None
    if claim_type == "threefold" and board.can_claim_threefold_repetition():
        g.result = "1/2-1/2"
        g.result_reason = "draw_claim_threefold"
        g.result_detail = "Ничья по заявке: троекратное повторение позиции."
    elif claim_type == "fifty_move" and board.can_claim_fifty_moves():
        g.result = "1/2-1/2"
        g.result_reason = "draw_claim_fifty_move"
        g.result_detail = "Ничья по заявке: 50 ходов без взятия и хода пешкой."
    else:
        return None
    g.draw_offer_by = None
    g.draw_offer_ply = None
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


def forfeit_disconnected_player(game_id: str, disconnected_user_id: str) -> dict | None:
    g = get_game_for_user(game_id, disconnected_user_id)
    if not g or g.result is not None:
        return None
    g.result = "0-1" if disconnected_user_id == g.white_id else "1-0"
    g.result_reason = "disconnect_forfeit"
    g.result_detail = "Соперник отключился и не вернулся вовремя."
    g.draw_offer_by = None
    g.draw_offer_ply = None
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
    if board.turn == chess.WHITE:
        white_used = min(g.white_remaining_ms, elapsed_ms)
        g.white_remaining_ms = max(0, g.white_remaining_ms - white_used + inc_ms)
        move_time_ms = white_used
    else:
        black_used = min(g.black_remaining_ms, elapsed_ms)
        g.black_remaining_ms = max(0, g.black_remaining_ms - black_used + inc_ms)
        move_time_ms = black_used
    g.last_clock_at = now
    san = board.san(move)
    board.push(move)
    g.fen = board.fen()
    g.moves.append(MoveRecord(san=san, time_ms=move_time_ms))
    _apply_result(g, board)
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
