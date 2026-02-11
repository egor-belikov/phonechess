# Деплой PhoneChess через Docker

Всё приложение (бэкенд + фронт) собирается в один образ и запускается одним контейнером. На сервере нужны только Docker и Docker Compose.

---

## Команды на сервере по порядку

Зайди на сервер по SSH и выполняй по шагам (репо: [github.com/egor-belikov/phonechess](https://github.com/egor-belikov/phonechess)).

**1. Перейти в каталог проектов и клонировать репо**

```bash
cd ~/my_projects
git clone https://github.com/egor-belikov/phonechess.git
cd phonechess
```

**2. Создать `.env` с токеном бота** (подставь свой токен от @BotFather)

```bash
printf 'TELEGRAM_BOT_TOKEN=8444402140:AAHIwuDVuxP6C3OcY1I_ULvrkopX0Fq81fc\nDEBUG=0\n' > .env
```

Проверить: `cat .env` — должен быть твой токен.

**3. Собрать образ и запустить контейнер**

```bash
docker compose build
docker compose up -d
```

**4. Проверить, что приложение отвечает**

```bash
docker compose ps
curl -s http://127.0.0.1:8000/health
```

В ответ должно быть `{"status":"ok"}`.

**5. Настроить Nginx** (если ещё нет конфига для chess.apichatpong.online)

```bash
sudo nano /etc/nginx/sites-available/chess
```

Вставить (и сохранить: Ctrl+O, Enter, Ctrl+X):

```nginx
server {
    listen 80;
    server_name chess.apichatpong.online;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

Включить сайт и перезагрузить Nginx:

```bash
sudo ln -sf /etc/nginx/sites-available/chess /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

**5a. Если Nginx запущен в Docker** (конфиги с хоста: `/root/my_projects/nginx/conf.d`)

Создай конфиг на хосте — nginx подхватит его из примонтированной папки. В `proxy_pass` нужен адрес **хоста с точки зрения контейнера nginx**: это Gateway сети контейнера (в твоём случае `172.19.0.1`), т.к. phonechess слушает на порту 8000 на хосте.

```bash
cat > /root/my_projects/nginx/conf.d/chess.conf << 'EOF'
server {
    listen 80;
    server_name chess.apichatpong.online;
    location / {
        proxy_pass http://172.19.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
EOF
docker exec nginx nginx -t && docker exec nginx nginx -s reload
```

Если Gateway у тебя другой — смотри в `docker inspect nginx` в блоке `Networks` → `Gateway`. Если nginx и phonechess окажутся в одной docker-сети, можно будет заменить на `http://phonechess-app-1:8000`.

**5b. Cloudflare Tunnel: завести chess.apichatpong.online**

Если снаружи ты заходишь на сайты через **Cloudflare Tunnel** (контейнер cloudflared), а не по A-записи на IP, то туннель нужно явно научить отправлять трафик для `chess.apichatpong.online` на nginx.

**Вариант 1: настройка в панели Cloudflare (Zero Trust)**

1. Зайди в [Zero Trust](https://one.dash.cloudflare.com) (или [dash.cloudflare.com](https://dash.cloudflare.com) → свой аккаунт → **Zero Trust**).
2. **Networks** → **Tunnels** → выбери свой туннель (тот, что крутится в cloudflared_tunnel).
3. Открой вкладку **Public Hostname** (или **Routing**).
4. Нажми **Add a public hostname**.
5. Укажи:
   - **Subdomain:** `chess` (или **Subdomain** = `chess`, **Domain** = `apichatpong.online` — получится chess.apichatpong.online).
   - **Service type:** `HTTP`.
   - **URL:** если cloudflared в одной Docker-сети с nginx — `nginx:80`. Если cloudflared на хосте и nginx в контейнере без проброса порта — укажи тот адрес, куда туннель сейчас стучится к nginx (например `localhost:80` или `host.docker.internal:80` — как у других хостов apichatpong.online).
6. Сохрани.

После этого Cloudflare сам создаст/обновит DNS (CNAME `chess` → туннель). Трафик на https://chess.apichatpong.online пойдёт в туннель → на указанный URL (nginx) → nginx по своему конфигу отдаст приложение с 172.19.0.1:8000.

**Вариант 2: конфиг туннеля в файле на сервере**

Если туннель запущен с локальным `config.yml` (например примонтирован в контейнер cloudflared), нужно добавить в секцию **ingress** правило для chess и перезапустить контейнер.

1. Найти конфиг:
   ```bash
   docker inspect cloudflared_tunnel --format '{{json .Mounts}}' | python3 -m json.tool
   ```
   Или посмотреть команду запуска: `docker inspect cloudflared_tunnel` и найти путь к конфигу (`--config /path/to/config.yml`).

2. Открыть этот файл на хосте и в **ingress** добавить строки для chess (важно: правило с конкретным hostname должно быть **выше** catch-all, если он есть):
   ```yaml
   ingress:
     - hostname: chess.apichatpong.online
       service: http://nginx:80
     # остальные hostname и service: ...
     - service: http_status:404
   ```

3. Перезапустить туннель:
   ```bash
   docker restart cloudflared_tunnel
   ```

4. В Cloudflare (DNS зоны apichatpong.online) должна быть запись для **chess**: тип **CNAME**, значение — `ваш-туннель.cfargotunnel.com` (то же, что и у других поддоменов через туннель). Если включали хостнейм через Zero Trust (вариант 1), CNAME часто создаётся автоматически.

**6. SSL через Let's Encrypt** (если домен уже указывает на сервер и Nginx слушает 80)

```bash
sudo certbot --nginx -d chess.apichatpong.online
```

Если используешь только Cloudflare (без certbot на сервере), шаг 6 можно пропустить — HTTPS выдаёт Cloudflare. В Cloudflare для зоны apichatpong.online должна быть A-запись **chess** → IP сервера (см. [DEPLOY_SUBDOMAIN.md](DEPLOY_SUBDOMAIN.md)).

**7. В BotFather** указать URL Mini App: `https://chess.apichatpong.online/`

Проверка: открыть в браузере https://chess.apichatpong.online/ — должна загрузиться лобби.

**Если страница грузится, но циклично «Нет соединения» и «Подключение…»** — WebSocket закрывается бэкендом. При открытии **в обычном браузере** (не из Telegram) у приложения нет `init_data`, и при `DEBUG=0` бэкенд отклоняет подключение. Включи отладку и перезапусти контейнер: в `.env` поставь `DEBUG=1`, затем `docker compose up -d --force-recreate`. После этого в браузере должно показать «Подключено». Для продакшена верни `DEBUG=0` и открывай приложение только из Telegram.

---

## Начать chess с нуля (очистка и заново)

Если на chess.apichatpong.online раньше было что-то другое и сейчас 502 — сделай полную очистку и настрой заново только под PhoneChess.

### На сервере

**1. Удалить старый конфиг nginx для chess** (если есть в папке конфигов Docker-nginx):

```bash
rm -f /root/my_projects/nginx/conf.d/chess.conf
docker exec nginx nginx -t && docker exec nginx nginx -s reload
```

**2. Убедиться, что крутится только нужный phonechess** (из папки phonechess):

```bash
cd /root/my_projects/phonechess
docker compose ps
curl -s http://127.0.0.1:8000/health
```

Если контейнер не запущен или health не отвечает: `docker compose up -d`, подождать пару секунд, снова проверить health.

**3. Заново создать конфиг nginx для chess** (прокси на phonechess):

```bash
cat > /root/my_projects/nginx/conf.d/chess.conf << 'EOF'
server {
    listen 80;
    server_name chess.apichatpong.online;
    location / {
        proxy_pass http://172.19.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
EOF
docker exec nginx nginx -t && docker exec nginx nginx -s reload
```

Если nginx и phonechess в одной docker-сети (оба в `my_projects_my_network`), замени в конфиге `proxy_pass` на `http://phonechess-app-1:8000` и снова reload.

**4. Проверить изнутри nginx, что бэкенд доступен:**

```bash
docker exec nginx wget -q -O- http://172.19.0.1:8000/health
```

Должно вывести `{"status":"ok"}`. Если ошибка — см. раздел про 502 выше (другой Gateway или имя контейнера).

### В Cloudflare

**5. Туннель (Zero Trust):** зайди в **Zero Trust** → **Tunnels** → свой туннель → **Public Hostname**. Найди запись для **chess.apichatpong.online** (или subdomain chess). Удали её (Delete), сохрани. Потом **Add a public hostname**: Subdomain = `chess`, Domain = `apichatpong.online`, Service = **HTTP**, URL = **nginx:80** (или тот же URL, что у других твоих сайтов через этот туннель). Сохрани.

**6. DNS:** в зоне **apichatpong.online** вкладка **DNS**. Если есть запись для **chess** (A или CNAME) с другим значением или «прокси выключен» — удали или отредактируй. Для туннеля обычно должна остаться одна запись **chess** → CNAME на твой туннель (часто создаётся автоматически при добавлении Public Hostname в п. 5).

После этого открой https://chess.apichatpong.online/ — должна открыться лобби PhoneChess.

---

## 1. Подготовка на сервере

- Установлен Docker и Docker Compose (v2: `docker compose`).
- Домен **chess.apichatpong.online** указывает на IP сервера (A-запись или CNAME).

## 2. Код на сервере

Клонируй репозиторий в каталог, где будешь деплоить (или залей файлы по SFTP):

```bash
cd /opt   # или свой каталог
git clone <url-репо> phonechess
cd phonechess
```

Либо загрузи только нужное: корень репо с `Dockerfile`, `docker-compose.yml`, папки `backend/` и `frontend/`.

## 3. Переменные окружения

В той же папке создай файл `.env` (не коммитить в git):

```env
TELEGRAM_BOT_TOKEN=123456:ABC-...
DEBUG=0
```

Команда в консоли (подставь свой токен и выполни из папки проекта):

```bash
printf 'TELEGRAM_BOT_TOKEN=ТВОЙ_ТОКЕН_ОТ_BOTFATHER\nDEBUG=0\n' > .env
```

- **TELEGRAM_BOT_TOKEN** — токен бота от @BotFather (обязателен для продакшена).
- **DEBUG** — `0` в продакшене; `1` только для локальной отладки (логин без Telegram).
- **ALLOWED_ORIGINS** — по умолчанию `*`; можно задать, например: `https://chess.apichatpong.online`.

## 4. Сборка и запуск

Из корня проекта (где лежит `docker-compose.yml`):

```bash
docker compose build
docker compose up -d
```

Проверка:

```bash
docker compose ps
curl http://127.0.0.1:8000/health
```

Должен ответить `{"status":"ok"}`. Приложение слушает порт **8000** внутри контейнера и проброшен на хост.

## 5. HTTPS и поддомен (Nginx на хосте)

Чтобы открывать приложение по `https://chess.apichatpong.online`, на том же сервере нужен reverse proxy с SSL.

**Если домен за Cloudflare** — в панели Cloudflare добавь A-запись для поддомена **chess** и включи SSL (Full или Full strict). Подробно: [DEPLOY_SUBDOMAIN.md](DEPLOY_SUBDOMAIN.md) → раздел «Настройка Cloudflare для поддомена».

Пример конфига Nginx (`/etc/nginx/sites-available/chess`):

```nginx
server {
    listen 80;
    server_name chess.apichatpong.online;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

Включить сайт и выдать сертификат:

```bash
sudo ln -s /etc/nginx/sites-available/chess /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d chess.apichatpong.online
```

После этого приложение доступно по **https://chess.apichatpong.online/**.

## 6. Обновление

После `git pull` или обновления файлов:

```bash
docker compose build
docker compose up -d
```

Контейнер пересоберётся и перезапустится с новым кодом.

## 7. Логи и перезапуск

Все события WebSocket и ошибки пишутся в stdout контейнера — смотреть их так:

```bash
cd /root/my_projects/phonechess
docker compose logs -f app
```

**Что должно быть при успешном подключении из браузера:**

1. `WS: connection attempt from ...` — запрос на /ws дошёл до приложения.
2. `WS: accepted, waiting for auth` — рукопожатие WebSocket прошло.
3. `WS: first message type=auth` — клиент прислал auth.
4. `WS: auth ok user_id=... username=...` — авторизация успешна (при DEBUG=1 — тестовый пользователь).
5. `WS: queue_counts sent to ...` — клиент получил счётчики очередей, в интерфейсе появятся кнопки.

**Если висит «Подключение…»:**

- Нет ни одной строки `WS: connection attempt` — запросы на /ws не доходят до контейнера (проверь Nginx, туннель, что запрос идёт на правильный хост и путь `/ws`).
- Есть `connection attempt`, но нет `accepted` — возможна ошибка при accept (смотри след. строку с ERROR).
- Есть `accepted`, но нет `first message type=auth` — клиент не отправил auth (проверь, что фронт открыт с того же домена и что WebSocket не режется прокси; в Nginx должны быть `Upgrade` и `Connection "upgrade"`).
- Есть `auth failed` — при DEBUG=0 нужен валидный Telegram init_data; при DEBUG=1 можно слать без init_data (поле `debug_uid` для отладки с двух вкладок).

Чтобы прислать логи: выполни `docker compose logs app --tail 200` и приложи вывод (или сохрани в файл и пришли фрагмент).

```bash
docker compose restart app
docker compose down
docker compose up -d
```

## 8. Краткий чеклист деплоя

| Шаг | Команда / действие |
|-----|---------------------|
| 1 | Клонировать/залить проект в каталог на сервере |
| 2 | Создать `.env` с `TELEGRAM_BOT_TOKEN` |
| 3 | `docker compose build && docker compose up -d` |
| 4 | Настроить Nginx + certbot для chess.apichatpong.online |
| 5 | В BotFather указать URL: `https://chess.apichatpong.online/` |

Готово: тестировать можно по ссылке в Telegram и в браузере.
