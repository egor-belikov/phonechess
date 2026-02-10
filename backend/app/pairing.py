"""
Очереди пейринга и создание партий (in-memory).
Этап 2: часы, ходы, валидация через python-chess.
"""
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
    fen: str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    moves: list[MoveRecord] = field(default_factory=list)
    is_private: bool = False
    white_remaining_ms: int = 0
    black_remaining_ms: int = 0
    last_clock_at: float = 0.0  # unix timestamp когда часы последний раз обновлялись
    result: str | None = None  # None | "1-0" | "0-1" | "1/2-1/2"

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
    player = QueuedPlayer(user_id=user_id, telegram_id=telegram_id, username=username)
    if queue:
        opponent = queue.pop(0)
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
    )
    g._init_clocks()
    return g


def get_game(game_id: str) -> Game | None:
    return _games.get(game_id)


def game_state_payload(g: Game) -> dict:
    """Собрать payload game_state для отправки клиенту."""
    return {
        "type": "game_state",
        "fen": g.fen,
        "white_remaining_ms": g.white_remaining_ms,
        "black_remaining_ms": g.black_remaining_ms,
        "moves": [{"san": m.san, "time_ms": m.time_ms} for m in g.moves],
        "result": g.result,
    }


def get_game_for_user(game_id: str, user_id: str) -> Game | None:
    """Партия существует и пользователь в ней участник."""
    g = _games.get(game_id)
    if not g or (g.white_id != user_id and g.black_id != user_id):
        return None
    return g


def apply_move(game_id: str, user_id: str, from_sq: str, to_sq: str, promotion: str | None = None) -> dict | None:
    """
    Применить ход. Возвращает dict для broadcast (game_update) или None при ошибке.
    """
    g = get_game_for_user(game_id, user_id)
    if not g or g.result is not None:
        return None
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
    now = time.monotonic()
    elapsed_ms = int((now - g.last_clock_at) * 1000)
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
    if board.is_checkmate():
        g.result = "1-0" if board.turn == chess.BLACK else "0-1"
    elif board.is_stalemate() or board.is_insufficient_material() or board.can_claim_fifty_moves() or board.can_claim_threefold_repetition():
        g.result = "1/2-1/2"
    elif g.white_remaining_ms <= 0 or g.black_remaining_ms <= 0:
        g.result = "0-1" if g.white_remaining_ms <= 0 else "1-0"
    uci = move.uci()
    return {
        "fen": g.fen,
        "white_remaining_ms": g.white_remaining_ms,
        "black_remaining_ms": g.black_remaining_ms,
        "san": san,
        "move_time_ms": move_time_ms,
        "result": g.result,
        "from": uci[:2],
        "to": uci[2:4],
    }
