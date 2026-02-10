"""Константы режимов игры."""
from typing import TypedDict


class TimeControl(TypedDict):
    initial_seconds: int
    increment_seconds: int
    key: str


TIME_CONTROLS: list[TimeControl] = [
    {"key": "3+0", "initial_seconds": 3 * 60, "increment_seconds": 0},
    {"key": "3+2", "initial_seconds": 3 * 60, "increment_seconds": 2},
    {"key": "5+0", "initial_seconds": 5 * 60, "increment_seconds": 0},
    {"key": "5+3", "initial_seconds": 5 * 60, "increment_seconds": 3},
    {"key": "10+0", "initial_seconds": 10 * 60, "increment_seconds": 0},
    {"key": "15+10", "initial_seconds": 15 * 60, "increment_seconds": 10},
]

TIME_CONTROL_KEYS = [tc["key"] for tc in TIME_CONTROLS]
