"""WebSocket protocol: auth, server flag, takeover/resume, one activity per user, move_rejected."""
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from app import pairing as P
from conftest import make_init_data, recv_until, ws_auth

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def start_pair(a, b, ida, idb, tc="3+0"):
    ws_auth(a, ida)
    ws_auth(b, idb)
    a.send_json({"type": "join_queue", "time_control": tc})
    b.send_json({"type": "join_queue", "time_control": tc})
    ma = recv_until(a, "matched")
    recv_until(b, "matched")
    return ma


def test_debug_uid_rejected_with_bot_token(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "init_data": "", "debug_uid": 1})
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 4003


def test_debug_uid_allowed_locally(client, no_bot_token, uid):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "init_data": "", "debug_uid": uid()})
        assert recv_until(ws, "queue_counts")


def test_stale_init_data_rejected(client, uid):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "init_data": make_init_data(uid(), age_sec=2 * 86400)})
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 4003


def test_server_flag_without_move_and_one_activity(client, uid):
    ida, idb = uid(), uid()
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        ma = start_pair(a, b, ida, idb)
        gid = ma["game_id"]
        g = P.get_game_any(gid)
        white, black = (a, b) if ma["color"] == "white" else (b, a)

        white.send_json({"type": "join_queue", "time_control": "5+0"})
        assert recv_until(white, "action_denied")["game_id"] == gid
        assert recv_until(white, "matched")["resumed"] is True

        g.white_remaining_ms = 1000
        white.send_json({"type": "make_move", "game_id": gid, "from": "e2", "to": "e4"})
        recv_until(white, "game_update"); recv_until(black, "game_update")
        black.send_json({"type": "make_move", "game_id": gid, "from": "e7", "to": "e5"})
        recv_until(white, "game_update"); recv_until(black, "game_update")
        t0 = time.time()
        u = recv_until(black, "game_update")  # nobody moves
        assert u["result"] == "0-1" and u["result_reason"] == "timeout"
        assert time.time() - t0 < 3


def test_takeover_and_resume(client, uid):
    ida, idb = uid(), uid()
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        ma = start_pair(a, b, ida, idb, "5+0")
        with client.websocket_connect("/ws") as a2:
            ws_auth(a2, ida)
            r = recv_until(a2, "matched")
            assert r["resumed"] and r["game_id"] == ma["game_id"] and r["color"] == ma["color"]
            with pytest.raises(WebSocketDisconnect) as e:
                while True:
                    a.receive_json()
            assert e.value.code == 4010
            a2.send_json({"type": "ping", "client_ts": 7})
            assert recv_until(a2, "pong")["client_ts"] == 7


def test_move_rejected(client, uid):
    ida, idb = uid(), uid()
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        ma = start_pair(a, b, ida, idb, "10+0")
        mover = a if ma["color"] == "white" else b
        mover.send_json({"type": "make_move", "game_id": ma["game_id"], "from": "e2", "to": "e5"})
        rej = recv_until(mover, "move_rejected")
        assert rej["fen"] == START
