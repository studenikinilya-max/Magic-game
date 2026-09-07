"""
Avito Webhook Server для MAGIC | GAME
Получает webhook от Авито → шлёт Илье в Телеграм → ловит ответ → шлёт в Авито
"""
import os
import json
import asyncio
import requests
from datetime import datetime
from flask import Flask, request, jsonify
import telebot
from telebot import types

# ============ КОНФИГ ============
AVITO_CLIENT_ID = "37JdRroSViO7DszyZokh"
AVITO_CLIENT_SECRET = "cpLQcyFUcDCi94UDB9oUQz0afFc-64VAtHOIWzXl"
AVITO_USER_ID = "220388146"

TELEGRAM_BOT_TOKEN = "8850826923:AAEquMIf3KIYbBjwKxNHWyRjI-lFELjn0ns"
TELEGRAM_OWNER_ID = 1046557548  # Илья
TOPIC_AVITO_QUESTIONS = 652566  # раздел "Авито вопросы"

app = Flask(__name__)
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Хранилище: chat_id -> message_id в Телеграме
pending_messages = {}

# ============ АВИТО API ============

def get_avito_token():
    """Получить токен Авито"""
    r = requests.post("https://api.avito.ru/token",
        auth=(AVITO_CLIENT_ID, AVITO_CLIENT_SECRET),
        data={"grant_type": "client_credentials"})
    return r.json().get("access_token")

def send_avito_message(chat_id, text):
    """Отправить сообщение в Авито"""
    token = get_avito_token()
    r = requests.post(
        f"https://api.avito.ru/messenger/v1/accounts/{AVITO_USER_ID}/chats/{chat_id}/messages",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"type": "text", "message": {"text": text}}
    )
    return r.status_code in [200, 201]

def get_chat_info(chat_id):
    """Получить инфо о чате"""
    token = get_avito_token()
    r = requests.get(
        f"https://api.avito.ru/messenger/v2/accounts/{AVITO_USER_ID}/chats/{chat_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code == 200:
        data = r.json()
        users = data.get("users", [])
        other = next((u for u in users if str(u.get("id")) != AVITO_USER_ID), {})
        ctx = data.get("context", {})
        item = ctx.get("value", {}) if isinstance(ctx.get("value"), dict) else {}
        return {
            "client_name": other.get("name", "Клиент"),
            "client_id": other.get("id"),
            "item_title": item.get("title", ""),
            "item_price": item.get("price_string", ""),
            "item_url": item.get("url", ""),
        }
    return None

def get_chat_messages(chat_id, limit=5):
    """Получить последние сообщения"""
    token = get_avito_token()
    r = requests.get(
        f"https://api.avito.ru/messenger/v3/accounts/{AVITO_USER_ID}/chats/{chat_id}/messages",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params={"limit": limit}
    )
    if r.status_code == 200:
        return r.json().get("messages", [])
    return []

# ============ TELEGRAM ============

def send_to_telegram(chat_id_avito, msg_text):
    """Отправить сообщение из Авито в Телеграм"""
    info = get_chat_info(chat_id_avito)
    if not info:
        return None

    # Получить последние сообщения для контекста
    msgs = get_chat_messages(chat_id_avito, 5)

    text = f"""🔔 **Новое сообщение в Авито**

👤 Клиент: {info['client_name']}
📦 Объявление: {info['item_title']}
💰 Цена: {info['item_price']}

💬 Последнее сообщение клиента:
{msg_text}

🔗 Чат ID: `{chat_id_avito}`
🔗 Объявление: {info['item_url']}

👇 **Ответь РЕПЛАЕМ на это сообщение — твой ответ уйдёт клиенту в Авито**"""

    msg = bot.send_message(TELEGRAM_OWNER_ID, text, parse_mode='Markdown')
    pending_messages[chat_id_avito] = msg.message_id
    return msg.message_id

# ============ TELEGRAM BOT HANDLERS ============

@bot.message_handler(func=lambda message: message.reply_to_message is not None)
def handle_reply(message):
    """Обработка реплая Ильи — отправка в Авито"""
    if message.from_user.id != TELEGRAM_OWNER_ID:
        return

    # Найти какой chat_id соответствует этому сообщению
    target_chat_id = None
    for cid, msg_id in pending_messages.items():
        if msg_id == message.reply_to_message.message_id:
            target_chat_id = cid
            break

    if not target_chat_id:
        bot.reply_to(message, "❌ Не нашёл чат Авито для этого сообщения")
        return

    text = message.text
    success = send_avito_message(target_chat_id, text)

    if success:
        bot.reply_to(message, f"✅ Отправлено в Авито (chat {target_chat_id[:15]}...)")
        del pending_messages[target_chat_id]
    else:
        bot.reply_to(message, "❌ Ошибка отправки в Авито")

# ============ WEBHOOK ENDPOINTS ============

@app.route('/')
def home():
    return "Avito Webhook Server for MAGIC | GAME is running"

@app.route('/health')
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

@app.route('/avito-webhook', methods=['POST'])
def avito_webhook():
    """Webhook от Авито — новое сообщение"""
    data = request.json
    print(f"[Webhook] Получено: {json.dumps(data, ensure_ascii=False)[:500]}")

    # Определить тип события
    event_type = data.get("type")
    payload = data.get("payload", {})

    if event_type == "message":
        chat_id = payload.get("chat_id")
        author_id = payload.get("author_id")
        text = payload.get("value", "")

        # Только сообщения от клиентов (не от нас)
        if author_id != int(AVITO_USER_ID) and text:
            send_to_telegram(chat_id, text)

    return jsonify({"status": "ok"}), 200

@app.route('/register-webhook', methods=['POST'])
def register_webhook():
    """Регистрация webhook в Авито"""
    url = request.json.get("url")
    if not url:
        return jsonify({"error": "url required"}), 400

    token = get_avito_token()
    r = requests.post(
        "https://api.avito.ru/messenger/v3/webhook",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"url": url}
    )
    return jsonify({
        "status_code": r.status_code,
        "response": r.json() if r.status_code in [200, 201] else r.text
    })

if __name__ == '__main__':
    # Запуск Flask + Telegram bot
    import threading
    bot_thread = threading.Thread(target=lambda: bot.polling(none_stop=True), daemon=True)
    bot_thread.start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
