# AGENTS.md

This file is a compact operational guide for AI agents working in `phonechess`.

## Project Snapshot

- Product: Telegram Mini App for online chess.
- Stack: FastAPI backend (`backend/app`), vanilla JS frontend (`frontend`).
- Runtime model: one web app serves UI, API, and WebSocket (`/ws`).
- Primary language in UI/content: Russian (current implementation).
- Target devices: smartphones first; desktop/tablet support is not a goal.

## Repository Layout

- `backend/app/main.py` - FastAPI app, routes, static mounting.
- `backend/app/ws_handlers.py` - WebSocket event handling/auth/game flow.
- `backend/app/pairing.py` - matchmaking queues by time control.
- `backend/app/game.py` - game state, move application, clocks/results.
- `frontend/index.html` - single-page shell for lobby/game.
- `frontend/app.js` - UI state, board rendering, WS client protocol.
- `frontend/styles/main.css` - mobile-first styling.
- `frontend/pieces/Chess_Pieces_Sprite.svg` - piece sprite sheet.
- `README.md` - local run and base deploy notes.
- `DEPLOY_DOCKER.md`, `DEPLOY_SUBDOMAIN.md`, `HOSTING.md` - deploy/infra docs.
- `PROJECT_PLAN.md` - product requirements and milestones.

## Core Functional Expectations

- Two-player realtime game over WebSocket.
- Strict legal move validation.
- Time controls from lobby: `3+0`, `3+2`, `5+0`, `5+3`, `10+0`, `15+10`.
- Board orientation must match player color by default:
  - white player: white pieces at bottom;
  - black player: black pieces at bottom.
- Manual board flip remains available (`Повернуть доску` button).
- Move input supports both:
  - tap-select + tap-target;
  - drag-and-drop.

## Frontend Conventions

- Keep frontend dependency-free unless explicitly requested.
- Preserve mobile-first layout and touch behavior.
- Avoid expensive DOM reflows; board is re-rendered from FEN state.
- Piece drag UX:
  - drag may start from any point in the piece square;
  - drag preview should show only the piece silhouette/sprite.

## Backend Conventions

- Keep WS protocol payloads stable and backward compatible when possible.
- Auth is based on Telegram WebApp `initData` (with debug fallback modes).
- Matchmaking and game updates should be resilient to reconnects.
- Do not silently alter time-control semantics.

## Local Development

From repo root:

1. Backend setup:
   - `cd backend`
   - `python -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. Run:
   - debug/non-Telegram: `DEBUG=1 uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
   - Telegram mode: set `TELEGRAM_BOT_TOKEN` and run uvicorn.
3. Open:
   - app: `http://localhost:8000/`
   - health: `http://localhost:8000/health`

## Deployment Notes

- Canonical GitHub repo: `https://github.com/egor-belikov/phonechess`.
- Standard server deploy uses Docker Compose (`docker compose build && docker compose up -d`).
- Production entrypoint domain is expected to be `https://chess.apichatpong.online/`.
- For reverse proxy, WebSocket upgrade headers are mandatory.

## Agent Working Rules

- Prefer minimal, targeted edits over broad refactors.
- Keep Russian UI labels consistent unless asked for i18n changes.
- If changing WS messages, update both sender and receiver code paths.
- After frontend logic updates, verify at least:
  - white orientation;
  - black orientation;
  - drag-and-drop still sends legal move payload.
- Do not commit secrets (`.env`, tokens).
