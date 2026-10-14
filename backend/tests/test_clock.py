"""Clock, move time, premove refund, increment, flag fall rules (pairing.py, no WebSocket)."""
from app import pairing as P
from app.db import SessionLocal
from app.models import GameMoveRecord

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def new_game(uid, tc="3+0"):
    a, b = uid(), uid()
    return P.join_queue(tc, str(a), a, "a") or P.join_queue(tc, str(b), b, "b")


def test_move_time_and_premove_refund(uid):
    g = new_game(uid)
    w, b = g.white_id, g.black_id
    u = P.apply_move(g.id, w, "e2", "e4")
    assert u["move_time_ms"] == 0 and u["white_remaining_ms"] == 180_000  # white clock not started yet

    g.last_clock_at -= 3
    u = P.apply_move(g.id, b, "e7", "e5")
    assert 2900 < u["move_time_ms"] < 3200
    assert 176_800 < u["black_remaining_ms"] < 177_100

    # Fake premove flag after 20 s of thinking: only PREMOVE_FREE_MS is refunded.
    g.last_clock_at -= 20
    u = P.apply_move(g.id, w, "g1", "f3", is_premove=True)
    assert 19_600 < u["move_time_ms"] < 19_800
    assert 160_200 < u["white_remaining_ms"] < 160_400

    # Real premove (100 ms round trip) is free and shows 0:00.
    before = g.black_remaining_ms
    g.last_clock_at -= 0.1
    u = P.apply_move(g.id, b, "b8", "c6", is_premove=True)
    assert u["move_time_ms"] == 0
    assert abs(before - u["black_remaining_ms"]) < 20

    g.last_clock_at -= 5
    u = P.apply_move(g.id, w, "f1", "c4")
    assert 4900 < u["move_time_ms"] < 5200

    with SessionLocal() as db:
        rows = db.query(GameMoveRecord).filter_by(game_id=g.id).order_by(GameMoveRecord.ply).all()
        times = [r.move_time_ms for r in rows]
    assert times[0] == 0 and times[3] == 0 and all(t > 2000 for t in (times[1], times[2], times[4]))


def test_increment_black_from_first_white_from_second(uid):
    g = new_game(uid, "3+2")
    P.apply_move(g.id, g.white_id, "d2", "d4")
    u = P.apply_move(g.id, g.black_id, "d7", "d5")
    assert abs(u["black_remaining_ms"] - 182_000) < 50
    g.last_clock_at -= 1
    u = P.apply_move(g.id, g.white_id, "c2", "c4")
    assert 180_900 < u["white_remaining_ms"] < 181_100


def test_bot_game_untimed_but_records_move_time(uid):
    h = uid()
    g = P.create_bot_game("3+0", str(h), h, "h", 1100)
    if g.white_id != g.human_user_id:
        P.apply_move(g.id, g.white_id, "e2", "e4")
        g.last_clock_at -= 7
        u = P.apply_move(g.id, g.human_user_id, "e7", "e5")
    else:
        g.last_clock_at -= 7
        u = P.apply_move(g.id, g.human_user_id, "e2", "e4")
    assert 6900 < u["move_time_ms"] < 7200
    assert u["white_remaining_ms"] == u["black_remaining_ms"] == 180_000


def _bare_game(fen):
    return P.Game(id="x", time_control_key="3+0", white_id="w", black_id="b", white_username="",
                  black_username="", white_telegram_id=0, black_telegram_id=0, fen=fen)


def test_flag_vs_insufficient_material_is_draw():
    g = _bare_game("8/8/8/8/8/8/k7/K6Q w - - 0 1")
    P._set_timeout_result(g, white_flagged=True)  # black has a lone king
    assert g.result == "1/2-1/2" and g.result_reason == "timeout_vs_insufficient"
    g = _bare_game("8/8/8/8/8/8/k7/K6Q w - - 0 1")
    P._set_timeout_result(g, white_flagged=False)  # white has a queen
    assert g.result == "1-0" and g.result_reason == "timeout"


def test_check_flag_persists_and_rates(uid):
    g = new_game(uid)
    P.apply_move(g.id, g.white_id, "e2", "e4")
    P.apply_move(g.id, g.black_id, "e7", "e5")
    g.last_clock_at -= 200  # white's clock ran out
    assert P.check_flag(g.id)
    assert g.result == "0-1" and g.result_reason == "timeout"
    from app.models import GameRecord, User
    with SessionLocal() as db:
        assert db.get(GameRecord, g.id).result == "0-1"
        assert db.get(User, g.white_id).blitz_rating < 1500
        assert db.get(User, g.black_id).games_played >= 1


def test_rematch_only_after_finish_and_once(uid):
    g = new_game(uid)
    g.is_private = True
    assert P.create_private_rematch(g.id) is None  # game still running
    P.resign_game(g.id, g.white_id)
    r = P.create_private_rematch(g.id)
    assert r and r.white_id == g.black_id
    assert P.create_private_rematch(g.id) is None


def test_bot_game_never_persisted_on_resign(uid):
    from app.models import GameRecord
    h = uid()
    g = P.create_bot_game("3+0", str(h), h, "h", 1100)
    P.resign_game(g.id, str(h))
    with SessionLocal() as db:
        assert db.get(GameRecord, g.id) is None


def test_evict_finished_games(uid):
    g = new_game(uid)
    P.resign_game(g.id, g.white_id)
    assert P.evict_finished_games(now=1000.0, ttl=60) == []  # first sight starts the timer
    assert g.id in P.evict_finished_games(now=1061.0, ttl=60)
    assert P.get_game_any(g.id) is None
