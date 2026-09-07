#!/usr/bin/env python3
"""
Avito Bot — polling сервер для MAGIC | GAME.
Каждые 60 секунд проверяет новые сообщения в Авито и шлёт черновики в Телеграм.
"""
import os
import time
import json
import requests
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# === Config ===
CLIENT_ID = os.environ.get("AVITO_CLIENT_ID", "37JdRroSViO7DszyZokh")
CLIENT_SECRET = os.environ.get("AVITO_CLIENT_SECRET", "cpLQcyFUcDCi94UDB9oUQz0afFc-64VAtHOIWzXl")
USER_ID = int(os.environ.get("AVITO_USER_ID", "220388146"))
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8850826923:AAEquMIf3KIYbBjwKxNHWyRjI-lFELjn0ns")
TELEGRAM_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "1046557548"))

# === Skip ===
SKIP_NAMES = ["GameShOp - PlayStation", "Moonqueen Store"]
SKIP_CHATS = ["u2i-n~ofJ4ijZkxJP6meVWIAcw"]
END_PHRASES = ["купил", "уже купил", "спасибо", "успехов", "🤝", "👍", "понял", "принял", "ладно", "договорились", "хорошо"]

# === State ===
SENT_FILE = "/workspace/.spru/sent_notifications.json"

def load_sent():
    try:
        with open(SENT_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_sent(sent):
    os.makedirs(os.path.dirname(SENT_FILE), exist_ok=True)
    with open(SENT_FILE, "w") as f:
        json.dump(sent, f, indent=2)

# === Avito ===
def get_token():
    r = requests.post("https://api.avito.ru/token",
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={"grant_type": "client_credentials"}, timeout=10)
    return r.json().get("access_token")

def get_chats(token):
    all_chats = []
    for offset in [0, 50, 100]:
        r = requests.get(f"https://api.avito.ru/messenger/v2/accounts/{USER_ID}/chats",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 50, "offset": offset}, timeout=15)
        chats = r.json().get("chats", [])
        if not chats:
            break
        all_chats.extend(chats)
    return all_chats

