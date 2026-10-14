# PhoneChess — спецификация (as-is)

Документ описывает систему **такой, какая она есть в коде** на коммите `1395c72`.
Где поведение расходится с `AGENTS.md` или выглядит как баг — помечено **⚠**.

---

## 1. Продукт

Telegram Mini App для онлайн-шахмат, только смартфоны (десктоп/планшет блокируются заглушкой `#mobile-only-block`).

Режимы:

| Режим | Рейтинг | Пишется в БД | Часы |
|---|---|---|---|
| Пул (матчмейкинг) | да | да | да |
| Приватная игра по ссылке | да | да | да |
| Реванш приватной игры | да | да | да |
| Турнир Swiss / KO (UI скрыт) | да | да | да |
| Игра с ботом (кампания) | нет (только прогресс кампании) | нет | нет (∞ у обоих) |

Контроли времени (`constants.py`): `3+0`, `3+2`, `5+0`, `5+3` — блиц; `10+0`, `15+10` — рапид.

---

## 2. Архитектура

```
Telegram client ──► WebApp (frontend/, статика) ──WS /ws──► FastAPI (uvicorn, 1 процесс)
                                                  ──REST /api/*──►      │
Telegram Bot API ◄── urllib (sync) ───────────────────────────────────┤
Telegram ──POST /telegram/webhook──────────────────────────────────────┤
                                                    Stockfish (UCI subprocess, 1 шт.)
                                                    PostgreSQL / SQLite (SQLAlchemy sync)
```

- **Один процесс, всё состояние живых партий в памяти** (`pairing._games`, очереди, турниры, таймеры). Рестарт = все текущие партии потеряны (при старте они закрываются в БД как `*` / `aborted_server_restart`). Горизонтальное масштабирование невозможно.
- Stockfish 19 (официальная universal-сборка), два процесса: ходы бота и анализ.
- БД — только журнал: пользователи, завершённые/идущие партии, ходы, инвайты, турниры.
- Схема: `Base.metadata.create_all` + ручные `ALTER TABLE` в `main._ensure_schema_updates` (миграций нет).
- Фронтенд: `index.html` + один `app.js` (~2.5k строк, IIFE) + `main.css`; зависимости с CDN: `telegram-web-app.js`, `chess.js 0.10.3`.

### Модули бэкенда

| Файл | Ответственность |
|---|---|
| `main.py` | FastAPI app, REST, webhook, автомиграции, статика |
| `auth.py` | Проверка `initData` (HMAC-SHA256) |
| `ws_handlers.py` | Протокол WS, таймеры (abort, disconnect, ход бота), уведомления |
| `ws_manager.py` | Реестр соединений, рассылки |
| `pairing.py` | Модель `Game`, очереди, ходы, часы, результат, Elo, инвайты, кампания |
| `tournaments.py` | Swiss/KO рантайм + планировщик |
| `uci_bot.py` | Stockfish: ход бота и анализ позиции |
| `telegram_bot.py` | Bot API: /start, сообщения, редактирование итогов |
| `game.py` | Пустой реэкспорт (мёртвый модуль) |

---

## 3. Аутентификация и идентичность

- `user_id = str(telegram_id)`. Отдельного внутреннего id нет.
- WS: первое сообщение обязано быть `{"type":"auth","init_data":...}`.
  - Валидный `initData` → пользователь upsert-ится в `users`.
  - `DEBUG=1`, пустой `TELEGRAM_BOT_TOKEN` и пустой `init_data` → берётся `debug_uid` от клиента (только локальная разработка).
  - `DEBUG=1` и нет токена бота → `initData` парсится без проверки подписи.
  - Невалидно → close `4003`; первое сообщение не `auth` → `4001`.
- **Одна активная сессия на пользователя**: новое соединение вытесняет старые (старым — close `4010`). Клиент на `4010` не переподключается сам, а делает это, когда его окно снова становится активным.
- После `auth`, если есть незавершённая партия, сервер шлёт `matched` с `resumed: true`.
- `initData` старше `INIT_DATA_MAX_AGE_SEC` (24 ч) отклоняется (WS `4003`, REST `401`).
- REST (`/api/*`) аутентифицирован заголовком `Authorization: tma <initData>`; в локальной отладке — `X-Debug-Uid`.

---

## 4. WebSocket-протокол

Все сообщения — JSON с полем `type`.

