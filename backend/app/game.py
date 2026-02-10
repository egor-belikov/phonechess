"""
Минимальная логика партии для этапа 1: хранение состояния.
Полная валидация ходов и часы — в следующих этапах.
"""
from .pairing import Game, get_game, get_game_for_user

__all__ = ["Game", "get_game", "get_game_for_user"]
