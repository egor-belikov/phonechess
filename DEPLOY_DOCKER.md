# Деплой PhoneChess через Docker

Всё приложение (бэкенд + фронт) собирается в один образ и запускается одним контейнером. На сервере нужны только Docker и Docker Compose.

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

```bash
docker compose logs -f app
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