def get_messages(token, chat_id):
    r = requests.get(f"https://api.avito.ru/messenger/v3/accounts/{USER_ID}/chats/{chat_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        params={"limit": 5}, timeout=10)
    return r.json().get("messages", [])

def get_item(token, item_id):
    r = requests.get(f"https://api.avito.ru/core/v1/items?user_id={USER_ID}&per_page=100",
        headers={"Authorization": f"Bearer {token}"}, timeout=10)
    items = r.json().get("resources", [])
    return next((i for i in items if i.get("id") == item_id), None)

def get_item_info(token, item_id):
    """Получает полную инфу по объявлению через прямой запрос"""
    # Используем список items (там есть title и price)
    return None  # Заглушка, реально используем get_item

# === Telegram ===
def send_telegram(text):
    r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        params={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    return r.status_code == 200

# === Logic ===
def detect_template(text, item_price, item_title):
    """Формирует черновик ответа"""
    t = text.lower().strip()
    
    # Имя
    return item_title, item_price

def is_cyrillic_name(name):
    """Проверяет: имя кириллица с заглавной?"""
    if not name or name == "Пользователь":
        return False
    name = name.split()[0] if " " in name else name
    if not name:
        return False
    first = name[0]
    rest = name[1:]
    if not first.isupper():
        return False
    # Проверяем что все буквы кириллица
    for c in rest:
        if not (("А" <= c <= "я") or c in "ёЁ" or c in "-"):
            return False
    return True

# === Polling ===
def poll_once():
    try:
        token = get_token()
        chats = get_chats(token)
        sent = load_sent()
        
        new_count = 0
        for c in chats[:50]:
            cid = c["id"]
            if cid in SKIP_CHATS:
                continue
            
            users = c.get("users", [])
            other = next((u for u in users if u.get("id") != USER_ID), {})
            name = other.get("name", "")
            
            if name in SKIP_NAMES:
                continue
            
            msgs = get_messages(token, cid)
            if not msgs:
                continue
            
            last = msgs[0]
            if last.get("author_id") == USER_ID:
                continue
            
            text = last.get("content", {}).get("text", "")
            if not text:
                continue
            if "Системное сообщение" in text:
                continue
            
            # Проверяем завершающие фразы
            t = text.lower()
            if any(ep in t for ep in END_PHRASES):
                continue
            
            created = last.get("created", 0)
            
            # Свежее 10 минут
            if created < time.time() - 600:
                continue
            
            # Дедупликация
            msg_id = last.get("id", "")
            key = f"{cid}_{msg_id}"
            if key in sent:
                continue
            sent[key] = int(time.time())
            
            # Получаем инфу об объявлении
            ctx = c.get("context", {})
            item_id = ctx.get("value", {}).get("id") if isinstance(ctx.get("value"), dict) else None
            item_title = "объявление"
            item_price = "?"
            
            if item_id:
                item = get_item(token, item_id)
                if item:
                    item_title = item.get("title", "объявление")
                    item_price = item.get("price", "?")
            
            # Имя
            fname = ""
            if is_cyrillic_name(name):
                fname = name.split()[0]
            
            # Проверяем — только цифры (телефон)?
            digits = text.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            if digits.isdigit() and len(digits) >= 10:
                # Телефон — отвечаем "Хорошо, принял"
                if fname:
                    reply = f"{fname}, хорошо, принял 👍"
                else:
                    reply = "Хорошо, принял 👍"
                # Отправляем сразу
                url = f"https://api.avito.ru/messenger/v1/accounts/{USER_ID}/chats/{cid}/messages"
                requests.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"type": "text", "message": {"text": reply}}, timeout=10)
                continue
            
            # Формируем черновик
            greeting = f"{fname}, здравствуйте 🤝" if fname else "Здравствуйте 🤝"
            
            if "цена" in t or "стоит" in t or "сколько" in t or "прайс" in t or "актуально" in t:
                # Вопрос про цену
                draft = f"""{greeting}

Базовый комплект ⚡️
▫️ {item_title}
▫️ Оригинальный геймпад
▫️ Полный комплект проводов
▫️ Личный аккаунт

{item_price} ₽ ✅

🎮 Также можем добавить:
▫️ 2-й геймпад — +5 500 ₽
▫️ Подписку PS Plus Extra/Deluxe
▫️ Док-станцию, диски с играми

Подскажите, какой комплект рассматриваете? Интересуют допы?"""
            elif "актуальн" in t or "объявлен" in t:
                draft = f"""{greeting}

По объявлению, на которое вы написали — {item_title}, цена {item_price} ₽ ✅

Да, актуально!

🎮 Можем добавить:
▫️ 2-й геймпад — +5 500 ₽
▫️ Подписку PS Plus
▫️ Док-станцию, диски

Подскажите, какой комплект?"""
            else:
                # Общий случай
                draft = f"""{greeting}

Вас приветствует команда MAGIC | GAME

На связи Илья — готов помочь и ответить на любой вопрос! 🎮

По объявлению, на которое вы написали — {item_title}, цена {item_price} ₽ ✅

🎮 Также можем добавить:
▫️ 2-й геймпад — +5 500 ₽
▫️ Подписку PS Plus Extra/Deluxe
▫️ Док-станцию, диски с играми

Подскажите, какой комплект рассматриваете?"""
            
            # Отправляем черновик в Телеграм
            notif = f"""🔔 <b>Новое сообщение</b>
👤 Имя: {name if name else '?'} ({'кириллица' if fname else 'без имени'})
💬 Чат: <code>{cid}</code>
📦 Объявление: {item_title}
💵 Цена: {item_price} ₽

📨 <b>Текст клиента:</b>
{text[:300]}

📝 <b>Черновик ответа:</b>
{draft}

Отправлять? (да/нет)"""
            
            if send_telegram(notif):
                new_count += 1
        
        save_sent(sent)
        return new_count
    except Exception as e:
        return f"error: {e}"

# === Flask (для Render healthcheck) ===
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def index():
    return "Avito Bot for MAGIC | GAME is running"

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "avito-bot"})

@app.route("/poll")
def poll():
    count = poll_once()
    return jsonify({"status": "polling_executed", "new_count": count})

# === Background polling ===
def background_polling():
    """Каждые 60 секунд проверяет новые чаты"""
    while True:
        try:
            count = poll_once()
            print(f"[{datetime.now().isoformat()}] Polled: {count} new")
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] Error: {e}")
        time.sleep(60)

# Запускаем polling в фоне при импорте
threading.Thread(target=background_polling, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
