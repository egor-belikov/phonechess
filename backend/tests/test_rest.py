"""REST auth, webhook secret, analysis guard, orphaned games."""
from app import pairing as P
from conftest import WEBHOOK_SECRET, auth_headers, make_init_data


def test_profile_requires_auth(client, uid):
    u = uid()
    P.ensure_user_registered(str(u), u, "x")
    assert client.get("/api/profile").status_code == 401
    assert client.get(f"/api/profile?telegram_id={u}").status_code == 401
    r = client.get("/api/profile", headers=auth_headers(u))
    assert r.status_code == 200 and r.json()["user_id"] == str(u)
    assert client.get("/api/profile", headers=auth_headers(u, age_sec=2 * 86400)).status_code == 401
    bad = {"Authorization": "tma " + make_init_data(u).replace("hash=", "hash=0")}
    assert client.get("/api/profile", headers=bad).status_code == 401


def test_register_only_own_login(client, uid):
    me, other = uid(), uid()
    P.ensure_user_registered(str(me), me, "me")
    P.ensure_user_registered(str(other), other, "other")
    name = f"n{me}"
    r = client.post("/api/login/register", headers=auth_headers(me), json={"telegram_id": other, "login_name": name})
    assert r.status_code == 200
    assert client.get("/api/profile", headers=auth_headers(me)).json()["login_name"] == name
    assert client.get("/api/profile", headers=auth_headers(other)).json()["login_name"] is None


def test_debug_header_only_without_token(client, no_bot_token, uid):
    u = uid()
    P.ensure_user_registered(str(u), u, "x")
    assert client.get("/api/profile", headers={"X-Debug-Uid": str(u)}).status_code == 200


def test_debug_header_ignored_with_token(client, uid):
    u = uid()
    P.ensure_user_registered(str(u), u, "x")
    assert client.get("/api/profile", headers={"X-Debug-Uid": str(u)}).status_code == 401


def test_webhook_secret(client):
    upd = {"message": {"text": "hi", "chat": {"id": 1}}}
    assert client.post("/telegram/webhook", json=upd).status_code == 403
    assert client.post("/telegram/webhook", json=upd, headers={"X-Telegram-Bot-Api-Secret-Token": "bad"}).status_code == 403
    ok = client.post("/telegram/webhook", json=upd, headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET})
    assert ok.status_code == 200


def test_analyze_forbidden_during_live_game(client, uid):
    a, b = uid(), uid()
    P.join_queue("15+10", str(a), a, "a")
    g = P.join_queue("15+10", str(b), b, "b")
    try:
        r = client.get("/api/analyze", params={"fen": g.fen}, headers=auth_headers(a))
        assert r.status_code == 403 and r.json()["detail"] == "game_in_progress"
    finally:
        P.resign_game(g.id, str(a))


def test_close_orphaned_games(uid):
    from app.db import SessionLocal
    from app.models import GameRecord
    a, b = uid(), uid()
    P.join_queue("10+0", str(a), a, "a")
    g = P.join_queue("10+0", str(b), b, "b")
    assert P.close_orphaned_games() >= 1
    with SessionLocal() as db:
        rec = db.get(GameRecord, g.id)
        assert rec.result == "*" and rec.result_reason == "aborted_server_restart"
    P.resign_game(g.id, str(a))  # free the users' in-memory game
