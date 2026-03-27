# AGENTS.md

This file is the operational guide for AI agents working in `phonechess`.

## Project Snapshot

- Product: Telegram Mini App for online chess.
- Stack: FastAPI backend (`backend/app`), vanilla JS frontend (`frontend`).
- Runtime model: one web app serves UI, API, and WebSocket (`/ws`).
- Primary language in UI/content: Russian (current implementation).
- Target devices: smartphones first; desktop/tablet support is not a goal.
- Current stage: playable realtime PvP prototype with mobile-first Lichess-like UI.

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
- `scripts/update_build_meta.py` - updates build metadata + asset version tags.
- `scripts/deploy.sh` - one-command release: build-meta update, commit/push, VPS deploy.

## Current Implemented Features (2026-03-27)

- Matchmaking by time controls: `3+0`, `3+2`, `5+0`, `5+3`, `10+0`, `15+10`.
- Realtime game via WebSocket with legal move validation (python-chess).
- Per-player board orientation by color; manual flip button remains.
- Clocks with low-time styling (`<20s`) and tenths.
- Last-move highlight, check highlight, move list with move time.
- Move input:
  - tap-select + tap-target;
  - desktop drag-and-drop;
  - touch drag on mobile.
  - legal-move dots are shown not only on tap/touch select, but also while holding a piece during desktop drag.
- Premove queue (unlimited):
  - can be queued while waiting for opponent move;
  - executes only if legal in resulting position;
  - if first queued premove becomes illegal, whole premove chain is cleared;
  - premove execution is sent with `premove: true` (0ms move cost on backend).
- Premove visualization:
  - colored markers with per-step numbering;
  - preview board position reflects chained premoves.
  - text hint with premove queue count under bottom clock is intentionally hidden (board markers stay as the source of truth).
- Premove target selection while waiting for opponent:
  - target hints are computed from piece movement rules on the preview position (current board + queued premoves), not only from currently legal chess.js moves;
  - this allows chaining intent-driven premoves like "pawn push, then potential capture from the new square";
  - final legality is still validated at execution time, and illegal first premove still clears full queue.
- Pawn promotion UX:
  - for both regular moves and premoves, promotion no longer auto-queens immediately;
  - when a pawn reaches last rank, a semi-transparent board-overlay picker with figure cells (`Q/R/B/N`) appears and requires an extra tap;
  - tapping outside picker cancels promotion choice without sending/queuing a move.
- Game-end UX:
  - end-of-game modal with reason text and `Вернуться в лобби` action.
  - opponent disconnect banner with reconnect grace-period notice.
- Draw handling (tournament-oriented):
  - draw offer button appears from move 15 onward;
  - offer frequency limit: not more than once per 5 moves per player;
  - offer cannot be cancelled by the offering side; opponent move counts as rejection;
  - opponent can accept by pressing the same `Ничья?` control.
- Draw claims and automatic draw rules:
  - player claim routes: threefold repetition and 50-move rule;
  - automatic draw routes: fivefold repetition and 75-move rule;
  - stalemate and insufficient-material draws include explicit reason codes/details.
- Build info badge at bottom: `version + deployed_at`.
- Pairing safety:
  - duplicate queue entries for same `user_id` are ignored;
  - self-match for the same `user_id` is forbidden;
  - if `matched` event cannot be delivered to both players, pairing is rolled back and both are re-queued.
  - stale WebSocket disconnect from an old replaced connection must not evict the new active connection of the same `user_id`.
- WS reconnect UX:
  - server may close old duplicate connection with `4000` when a new one for same user is accepted;
  - frontend treats `4000` as reconnect state (not a hard error banner) and retries quickly.

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
- `apply_move(..., is_premove=True)` must keep `elapsed_ms = 0`.

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

## Build Metadata and Cache Busting

- Before deploy, run from repo root:
  - `python3 scripts/update_build_meta.py`
- Script updates:
  - `frontend/build-meta.json` (`version`, `deployed_at`);
  - cache-busting tags in `frontend/index.html` for `app.js` and `main.css`;
  - fallback text in `#build-info`.
- Frontend reads `/build-meta.json` with `cache: no-store`.
- One-command path:
  - `bash scripts/deploy.sh "Your detailed commit message"`

## Deployment Notes

- Canonical GitHub repo: `https://github.com/egor-belikov/phonechess`.
- Standard server deploy uses Docker Compose (`docker compose build && docker compose up -d`).
- Production entrypoint domain is expected to be `https://chess.apichatpong.online/`.
- For reverse proxy, WebSocket upgrade headers are mandatory.
- Server used in active workflow: SSH alias `egorvps`, path `/root/my_projects/phonechess`.
- For browser-based testing without Telegram, server `.env` should keep `DEBUG=1`.

## Agent Working Rules

- Prefer minimal, targeted edits over broad refactors.
- Keep Russian UI labels consistent unless asked for i18n changes.
- If changing WS messages, update both sender and receiver code paths.
- After frontend logic updates, verify at least:
  - white orientation;
  - black orientation;
  - drag-and-drop still sends legal move payload.
- For premove changes, additionally verify:
  - queue while out-of-turn works;
  - illegal first premove clears full queue;
  - move list shows premove move time as `0:00`.
- Do not commit secrets (`.env`, tokens).

## Latest Commit Details (2026-03-27)

- Scope:
  - private invite flow via Telegram deep-link + persistent game/invite storage + replay/analyze mode foundation.
- Files changed:
  - `backend/app/db.py`
  - `backend/app/models.py`
  - `backend/requirements.txt`
  - `backend/app/config.py`
  - `backend/app/main.py`
  - `backend/app/pairing.py`
  - `backend/app/ws_handlers.py`
  - `backend/app/telegram_bot.py`
  - `frontend/index.html`
  - `frontend/styles/main.css`
  - `frontend/app.js`
  - `frontend/i18n/en.json`
  - `frontend/i18n/ru.json`
  - `frontend/i18n/*.json` (30-language set: added/backfilled keys for private invites + analysis panel)
  - `AGENTS.md`
- Behavior changes:
  - backend now initializes SQLAlchemy + PostgreSQL models on startup (`users`, `games`, `game_moves`, `private_invites`) and persists active game snapshots/moves/results.
  - user registration/start-state is stored in DB; `/start` webhook marks `has_started_bot=true` for Telegram notifications.
  - new WS flow:
    - `create_private_invite` -> generates `private_<key>` deep-link;
    - `open_private_link` -> resolves pending/active/finished invite and returns either `matched` or `private_game_history`.
  - private invite links are stable: pending invite becomes active game link; after finish, same key resolves to history payload.
  - frontend lobby has `Приватная игра` action with time-control pick + Telegram share-link open.
  - replay mode added for finished/private history with move navigation buttons (`|<`, `<`, `>`, `>|`).
  - client-side Stockfish panel added (web worker/CDN) with start/stop, eval and PV line, using current replay position.
  - i18n dictionaries expanded with private-invite + analysis keys and backfilled across all 30 supported locales.
- Safety invariants preserved:
  - backend remains the source of truth for move legality;
  - premove execution still sends `premove: true` and keeps existing chain-clear semantics on illegal first premove.