### Клиент → сервер

| type | Поля | Поведение |
|---|---|---|
| `auth` | `init_data`, `debug_uid?` | см. §3 |
| `ping` | `client_ts` | → `pong` |
| `join_queue` | `time_control` | в очередь; при паре → `matched` обоим |
| `leave_queue` | `time_control?` | из одной/всех очередей |
| `start_bot_game` | `time_control`, `bot_elo` | проверка кампании → `matched` или `bot_start_denied` |
| `create_private_invite` | `time_control` | → `private_invite_created` (+ сообщение в бот) |
| `open_private_link` | `invite_key` | waiting room / активация / `matched` / история |
| `subscribe_game` | `game_id` | → `game_state` (только участнику) |
| `make_move` | `game_id`, `from`, `to`, `promotion?`, `premove?` | → `game_update` обоим |
| `resign` | `game_id` | → `game_update` |
| `offer_draw` | `game_id` | с 30-го полухода, не чаще 1 раза в 10 полуходов на игрока → `draw_offer_state` |
| `respond_draw` | `game_id`, `action:"accept"` | → `game_update` (ничья) |
| `claim_draw` | `game_id`, `claim_type` | **no-op** (claim отключён, ничьи автоматические) |
| `rematch_request` | `game_id` | только `is_private`; оба голоса → новая партия, цвета меняются. ⚠ Нет проверки, что партия закончена, и голосовать можно повторно |
| `open_game_history` | `game_id` | → `private_game_history` (только участнику) |
| `join_tournament_waiting` / `leave_tournament_waiting` | `format`, `time_control` | очередь турнира |

### Сервер → клиент

`queue_counts`, `matched`, `game_state`, `game_update`, `draw_offer_state`, `opponent_connection`
(`disconnected`/`reconnected`), `private_invite_created|waiting|invalid|taken`, `private_game_history`,
`rematch_offer_available`, `rematch_vote_update`, `bot_start_denied`, `bot_campaign`,
`tournament_waiting_ack`, `tournament_finished`, `pong`.

`game_update` — полный снимок: `fen`, `white_remaining_ms`, `black_remaining_ms`, `san`, `move_time_ms`,
`from`, `to`, `result`, `result_reason`, `result_detail`, `draw_offer_*`, `is_bot_game?`, `bot_elo?`, `bot_campaign?`.

Отклонённый `make_move` → `move_rejected` (`game_id`, `from`, `to`, `premove`, `fen`, `result`). Попытка начать новую активность во время партии → `action_denied` + `matched` (`resumed`). Прочие ошибки игнорируются.

---

## 5. Жизненный цикл партии

### 5.1 Создание
- Пул: FIFO по контролю; цвет случайный; партия сразу пишется в `games`. Если `matched` не доставлен хоть одному — партия удаляется из памяти, оба игрока возвращаются в начало очереди.
- Запускается **таймер отмены 60 с**: если за 60 с не сделано 2 полухода → `aborted_unstarted` (ничья, без рейтинга) + `rematch_offer_available`.

### 5.2 Часы
- Хранятся `*_remaining_ms` + `last_clock_at` (monotonic); живое значение считается при отдаче.
- Часы белых не идут до первого хода чёрных; часы чёрных не идут до первого хода белых.
- Инкремент: белым — со 2-го хода, чёрным — с 1-го.
- Время хода считается от начала хода (момент, зафиксированный **до** `materialize_live_clocks`).
- `premove: true` → возвращается не больше `PREMOVE_FREE_MS = 300` мс времени хода (настоящий премув = `0:00`, флагом нельзя остановить часы).
- Серверный таймер флага перевзводится после каждого хода и завершает партию в момент падения флага (`check_flag` → `finish_game_side_effects`).
- Бот-партии: часы не идут ни у кого; `move_time_ms` = реальное время (до 600 с) для отображения.

### 5.3 Окончание (`result_reason`)
| reason | Условие |
|---|---|
| `checkmate` | мат |
| `stalemate` | пат |
| `insufficient_material` | python-chess `is_insufficient_material` |
| `draw_claim_threefold` | троекратное повторение — **автоматически** |
| `draw_claim_fifty_move` | 50 ходов — **автоматически** |
| `draw_auto_fivefold`, `draw_auto_75move` | недостижимы (срабатывают ветки выше) |
| `timeout` | время ≤ 0 |
| `timeout_vs_insufficient` | время ≤ 0, но у соперника недостаточно материала для мата → ничья |
| `resign` | сдача |
| `draw_agreement` | ничья по соглашению |
| `disconnect_turn_timeout` | отключился в свой ход и не вернулся за 10 с. ⚠ В БД пишется `disconnect_forfeit` (переопределение только в WS-payload) |
| `aborted_unstarted` | см. 5.1 |

