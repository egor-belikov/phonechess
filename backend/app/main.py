"""
PhoneChess API и WebSocket.
"""
import asyncio
import hmac
import logging
import re
import time
from pathlib import Path
from collections import deque

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .constants import BOT_CAMPAIGN_ELOS
from .auth import validate_init_data
from .config import get_config
from .db import Base, SessionLocal, engine
from . import models  # noqa: F401
from .telegram_bot import process_update
from .uci_bot import analyze_fen_light, shutdown_uci_bot
from .ws_handlers import ws_auth_and_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="PhoneChess API")
config = get_config()
Base.metadata.create_all(bind=engine)


def _column_exists(table: str, column: str) -> bool:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() if engine.dialect.name == "sqlite" else conn.execute(text(f"SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table}).fetchall()
    if engine.dialect.name == "sqlite":
        return any((r[1] == column) for r in rows)
    return any((r[0] == column) for r in rows)


def _ensure_schema_updates() -> None:
    alter_map = [
        ("users", "login_name", "VARCHAR(20)"),
        ("users", "is_anonymous", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("users", "blitz_rating", "INTEGER NOT NULL DEFAULT 1500"),
        ("users", "rapid_rating", "INTEGER NOT NULL DEFAULT 1500"),
        ("users", "games_played", "INTEGER NOT NULL DEFAULT 0"),
        ("users", "bot_campaign_beaten_json", "TEXT"),
    ]
    with engine.begin() as conn:
        for table, col, col_type in alter_map:
            if _column_exists(table, col):
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
        # Backfill safety: keep initial ratings consistent for legacy rows.
        conn.execute(text("UPDATE users SET blitz_rating = 1500 WHERE blitz_rating IS NULL OR blitz_rating <= 0"))
        conn.execute(text("UPDATE users SET rapid_rating = 1500 WHERE rapid_rating IS NULL OR rapid_rating <= 0"))
        try:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_login_name ON users (login_name)"))
        except Exception:
            pass


_ensure_schema_updates()

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    logger.info("WS: connection attempt from %s", ws.client)
    await ws_auth_and_loop(ws)


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    # process_update() does blocking HTTP calls to Telegram: keep them off the event loop.
    secret = config.telegram_webhook_secret
    if secret:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(got, secret):
            raise HTTPException(status_code=403, detail="bad_webhook_secret")
    else:
        logger.warning("Telegram webhook: TELEGRAM_WEBHOOK_SECRET is not set, request is not verified")
    data = await request.json()
    if isinstance(data, dict):
        await asyncio.to_thread(process_update, data)
    return {"ok": True}


@app.on_event("shutdown")
def _shutdown_workers():
    shutdown_uci_bot()


@app.on_event("startup")
async def _startup_tournaments():
    from . import tournaments
    from .pairing import close_orphaned_games, cleanup_loop

    # Live games exist only in memory: anything unfinished in the DB died with the previous process.
    n = close_orphaned_games()
    if n:
        logger.warning("startup: closed %d games left unfinished by previous process", n)
    asyncio.create_task(tournaments.scheduler_loop())
    asyncio.create_task(cleanup_loop())


def current_user_id(request: Request) -> str:
    """
    REST auth: `Authorization: tma <Telegram.WebApp.initData>`.
    Local debug only (DEBUG=1 and no bot token): `X-Debug-Uid` header or `telegram_id` query param.
    """
    header = request.headers.get("Authorization", "")
    if header.startswith("tma "):
        user = validate_init_data(header[4:].strip())
        if user and user.get("id") is not None:
            return str(int(user["id"]))
        raise HTTPException(status_code=401, detail="bad_init_data")
    if config.debug and not config.telegram_bot_token:
        raw = request.headers.get("X-Debug-Uid") or request.query_params.get("telegram_id")
        try:
            if raw:
                return str(int(raw))
        except ValueError:
            pass
    raise HTTPException(status_code=401, detail="auth_required")


LOGIN_RE = re.compile(r"^[A-Za-z0-9_.-]{1,20}$")
_analysis_rate_window_sec = 5.0
_analysis_rate_limit = 20
_analysis_rate_by_client: dict[str, deque[float]] = {}


def _check_analyze_rate_limit(client_key: str) -> None:
    now = time.monotonic()
    if len(_analysis_rate_by_client) > 10000:
        # Drop idle keys so the limiter itself cannot grow without bound.
        for k in [k for k, v in _analysis_rate_by_client.items() if not v or now - v[-1] > _analysis_rate_window_sec]:
            _analysis_rate_by_client.pop(k, None)
    q = _analysis_rate_by_client.setdefault(client_key, deque())
    while q and (now - q[0]) > _analysis_rate_window_sec:
        q.popleft()
    if len(q) >= _analysis_rate_limit:
        raise HTTPException(status_code=429, detail="analyze_rate_limited")
    q.append(now)


@app.get("/api/profile")
def get_profile(user_id: str = Depends(current_user_id)):
    with SessionLocal() as db:
        user = db.get(models.User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="user_not_found")
        from .pairing import bot_campaign_snapshot_for_db_user

        snap = bot_campaign_snapshot_for_db_user(user)
        beaten = tuple(snap.get("beaten") or [])
        allowed = list(snap.get("allowed_elos") or BOT_CAMPAIGN_ELOS)
        return {
            "user_id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "login_name": user.login_name,
            "is_anonymous": bool(user.is_anonymous),
            "blitz_rating": int(user.blitz_rating),
            "rapid_rating": int(user.rapid_rating),
            "games_played": int(user.games_played),
            "bot_campaign_beaten": list(beaten),
            "bot_campaign_allowed_elos": allowed,
            "bot_campaign_levels": list(BOT_CAMPAIGN_ELOS),
        }


@app.post("/api/login/register")
async def register_login(request: Request, user_id: str = Depends(current_user_id)):
    payload = await request.json()
    login_name = str(payload.get("login_name", "")).strip()
    if not LOGIN_RE.match(login_name):
        raise HTTPException(status_code=400, detail="invalid_format")
    with SessionLocal() as db:
        user = db.get(models.User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="user_not_found")
        exists = db.query(models.User).filter(models.User.login_name == login_name, models.User.id != user_id).first()
        if exists:
            raise HTTPException(status_code=409, detail="already_taken")
        user.login_name = login_name
        user.is_anonymous = False
        db.commit()
        return {"ok": True, "login_name": login_name}


@app.get("/api/history")
def get_history(limit: int = 30, user_id: str = Depends(current_user_id)):
    cap = max(1, min(limit, 100))
    with SessionLocal() as db:
        rows = (
            db.query(models.GameRecord)
            .filter((models.GameRecord.white_id == user_id) | (models.GameRecord.black_id == user_id))
            .order_by(models.GameRecord.created_at.desc())
            .limit(cap)
            .all()
        )
        out = []
        for g in rows:
            color = "white" if g.white_id == user_id else "black"
            opp = g.black_username if color == "white" else g.white_username
            out.append(
                {
                    "game_id": g.id,
                    "created_at": g.created_at.isoformat() if g.created_at else None,
                    "time_control": g.time_control_key,
                    "color": color,
                    "opponent": opp,
                    "result": g.result,
                    "result_reason": g.result_reason,
                }
            )
        return {"items": out}


@app.get("/api/tournaments/history")
def get_tournaments_history(limit: int = 30, user_id: str = Depends(current_user_id)):
    from . import tournaments

    cap = max(1, min(limit, 100))
    return {"items": tournaments.user_tournament_history(user_id, cap)}


@app.get("/api/analyze")
async def analyze_position(fen: str, user_id: str = Depends(current_user_id)):
    fen = (fen or "").strip()
    if not fen:
        raise HTTPException(status_code=400, detail="fen_required")
    from .pairing import get_active_game_for_user

    active = get_active_game_for_user(user_id)
    if active and not active.is_bot_game:
        # No engine help during a live game against a human.
        raise HTTPException(status_code=403, detail="game_in_progress")
    _check_analyze_rate_limit(user_id)
    try:
        return await analyze_fen_light(fen)
    except Exception as e:
        logger.warning("analyze failed: %s", e)
        raise HTTPException(status_code=500, detail="analyze_failed")


# Статика фронтенда (для разработки)
frontend_path = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_path.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
