"""
Test setup: env must be set before `app` is imported (config is cached, DB engine is created at import).
Every test uses its own user ids, because game/queue state is process-global.
"""
import hashlib
import hmac
import itertools
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

BOT_TOKEN = "123456:test-token"
WEBHOOK_SECRET = "test-webhook-secret"

_tmp = tempfile.mkdtemp(prefix="phonechess-tests-")
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{Path(_tmp) / 'test.db'}"
os.environ["TELEGRAM_BOT_TOKEN"] = BOT_TOKEN
os.environ["TELEGRAM_WEBHOOK_SECRET"] = WEBHOOK_SECRET
os.environ["DEBUG"] = "1"
os.environ.setdefault("STOCKFISH_PATH", str(Path(_tmp) / "no-stockfish"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_config  # noqa: E402
from app.main import app  # noqa: E402

_uid_counter = itertools.count(100_000)


@pytest.fixture
def uid():
    """Fresh numeric telegram id per call."""
    return lambda: next(_uid_counter)


def make_init_data(telegram_id: int, age_sec: int = 0, token: str = BOT_TOKEN) -> str:
    fields = {
        "auth_date": str(int(time.time()) - age_sec),
        "query_id": "q",
        "user": json.dumps({"id": telegram_id, "first_name": f"U{telegram_id}", "username": f"u{telegram_id}"}),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def auth_headers(telegram_id: int, age_sec: int = 0) -> dict:
    return {"Authorization": "tma " + make_init_data(telegram_id, age_sec)}


@pytest.fixture(scope="session")
def client():
    # Context manager => one shared event loop for all WebSocket sessions (cross-socket sends work).
    with TestClient(app) as c:
        yield c


@pytest.fixture
def no_bot_token(monkeypatch):
    """Local-debug mode: DEBUG=1 and no bot token."""
    monkeypatch.setattr(get_config(), "telegram_bot_token", "")


def recv_until(ws, msg_type: str, limit: int = 30) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == msg_type:
            return msg
    raise AssertionError(f"no {msg_type!r} message")


def ws_auth(ws, telegram_id: int) -> dict:
    ws.send_json({"type": "auth", "init_data": make_init_data(telegram_id)})
    return recv_until(ws, "queue_counts")