### 5.4 Дисконнект
- При потере последнего соединения сопернику уходит `opponent_connection: disconnected, grace_seconds: 10`.
- Если сейчас ход отключившегося — через 10 с поражение. Если не его ход — таймер стартует, когда до него дойдёт очередь.
- Пользователь удаляется из всех очередей (кроме турнирных листов ожидания).
- ⚠ При авторизации сервер **не сообщает** клиенту о его активной партии. Вернуться можно, только если клиент помнит `currentGameId` в памяти; перезапуск Mini App = потеря партии.
- ⚠ Сервер не мешает одному пользователю одновременно быть в партии, в очереди пула и в бот-партии.

### 5.5 После окончания
- Рейтинг (§7), `mark_invite_finished_by_game`, турнирный хук.
- Уведомление в Telegram (однократно): для приватной игры — редактирование двух стартовых сообщений, иначе — новое сообщение тем, кто запускал бота. Итог + SAN в `<pre>`.
- Клиент переходит в режим replay + анализ.
- Через 15 минут после окончания партия удаляется из памяти (история — в БД).
- ⚠ Бот-партии не пишутся в БД при ходах, но **пишутся** при `resign` и дисконнект-форфейте (`_persist_game_state` без проверки `is_bot_game`) — в истории появляются партии против `__bot_weak__`.

---

## 6. Приватные игры

1. `create_private_invite` → ключ (`token_urlsafe`, до 20 символов), запись `private_invites(status=pending)`, ссылка `https://t.me/<bot>?start=private_<key>`.
2. Бот на `/start private_<key>` отвечает кнопкой WebApp `?startapp=private_<key>`.
3. `open_private_link`: первый не-создатель становится `invited_user_id`; оба попадают в `_private_room_presence`.
4. Когда оба онлайн и в комнате → `activate_private_invite` → партия (создатель белыми), `status=active`.
5. По окончании `status=finished`; повторное открытие ссылки показывает историю.

---

## 7. Рейтинг

- Отдельно блиц и рапид, старт 1500, пол 100, Elo с **K=20** для всех, без provisional-периода.
- Применяется к пулу, приватным, реваншам и турнирным партиям; не применяется к `aborted_unstarted` и ботам.
- `games_played` растёт только в рейтинговых партиях.

---

## 8. Бот-кампания

- Уровни `BOT_CAMPAIGN_ELOS = 1100…2900` шаг 300.
- Анонимным (без логина) доступны все уровни; с логином — побеждённые + следующий.
- Победа над ботом сохраняется в `users.bot_campaign_beaten_json` (только неанонимным).
- ⚠ Если процесс Stockfish упал, `_engine` не пересоздаётся: бот навсегда играет `legal[0]`, анализ отдаёт 500.
- Ход: задержка 1 с + Stockfish `UCI_LimitStrength`, `UCI_Elo = clamp(level, engine.min..max)` (обычно ≥1320, т.е. уровень 1100 = 1320), время 20–200 мс. Один движок на весь сервер под глобальным `asyncio.Lock`.

---

## 9. Анализ

- `GET /api/analyze?fen=` — MultiPV 3, depth 14 / 0.42 с, кэш по FEN 120 с (без ограничения размера), лимит 20 запросов / 5 с на `request.client.host`.
- Использует тот же движок и тот же лок, что ход бота.
- Требует аутентификации; при незавершённой небот-партии → `403 game_in_progress`. Лимит — на пользователя. Кэш — LRU на 5000 позиций. Отдельный процесс Stockfish (ход бота не ждёт анализа).
- Клиент — дебаунс 180 мс при пролистывании.
- ⚠ За nginx в Docker `request.client.host` = IP шлюза/прокси (uvicorn не доверяет `X-Forwarded-For` без `--forwarded-allow-ips`) → один общий лимит на всех пользователей.
- ⚠ Можно анализировать позицию из идущей рейтинговой партии (встроенный читерский движок).

