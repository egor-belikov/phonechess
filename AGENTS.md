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
  - private invite step-1 overhaul: bot-mediated invite handoff (`/start private_<key>` -> bot message with `Начать игру` button).
- Files changed:
  - `backend/app/pairing.py`
  - `backend/app/telegram_bot.py`
  - `backend/app/ws_handlers.py`
  - `AGENTS.md`
- Behavior changes:
  - generated private invite link now points to bot launch URL (`https://t.me/<bot>?start=private_<key>`) instead of direct `startapp` link;
  - bot now parses `/start private_<key>` payload and sends a dedicated message with `Начать игру` WebApp button targeting `.../?startapp=private_<key>`;
  - frontend share flow keeps sending invite link via Telegram share, but this link now consistently opens bot-first handshake;
  - creator notification button remains a WebApp button and now targets app URL with explicit `startapp=private_<key>` parameter.
- Safety invariants preserved:
  - private invite key format and backend waiting-room/match activation lifecycle are unchanged;
  - invite consumption/validation still happens only on backend via `open_private_link`/`join_private_invite`.

## Latest Iteration Details (2026-03-27: Logins & Profiles)

- Scope:
  - optional login/profile foundation with history and strict single active client policy.
- Files changed:
  - `backend/app/models.py`
  - `backend/app/main.py`
  - `backend/app/pairing.py`
  - `backend/app/ws_handlers.py`
  - `frontend/index.html`
  - `frontend/styles/main.css`
  - `frontend/app.js`
  - `frontend/i18n/ru.json`
  - `frontend/i18n/en.json`
  - `AGENTS.md`
- Behavior changes:
  - added user profile fields: `is_anonymous`, `login_name`, `blitz_rating`, `rapid_rating`, `games_played`;
  - added safe runtime schema update path for existing `users` table columns/defaults;
  - added API endpoints:
    - `GET /api/profile?telegram_id=...`
    - `POST /api/login/register` (`telegram_id`, `login_name`, regexp validation + unique check)
    - `GET /api/history?telegram_id=...`
  - ratings and games played are updated automatically on game finish for blitz/rapid pools (Elo-like update);
  - WS now rejects second concurrent active client for same `user_id` with explicit close reason (`4009`);
  - frontend now has profile modal, optional login registration form, history list, and replay open from history;
  - i18n keys added for login/profile UX and second-session denial message.
- Safety invariants preserved:
  - anonymous users can still play and create private invites;
  - existing real-time game flow and private invite waiting-room lifecycle remain intact.

## Latest Hotfix Details (2026-03-27: Initial Ratings = 1500)

- Scope:
  - enforce stable initial ratings (`1500`) for both blitz and rapid across new and legacy users.
- Files changed:
  - `backend/app/main.py`
  - `backend/app/pairing.py`
  - `AGENTS.md`
- Behavior changes:
  - startup schema safety routine now backfills legacy/invalid rating values to `1500`:
    - `blitz_rating IS NULL OR blitz_rating <= 0 -> 1500`
    - `rapid_rating IS NULL OR rapid_rating <= 0 -> 1500`
  - user upsert path now self-heals bad rating values for existing users on activity:
    - if blitz/rapid rating is `NULL` or `<= 0`, value is reset to `1500`.
- Safety invariants preserved:
  - Elo update logic and game result processing are unchanged;
  - anonymous flow, login flow, and private invite flow are unchanged.

## Latest UX Hotfix Details (2026-03-27: Stable Tap-Select on Mobile)

- Scope:
  - fix touch input UX in Telegram mobile webview: stable one-tap piece selection with legal target markers, while preserving drag move input.
- Files changed:
  - `frontend/app.js`
  - `frontend/styles/main.css`
  - `PROJECT_PLAN.md`
  - `AGENTS.md`
- Behavior changes:
  - one-tap on own piece now pins selection (does not instantly clear), shows legal target dots, and allows:
    - tap on target square to move;
    - tap same selected piece to cancel selection;
    - tap elsewhere to clear or reselect according to existing click logic.
  - drag input is kept as-is for desktop and touch drag on mobile.
  - legal-target dots now have two visual modes:
    - `drag`: more transparent marker;
    - `tap`: brighter marker.
  - selection state management was centralized (`clearSelection` / `selectSquare`) to prevent touch flicker/race.
  - `PROJECT_PLAN.md` roadmap section synced to current implementation state.
- Safety invariants preserved:
  - move legality validation and promotion flow are unchanged;
  - premove semantics are unchanged;
  - private invite/game lifecycle is unchanged.

## Latest Gameplay Update (2026-03-27: Bot Mode, Start-Abort, Rematch, Bot Notifications)

- Scope:
  - add non-profile bot games, fix move-time drift, add unstarted-game abort flow with private rematch voting, and restore Telegram bot game-finish notifications.
- Files changed:
  - `backend/app/pairing.py`
  - `backend/app/ws_handlers.py`
  - `backend/app/telegram_bot.py`
  - `frontend/index.html`
  - `frontend/app.js`
  - `frontend/i18n/ru.json`
  - `frontend/i18n/en.json`
  - `PROJECT_PLAN.md`
  - `AGENTS.md`
