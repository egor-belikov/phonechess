# PhoneChess

Telegram Mini App для онлайн-шахмат. Этап 1: скелет (лобби, очередь, пейринг по WebSocket).

## Запуск (этап 1)

### Бэкенд

```bash
cd phonechess/backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Для проверки **без Telegram** (браузер с любого URL) задайте `DEBUG=1` и не указывайте токен — будет принят тестовый пользователь:

```bash
DEBUG=1 uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Для работы **из Telegram** создайте бота через [@BotFather](https://t.me/BotFather), получите токен и укажите:

```bash
export TELEGRAM_BOT_TOKEN=123456:ABC...
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Фронт отдаётся с того же порта (папка `frontend/` монтируется как статика).

### Деплой на сервер (Docker)

На сервере с Docker достаточно клонировать проект, задать в `.env` переменную `TELEGRAM_BOT_TOKEN` и выполнить:

```bash
docker compose build && docker compose up -d
```

Подробно: [DEPLOY_DOCKER.md](DEPLOY_DOCKER.md). Там же — настройка Nginx и HTTPS для chess.apichatpong.online.

### Проверка

- Открой в браузере: `http://localhost:8000/`
- В режиме `DEBUG=1` подключение идёт без Telegram (каждой вкладке — свой тестовый пользователь). Открой **две вкладки**, в обеих нажми **один и тот же** контроль (например 3+0): первая попадёт в «Ожидание соперника», во второй нажми 3+0 — в обеих откроется экран партии (плейсхолдер).
- Health: `http://localhost:8000/health`

## Структура

- `backend/app/` — FastAPI, auth (initData), очереди, WebSocket.
- `frontend/` — одна страница: лобби (6 кнопок + счётчики), ожидание, экран игры (плейсхолдер).

Подробный план — в [PROJECT_PLAN.md](PROJECT_PLAN.md), хостинг при узком канале — в [HOSTING.md](HOSTING.md).

**Деплой на поддомен для тестов:** настрой `chess.apichatpong.online` по инструкции [DEPLOY_SUBDOMAIN.md](DEPLOY_SUBDOMAIN.md) — один HTTPS-адрес для фронта и API, удобно тестировать из Telegram.

## Git и GitHub

Если папка **phonechess** ещё не под Git — в консоли из корня проекта (где лежит этот README):

```bash
cd /Users/egor/Desktop/code/phonechess
git init
git add .
git commit -m "PhoneChess: этап 1 — лобби, очередь, WebSocket"
```

Дальше — один из двух способов.

### Вариант A: репозиторий через GitHub CLI

Установи [GitHub CLI](https://cli.github.com/) (`brew install gh` на macOS), авторизуйся (`gh auth login`), затем:

```bash
gh repo create phonechess --private --source . --remote origin --push
```

Будет создан репозиторий **phonechess** в твоём аккаунте (приватный), привязан как `origin` и выполнен первый `push`. Имя репо можно поменять: `gh repo create MY_REPO_NAME ...`.

### Вариант B: репозиторий создаёшь вручную на GitHub

1. На [github.com](https://github.com) нажми **New repository**, имя например **phonechess**, создай (без README/ .gitignore).
2. В консоли в папке проекта:

```bash
git remote add origin https://github.com/ТВОЙ_ЛОГИН/phonechess.git
git branch -M main
git push -u origin main
```

Подставь свой логин GitHub вместо `ТВОЙ_ЛОГИН`. Если используешь SSH: `git@github.com:ТВОЙ_ЛОГИН/phonechess.git`.

Файл `.env` в репозиторий не попадёт — он в [.gitignore](.gitignore).