---

## 10. Турниры (бэкенд жив, UI скрыт CSS-классом)

- Очереди по формату × контролю. Планировщик раз в `TOURNAMENT_INTERVAL_SEC` (1800 с) запускает турнир, если набран порог.
- **Swiss**: ровно `SWISS_MIN_PLAYERS` (8) участников, `min(5, n-1)` туров, жадная пара по очкам/рейтингу, без байев, без Бухгольца (поле есть, всегда 0).
- **KO**: ровно 16, сетка 1–16, матч из 2 партий + тай-брейк (ничья в тай-брейке → побеждают чёрные), финал + матч за 3-е.
- Рантайм турниров только в памяти.
- ⚠ Для турнирных партий не запускается таймер отмены; `abort_unstarted_game` не вызывает турнирный хук → тур может зависнуть навсегда.
- ⚠ Офлайн-игроки не удаляются из листа ожидания турнира.
- ⚠ Жадная пара Swiss при отсутствии свободного соперника допускает повторную встречу.

---

## 11. REST API

| Метод | Путь | Описание |
|---|---|---|
| GET | `/health` | `{"status":"ok"}` |
| GET | `/api/profile?telegram_id=` | профиль + кампания |
| POST | `/api/login/register` | `{telegram_id, login_name}` — `^[A-Za-z0-9_.-]{1,20}$`, уникальный |
| GET | `/api/history?telegram_id=&limit=` | до 100 последних партий |
| GET | `/api/tournaments/history?telegram_id=` | места в турнирах |
| GET | `/api/analyze?fen=` | §9 |
| POST | `/telegram/webhook` | апдейты бота; при `TELEGRAM_WEBHOOK_SECRET` проверяется `X-Telegram-Bot-Api-Secret-Token` |
| GET | `/build-meta.json` | версия/дата деплоя |

---

## 12. Данные (БД)

`users`, `games`, `game_moves`, `private_invites`, `tournaments`, `tournament_participants`, `tournament_matches` (последняя не используется кодом). Внешних ключей от `games` к `users` нет.

---