- Behavior changes:
  - **Bot mode**:
    - new lobby action starts `start_bot_game` (default `3+0`);
    - bot is intentionally very weak (deterministic weak move policy) and moves exactly after 1 second delay;
    - bot games are in-memory only (not written to profile/history/rating);
    - draw offer flow is disabled for bot games, resign flow remains.
  - **Clock and move-time fixes**:
    - `subscribe_game` no longer materializes/reset clocks, fixing `0ms` move-time artifacts in move list;
    - white clock now starts only after black’s first move;
    - white increment is applied starting from white’s second move;
    - no-clock side support added for bot games (human can have unlimited think time).
  - **Unstarted-game abort**:
    - after pairing, a 60-second watchdog waits for both first moves (white and black);
    - if either side misses first move, game auto-aborts with explicit reason (`aborted_unstarted`) and result modal text.
  - **Private rematch flow**:
    - after unstarted abort, both players get rematch availability;
    - each player can vote for rematch; when both voted, a new private game is started immediately with same pair.
  - **Telegram finish notifications**:
    - end-of-game bot messages are sent once per game with result/reason/details and SAN move line to users who started bot.
- Safety invariants preserved:
  - base matchmaking, private-invite waiting room, and resign confirmation UX remain compatible with existing clients;
  - persistent DB entities for regular games remain unchanged.

## Latest Engine Update (2026-03-27: UCI Stockfish Worker for Bot Mode)

- Scope:
  - switch bot mode from placeholder move picker to real UCI engine worker with weak Stockfish settings.
- Files changed:
  - `backend/app/uci_bot.py` (new)
  - `backend/app/ws_handlers.py`
  - `backend/app/main.py`
  - `backend/app/config.py`
  - `Dockerfile`
  - `AGENTS.md`
- Behavior changes:
  - server now runs Stockfish as UCI subprocess for bot games;
  - dedicated async worker path `pick_move_weak_uci(...)` is used for bot move selection;
  - engine is configured to weakest practical level:
    - `Skill Level = 0`
    - `UCI_LimitStrength = true`
    - `UCI_Elo = 1320`
    - `Threads = 1`, `Hash = 16`
  - bot still moves with fixed 1-second delay in WS flow;
  - `STOCKFISH_PATH` config added (default `/usr/games/stockfish`);
  - Docker image now installs `stockfish` package;
  - app shutdown now gracefully closes UCI engine process.
- Safety invariants preserved:
  - if UCI engine fails, worker falls back to first legal move (no game flow break);
  - bot games remain non-profile and non-rating.

## Latest Analysis Update (2026-03-27: Server-side Replay Analysis Cache)

- Scope:
  - fix broken Stockfish-in-browser analysis in replay mode by adding lightweight server-side analysis with cache.
- Files changed:
  - `backend/app/uci_bot.py`
  - `backend/app/main.py`
  - `backend/app/ws_handlers.py`
  - `frontend/app.js`
  - `AGENTS.md`
- Behavior changes:
  - new API endpoint: `GET /api/analyze?fen=...`
  - server performs short UCI analysis (`depth=8`, `time=0.05`) and returns:
    - `score_type`: `cp|mate`
    - `score`: numeric value
    - `pv`: best line in UCI list
  - in-memory TTL cache by FEN (120s) reduces repeated CPU load in replay scrubbing.
  - frontend analysis now requests server analysis first; if failed, falls back to local Stockfish worker.
  - removed erroneous finish-notify call from draw-offer branch (non-terminal event).
- Safety invariants preserved:
  - game flow and move validation are unchanged;
  - analysis endpoint is read-only and does not modify game state.

## Latest Protection Update (2026-03-27: Analyze Rate Limit + Client Debounce)

- Code release commit: `c19870d` — backend rate limit + frontend debounce for `/api/analyze`.
- Documentation follow-up commit: `b17ffc0` — expanded release notes in this file (implementation details, ops note).
- Production `build-meta.json` (served at `/build-meta.json`): `version` is the git short hash at deploy; `deployed_at` and `asset_tag` are stamped by `scripts/update_build_meta.py` on each VPS deploy — use the live endpoint for current values (do not treat examples in this file as authoritative). Commit lineage for this feature: application changes in `c19870d`; AGENTS detail commit `b17ffc0`; AGENTS build-meta lineage documentation `5fb4b0b` and follow-up `c8eba46`.
- Scope:
  - protect server analysis endpoint from replay-scrub bursts and abusive request rates.
- Files changed:
  - `backend/app/main.py`
  - `frontend/app.js`
  - `AGENTS.md`
- Behavior changes:
  - `/api/analyze` now applies in-memory per-client rate limiting:
    - key: `Request.client.host` (falls back to `"unknown"` if missing)
    - implementation: sliding window with `collections.deque` of request timestamps per host
    - window: 5 seconds
    - limit: 20 requests per client host in window
    - on exceed: HTTP `429` (`analyze_rate_limited`)
  - frontend analysis requests are debounced (`180ms`) when replay index changes (`setReplayIndex` → `scheduleAnalysis` instead of immediate `analyzeCurrentPosition`).
  - analysis toggle-on uses the same debounced path; `stopAnalysis()` clears the pending debounce timer and stops local Stockfish worker as before.
- Safety invariants preserved:
  - no changes to move validation, game state transitions, or rating logic;
  - analysis remains read-only.
- Ops note:
  - immediately after `docker compose up -d`, `/health` can briefly reset connections; retry after a few seconds if automated checks fail.

## Bot game: no disconnect timeout on bot turn (2026-03-27)

- Release commit: `432c95b`.
- Bug: after each human move, `make_move` called `_maybe_start_disconnect_task(g, turn_user_id(g))`. On the bot’s turn that user id is `bot_user_id`; the bot never has a WebSocket, so `manager.has_user` was false and a 10s grace timer started — the bot was forfeited as if offline (`disconnect_turn_timeout`).
- Fix: in `backend/app/ws_handlers.py`, skip starting (and completing) disconnect-forfeit logic when the “disconnected” participant is `g.bot_user_id` in a bot game.
- Human disconnect handling during bot games is unchanged (only the real human id is timed).
