# Avito Webhook Server for MAGIC | GAME

Webhook-сервер для мгновенных ответов клиентам Авито через Телеграм.

## Как работает:
1. Клиент пишет в Авито → Avito шлёт webhook
2. Сервер получает → пересылает Илье в Телеграм
3. Илья отвечает реплаем в Телеграме
4. Сервер ловит ответ → отправляет в Авито

## Деплой на Render:
1. Создать GitHub репо (или залить код)
2. Зайти на render.com → New → Web Service
3. Подключить репо
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `gunicorn server:app`
6. Plan: Free

## Переменные окружения (опционально):
- `PORT` — Render ставит автоматически на 10000
- `AVITO_USER_ID` — 220388146
- `TELEGRAM_OWNER_ID` — 1046557548

## После деплоя:
1. Получить URL вида `https://magic-avito-bot.onrender.com`
2. Зарегистрировать webhook: `POST /register-webhook` с `{"url": "https://your-url/avito-webhook"}`
3. Проверить: написать в любой Авито-чат — сообщение придёт в Телеграм