## 13. Конфигурация

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_WEBAPP_URL`, `DATABASE_URL` (по умолчанию SQLite), `STOCKFISH_PATH`, `DEBUG`, `ALLOWED_ORIGINS` (по умолчанию `*`), `SWISS_MIN_PLAYERS`, `KO_MIN_PLAYERS`, `TOURNAMENT_INTERVAL_SEC`, `SWISS_MAX_ROUNDS`.

## 14. Деплой

Docker Compose (`app` + `postgres:16`; ⚠ порт `8000:8000` открыт на всех интерфейсах — в обход nginx/TLS; пароль БД по умолчанию `phonechess`), `scripts/deploy.sh`: коммит в `main` → push → ssh на VPS → `git pull` → `update_build_meta.py` → `docker compose build/up`. Тестов, CI, линтеров нет.

---

## 15. Известные дефекты и риски

Все пункты проверены по коду на `1395c72`. Приоритеты и план исправлений — в [`PLAN.md`](PLAN.md).

### Безопасность / честность игры
| # | Дефект | Где |
|---|---|---|
| S1 | ~~Флаг `premove` позволяет не тратить время~~ — **не подтвердилось**: часы списывал `materialize_live_clocks`. Реальный баг был другой: из-за него `move_time_ms` всех PvP- и бот-ходов был ≈0 (список ходов и БД). Исправлено, премув ограничен 300 мс | `pairing.apply_move` |
| S2 | ~~`DEBUG=1` + `debug_uid` → вход под любым `telegram_id`~~ — исправлено: `debug_uid` только без `TELEGRAM_BOT_TOKEN` | `ws_handlers.ws_auth_and_loop` |
| S3 | ✅ исправлено. Было: REST без аутентификации: `POST /api/login/register` меняет логин любого пользователя, `/api/profile`, `/api/history` читают чужие данные | `main.py` |
| S4 | ~~webhook без секрета~~ — исправлено: при заданном `TELEGRAM_WEBHOOK_SECRET` проверяется заголовок, иначе `403` | `main.telegram_webhook` |
| S5 | ~~Stored XSS в истории профиля~~ — исправлено: `escapeHtml()` | `app.js` |
| S6 | ✅ исправлено. Было: `auth_date` не проверяется → перехваченный `initData` действует вечно | `auth.py` |
| S7 | ✅ исправлено. Было: `/api/analyze` доступен для позиций из идущих партий | `main.analyze_position` |
| S8 | Порт 8000 опубликован наружу, CORS `*` + `allow_credentials` | `docker-compose.yml`, `main.py` |

### Корректность игры
| # | Дефект | Где |
|---|---|---|
| G1 | ✅ исправлено. Было: нет серверного флага: если у игрока кончилось время, а он не ходит и не отключается, партия висит вечно | `pairing.materialize_live_clocks` вызывается только на ход/дисконнект |
| G2 | ✅ исправлено. Было: `timeout` при недостаточном материале у соперника = победа (должна быть ничья) | `pairing._apply_result`, `materialize_live_clocks` |
| G3 | ✅ исправлено. Было: после перезапуска Mini App нельзя вернуться в идущую партию: сервер не присылает активную партию при `auth` | `ws_auth_and_loop` |
| G4 | ✅ исправлено (вытеснение, `4010`). Было: `4009` при переподключении, пока сервер не заметил смерть старого сокета (до ~40 с у uvicorn); клиент на `4009` не ретраит → игрок заперт, его часы идут | `ws_auth_and_loop`, `app.js` `onclose` |
| G5 | ✅ исправлено. Было: один пользователь может одновременно быть в партии и в очереди / бот-партии | `join_queue`, `create_bot_game` |
| G6 | ✅ исправлено. Было: `rematch_request` без проверки `g.result` → реванш во время партии; повторные голоса после реванша создают ещё партии | `ws_handlers` |
| G7 | ✅ исправлено. Было: принятие ничьей (`respond_draw`) не вызывает `_notify_game_finished_once` → нет итогового сообщения в Telegram | `ws_handlers` |
| G8 | Премув превращения без выбора фигуры уходит как `q` (расходится с UX-описанием в `AGENTS.md`) | `app.js` `tryExecutePremoves` |
| G9 | ✅ исправлено. Было: бот-партии попадают в БД/историю при сдаче и дисконнекте | `resign_game`, `forfeit_disconnected_player` |
| G10 | ✅ исправлено. Было: `disconnect_turn_timeout` в WS, `disconnect_forfeit` в БД | `ws_handlers._schedule_disconnect_forfeit` |
| G11 | Турниры: нет таймера отмены, abort не двигает тур, офлайн-игроки в листе ожидания | `tournaments.py` |
| G12 | ✅ исправлено. Было: упавший Stockfish не перезапускается | `uci_bot._ensure_engine` |

Дополнительно найдено и исправлено на этапе 1:
- флаг, обнаруженный при ходе или по таймеру дисконнекта, **не записывался в БД и не менял рейтинг**;
- клиентская `requestGameStateSync(0)` (после переподключения и при возврате в приложение) из-за троттлинга никогда не отправляла запрос.

### Надёжность / производительность
| # | Дефект |
|---|---|
| R1 | ◐ частично: Telegram-вызовы вынесены в потоки; запись в БД по-прежнему синхронная (быстрая на Postgres). Было: синхронные SQLAlchemy-коммиты на каждый ход и синхронный `urllib` к Telegram (таймаут 10 с) внутри event loop — блокируют все партии |
| R2 | ✅ исправлено (выселение через 15 мин, LRU-кэш анализа). Было: `_games`, `_result_notified_games`, `_rematch_votes`, `_analysis_cache` растут без ограничений |
| R3 | ◐ частично: «вечные» партии закрываются при старте; сами партии рестарт по-прежнему не переживают. Было: рестарт процесса (каждый деплой) обрывает все идущие партии без следа; в БД они остаются с `result = NULL` |
| R4 | ✅ исправлено (два процесса). Было: один Stockfish под одним локом на бота и анализ: 20 анализов × 0.42 с = боты стоят ~8 с |
| R5 | ✅ исправлено (лимит на пользователя). Было: rate limit анализа фактически глобальный (IP прокси) |
| R6 | Миграции — ручные `ALTER TABLE` при импорте модуля |
| R7 | ◐ частично: pytest (24 теста) + GitHub Actions, health-check с ретраями в `deploy.sh`; `git add -A` в `deploy.sh` оставлен. Было: нет тестов, CI, линтера; `deploy.sh` делает `git add -A` и коммитит в `main` всё подряд |
