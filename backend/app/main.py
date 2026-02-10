"""
PhoneChess API и WebSocket.
"""
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_config
from .ws_handlers import ws_auth_and_loop

app = FastAPI(title="PhoneChess API")
config = get_config()

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
    await ws_auth_and_loop(ws)


# Статика фронтенда (для разработки)
frontend_path = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_path.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
