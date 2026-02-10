"""
Очереди пейринга и создание партий (in-memory для этапа 1).
"""
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from .constants import TIME_CONTROL_KEYS, TIME_CONTROLS, TimeControl


@dataclass
class QueuedPlayer:
    user_id: str
    telegram_id: int
    username: str


@dataclass
class Game:
    id: str
    time_control_key: str
    white_id: str
    black_id: str
    white_username: str
    black_username: str
    fen: str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    moves: list[str] = field(default_factory=list)
    is_private: bool = False

    @property
    def time_control(self) -> TimeControl:
        for tc in TIME_CONTROLS:
            if tc["key"] == self.time_control_key:
                return tc
        return TIME_CONTROLS[0]


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
    return Game(
        id=str(uuid.uuid4()),
        time_control_key=time_control_key,
        white_id=white.user_id,
        black_id=black.user_id,
        white_username=white.username or f"user_{white.user_id[:8]}",
        black_username=black.username or f"user_{black.user_id[:8]}",
    )


def get_game(game_id: str) -> Game | None:
    return _games.get(game_id)


def get_game_for_user(game_id: str, user_id: str) -> Game | None:
    """Партия существует и пользователь в ней участник."""
    g = _games.get(game_id)
    if not g or (g.white_id != user_id and g.black_id != user_id):
        return None
    return g
