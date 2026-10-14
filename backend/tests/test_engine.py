"""Stockfish wrapper: restart of a dead engine, bounded analysis cache. Real engine tests run only if available."""
import os
import shutil

import chess
import chess.engine
import pytest

from app import uci_bot

START = chess.STARTING_FEN


class _DeadEngine:
    options = {}

    def configure(self, *_):
        raise chess.engine.EngineTerminatedError("dead")

    def quit(self):
        pass


def test_dead_engine_is_dropped_and_move_is_legal(monkeypatch):
    monkeypatch.setattr(uci_bot, "_ensure_engine", lambda kind="play": _DeadEngine())
    mv = uci_bot._pick_move_blocking_at_elo(START, 1400)
    assert chess.Move.from_uci(mv) in chess.Board(START).legal_moves


def test_analysis_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(uci_bot, "_ANALYSIS_CACHE_MAX", 3)
    uci_bot._analysis_cache.clear()
    for i in range(10):
        uci_bot._cache_put(str(i), 0.0, {})
    assert list(uci_bot._analysis_cache) == ["7", "8", "9"]
    uci_bot._analysis_cache.clear()


_SF = os.environ.get("STOCKFISH_TEST_PATH") or shutil.which("stockfish")


@pytest.mark.skipif(not _SF, reason="stockfish binary not available")
def test_real_engine_play_and_analysis(monkeypatch):
    from app.config import get_config

    monkeypatch.setattr(get_config(), "stockfish_path", _SF)
    uci_bot.shutdown_uci_bot()
    try:
        mv = uci_bot._pick_move_blocking_at_elo(START, 1500)
        assert chess.Move.from_uci(mv) in chess.Board(START).legal_moves
        res = uci_bot._analyze_fen_blocking(START)
        assert res["lines"] and res["lines"][0]["san"].startswith("1.")
    finally:
        uci_bot.shutdown_uci_bot()
