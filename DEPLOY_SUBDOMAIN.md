# Деплой на chess.apichatpong.online

Так удобнее тестировать: один поддомен, всё (фронт + API + WebSocket) по HTTPS. Telegram Web App открывает только HTTPS-ссылки.

## 1. DNS

У домена **apichatpong.online** добавь запись для поддомена (если домен в Cloudflare — делай это в панели Cloudflare, см. раздел 2).

| Тип  | Имя   | Значение        | TTL |
|------|--------|-----------------|-----|
| A    | chess  | IP твоего VPS   | 300 |

После сохранения подожди 1–5 минут (с Cloudflare обычно быстро), проверка: `ping chess.apichatpong.online`.

---

## 2. Настройка Cloudflare для поддомена

Если домен **apichatpong.online** уже подключён к Cloudflare, сделай следующее.

### 2.1 DNS-запись

1. Зайди в [dash.cloudflare.com](https://dash.cloudflare.com) → выбери зону **apichatpong.online** → вкладка **DNS** → **Records**.
2. Нажми **Add record**.
3. Заполни:
   - **Type:** `A`
   - **Name:** `chess` (получится поддомен chess.apichatpong.online)
   - **IPv4 address:** IP твоего VPS
   - **Proxy status:** включён (оранжевое облако) — трафик пойдёт через Cloudflare (HTTPS, защита, кэш по желанию).
4. Сохрани (**Save**).

Проверка: в браузере или `curl -I https://chess.apichatpong.online/` — должен отвечать твой сервер (после настройки Nginx ниже).

### 2.2 SSL/TLS

1. В зоне **apichatpong.online** открой **SSL/TLS**.
2. Режим **Overview** → **Encryption mode:** выбери **Full** или **Full (strict)**.
   - **Full** — Cloudflare подключается к твоему серверу по HTTPS или HTTP (подойдёт, если на VPS есть любой валидный сертификат, в т.ч. Let's Encrypt).
   - **Full (strict)** — сервер должен отдавать валидный сертификат (например от Let's Encrypt для chess.apichatpong.online). Рекомендуется, если уже настроен certbot.

Для одного поддомена можно не трогать **Edge Certificates** — бесплатный универсальный сертификат Cloudflare уже выдаёт HTTPS для посетителей.

### 2.3 WebSockets

WebSocket (нужен для лобби и игры) у Cloudflare работает по умолчанию, ничего включать не нужно. Запросы к `wss://chess.apichatpong.online/ws` будут проксироваться на твой сервер.

### 2.4 Кэш (по желанию)

Чтобы не кэшировать API и WebSocket (логика игры должна быть в реальном времени):

1. **Rules** → **Page Rules** (или **Configuration Rules** в новом интерфейсе).
2. Можно добавить правило для `chess.apichatpong.online/*`: **Cache Level** = **Bypass**. Тогда весь поддомен не кэшируется.  
   Либо не добавлять правил — по умолчанию далеко не всё кэшируется, WebSocket не кэшируется никогда.

Если хочешь кэшировать только статику (CSS/JS) — оставь кэш по умолчанию или настрой позже по необходимости.

### 2.5 Итог по Cloudflare

| Где | Что сделать |
|-----|-------------|
| DNS | Запись **A** для **chess** → IP VPS, Proxy включён |
| SSL/TLS | Режим **Full** или **Full (strict)** |
| WebSockets | Ничего не менять |
| Кэш | По желанию: Bypass для всего поддомена или оставить по умолчанию |

Дальше на самом VPS нужен Nginx (или Caddy) с SSL и проксированием на приложение — см. разделы ниже.

## 3. Сервер (VPS)

Приложение слушает один порт (например 8000). Нужен reverse proxy с HTTPS.

### Вариант A: Nginx + Let's Encrypt (certbot)

```bash
# Установка nginx и certbot (Debian/Ubuntu)
sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx
```

Файл конфига Nginx (например `/etc/nginx/sites-available/chess`):

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

Включить сайт и получить сертификат:

```bash
sudo ln -s /etc/nginx/sites-available/chess /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d chess.apichatpong.online
```

Certbot сам добавит `listen 443 ssl` и пути к сертификатам.

### Вариант B: Caddy

Caddy сам получает сертификаты по HTTPS:

```bash
# Установка Caddy (см. caddyserver.com)
```

Файл `Caddyfile`:

```
chess.apichatpong.online {
    reverse_proxy 127.0.0.1:8000
}
```

Запуск: `caddy run` или через systemd.

## 4. Запуск приложения

**Рекомендуемый способ — Docker** (см. [DEPLOY_DOCKER.md](DEPLOY_DOCKER.md)):

```bash
cd /path/to/phonechess
echo 'TELEGRAM_BOT_TOKEN=твой_токен' > .env
docker compose up -d
```

Приложение будет слушать порт 8000 на хосте.

**Без Docker** — вручную на VPS:

```bash
cd /path/to/phonechess/backend
source .venv/bin/activate
export TELEGRAM_BOT_TOKEN="твой_токен"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

(Или через systemd/supervisor.)

## 5. Telegram Bot

В [@BotFather](https://t.me/BotFather) → твой бот → **Bot Settings** → **Menu Button** (или **Configure** у Web App):

- URL: `https://chess.apichatpong.online/`

Либо создай команду/кнопку, которая открывает:  
`https://chess.apichatpong.online/`

Тогда пользователи заходят по HTTPS, фронт и WebSocket (`wss://chess.apichatpong.online/ws`) работают с одного домена — CORS и куки не мешают.

## 6. Проверка

- В браузере: `https://chess.apichatpong.online/` — должна открыться лобби.
- В Telegram: открой бота и кнопку/команду с этой ссылкой — откроется Mini App.

Если что-то не открывается, проверь: DNS, firewall (80/443 открыты), логи nginx/caddy и `uvicorn`.
