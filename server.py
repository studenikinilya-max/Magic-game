#!/usr/bin/env python3
"""
Avito Bot Server для MAGIC | GAME.
- Polling Avito каждые 60 сек
- Отправка черновиков в Telegram
- Приём ответов Ильи через Telegram webhook
- Автоотправка в Avito по подтверждению
"""
import os
import time
import json
import threading
import requests
from flask import Flask, request, jsonify

# === Config ===
CLIENT_ID = os.environ.get("AVITO_CLIENT_ID", "37JdRroSViO7DszyZokh")
CLIENT_SECRET = os.environ.get("AVITO_CLIENT_SECRET", "cpLQcyFUcDCi94UDB9oUQz0afFc-64VAtHOIWzXl")
USER_ID = int(os.environ.get("AVITO_USER_ID", "220388146"))
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8850826923:AAEquMIf3KIYbBjwKxNHWyRjI-lFELjn0ns")
TG_CHAT = int(os.environ.get("TELEGRAM_CHAT_ID", "1046557548"))

# === State ===
SENT_FILE = "/tmp/sent_notifications.json"
PENDING_FILE = "/tmp/pending_drafts.json"

SKIP_NAMES = ["GameShOp - PlayStation", "Moonqueen Store"]
SKIP_CHATS = ["u2i-n~ofJ4ijZkxJP6meVWIAcw"]
END_PHRASES = ["купил", "уже купил", "спасибо", "успехов", "понял", "принял", "ладно", "договорились"]

# === Helpers ===
def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"save error: {e}")

def get_token():
    r = requests.post("https://api.avito.ru/token",
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={"grant_type": "client_credentials"}, timeout=10)
    return r.json().get("access_token")

def is_cyrillic_name(name):
    if not name or name == "Пользователь":
        return ""
    parts = name.split()
    if not parts:
        return ""
    n = parts[0]
    if not n[0].isupper():
        return ""
    for c in n[1:]:
        if not (("А" <= c <= "я") or c in "ёЁ" or c in "-"):
            return ""
    return n

def send_tg(text):
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML"}, timeout=10)
    return r.status_code == 200

def send_avito(token, chat_id, text):
    url = f"https://api.avito.ru/messenger/v1/accounts/{USER_ID}/chats/{chat_id}/messages"
    return requests.post(url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"type": "text", "message": {"text": text}}, timeout=10)

# === Polling ===
def poll_once():
    try:
        token = get_token()
        sent = load_json(SENT_FILE, {})
        pending = load_json(PENDING_FILE, {})
        new = 0
        
        r = requests.get(f"https://api.avito.ru/messenger/v2/accounts/{USER_ID}/chats",
            headers={"Authorization": f"Bearer {token}"}, params={"limit": 50}, timeout=15)
        chats = r.json().get("chats", [])
        
        for c in chats:
            cid = c["id"]
            if cid in SKIP_CHATS:
                continue
            
            users = c.get("users", [])
            other = next((u for u in users if u.get("id") != USER_ID), {})
            name = other.get("name", "")
            
            if name in SKIP_NAMES:
                continue
            
            r2 = requests.get(f"https://api.avito.ru/messenger/v3/accounts/{USER_ID}/chats/{cid}/messages",
                headers={"Authorization": f"Bearer {token}"}, params={"limit": 5}, timeout=10)
            msgs = r2.json().get("messages", [])
            if not msgs:
                continue
            
            last = msgs[0]
            if last.get("author_id") == USER_ID:
                continue
            
            text = last.get("content", {}).get("text", "")
            if not text or "Системное сообщение" in text:
                continue
            
            t = text.lower()
            if any(ep in t for ep in END_PHRASES):
                continue
            
            msg_id = last.get("id", "")
            key = f"{cid}_{msg_id}"
            if key in sent:
                continue
            sent[key] = int(time.time())
            
            # Item info
            ctx = c.get("context", {})
            item_id = ctx.get("value", {}).get("id") if isinstance(ctx.get("value"), dict) else None
            item_title = "объявление"
            item_price = "?"
            if item_id:
                r3 = requests.get(f"https://api.avito.ru/core/v1/items?user_id={USER_ID}&per_page=100",
                    headers={"Authorization": f"Bearer {token}"}, timeout=10)
                items = r3.json().get("resources", [])
                item = next((i for i in items if i.get("id") == item_id), None)
                if item:
                    item_title = item.get("title", "объявление")
                    item_price = item.get("price", "?")
            
            fname = is_cyrillic_name(name)
            
            # Phone number - send immediately
            digits = text.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            if digits.isdigit() and len(digits) >= 10:
                if fname:
                    reply = f"{fname}, хорошо, принял 👍"
                else:
                    reply = "Хорошо, принял 👍"
                send_avito(token, cid, reply)
                continue
            
            # Build draft based on text
            if any(w in t for w in ["цена", "стоит", "сколько", "прайс"]):
                draft = f"""{fname + ', ' if fname else ''}здравствуйте 🤝

Базовый комплект ⚡️
▫️ {item_title}
▫️ Оригинальный геймпад
▫️ Полный комплект проводов
▫️ Личный аккаунт

{item_price} ₽ ✅

🎮 Также можем добавить:
▫️ 2-й геймпад — +5 500 ₽
▫️ Подписка PS Plus Extra/Deluxe
▫️ Док-станция, диски с играми

Подскажите, какой комплект рассматриваете? Интересуют допы?"""
            elif "актуальн" in t:
                draft = f"""{fname + ', ' if fname else ''}здравствуйте 🤝

По объявлению, на которое вы написали — {item_title}, цена {item_price} ₽ ✅

Да, актуально!

🎮 Можем добавить:
▫️ 2-й геймпад — +5 500 ₽
▫️ Подписка PS Plus
▫️ Док-станция, диски

Подскажите, какой комплект?"""
            elif any(w in t for w in ["пристав", "ps5", "ps 5", "купить"]):
                draft = f"""{fname + ', ' if fname else ''}здравствуйте 🤝

Вас приветствует команда MAGIC | GAME

По объявлению, на которое вы написали — {item_title}, цена {item_price} ₽ ✅

Базовый комплект ⚡️
▫️ {item_title}
▫️ Оригинальный геймпад
▫️ Полный комплект проводов
▫️ Личный аккаунт

🎮 Также можем добавить:
▫️ 2-й геймпад — +5 500 ₽
▫️ Подписка PS Plus
▫️ Док-станция, диски

Подскажите, какой комплект рассматриваете?"""
            else:
                draft = f"""{fname + ', ' if fname else ''}здравствуйте 🤝

По объявлению, на которое вы написали — {item_title} ✅

Подскажите, что хотите уточнить?"""
            
            # Save draft for this chat
            pending[cid] = {
                "draft": draft,
                "name": name,
                "fname": fname,
                "item_title": item_title,
                "item_price": item_price,
                "client_text": text,
                "created_at": int(time.time()),
            }
            
            # Send to Telegram
            notif = f"""🔔 <b>Новое сообщение</b>
👤 Имя: {name} ({'кириллица' if fname else 'без имени'})
💬 Чат: <code>{cid}</code>
📦 {item_title}
💵 {item_price} ₽

📨 Текст клиента:
{text[:200]}

📝 <b>Черновик:</b>
{draft}

Ответь: <b>да</b> / <b>нет</b> / <b>свой текст</b>"""
            if send_tg(notif):
                new += 1
        
        save_json(SENT_FILE, sent)
        save_json(PENDING_FILE, pending)
        return new
    except Exception as e:
        return f"error: {e}"

# === Telegram webhook (слушает ответы Ильи) ===
def handle_tg_update(update):
    """Обрабатывает сообщение от Ильи в Telegram."""
    try:
        msg = update.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "").strip()
        
        if str(chat_id) != str(TG_CHAT):
            return  # Чужой чат
        
        if not text:
            return
        
        # Проверяем формат: "да CHAT_ID" или просто "да"
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else None
        
        pending = load_json(PENDING_FILE, {})
        
        # Получить список ожидающих
        if not pending:
            send_tg("❌ Нет черновиков для отправки")
            return
        
        if cmd == "нет":
            # Отменить все или конкретный
            if arg:
                pending.pop(arg, None)
                save_json(PENDING_FILE, pending)
                send_tg(f"🗑 Черновик для чата {arg} отменён")
            else:
                pending.clear()
                save_json(PENDING_FILE, pending)
                send_tg("🗑 Все черновики отменены")
            return
        
        if cmd == "список":
            lines = ["📋 Ожидающие черновики:"]
            for cid, p in pending.items():
                lines.append(f"• {p['name']} ({cid})")
            send_tg("\n".join(lines))
            return
        
        # Определить какой чат
        target_cid = arg
        if not target_cid and len(pending) == 1:
            target_cid = list(pending.keys())[0]
        
        if not target_cid or target_cid not in pending:
            send_tg(f"❌ Уточните chat_id. Черновики: {', '.join(pending.keys())}")
            return
        
        p = pending[target_cid]
        custom_text = None
        
        if cmd in ["да", "отправляй", "ok", "ok"]:
            # Отправить черновик
            text_to_send = p["draft"]
        elif cmd == "свой":
            # Свой текст после "свой"
            custom_text = arg.replace("свой ", "", 1).strip() if arg and arg.startswith("свой ") else None
            if not custom_text:
                send_tg(f"❌ После 'свой' укажи текст: свой ТЕКСТ {target_cid}")
                return
            text_to_send = custom_text
        elif cmd.startswith("прав"):
            # правка текста
            custom_text = arg.replace("прав ", "", 1).strip() if arg and arg.startswith("прав ") else None
            if not custom_text:
                send_tg(f"❌ После 'прав' укажи текст: прав ТЕКСТ {target_cid}")
                return
            text_to_send = custom_text
        else:
            # Любой другой текст = пользовательский ответ
            text_to_send = text
        
        # Отправить в Avito
        try:
            token = get_token()
            r = send_avito(token, target_cid, text_to_send)
            if r.status_code in [200, 201]:
                pending.pop(target_cid, None)
                save_json(PENDING_FILE, pending)
                send_tg(f"✅ Отправлено в чат {target_cid}")
            else:
                send_tg(f"❌ Ошибка Avito: {r.status_code} {r.text[:200]}")
        except Exception as e:
            send_tg(f"❌ Ошибка: {e}")
    except Exception as e:
        print(f"handle_tg_update error: {e}")

# === Flask app ===
app = Flask(__name__)

@app.route("/")
def index():
    return "Avito Bot for MAGIC | GAME is running"

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "avito-bot"})

@app.route("/poll")
def poll():
    """Ручной запуск polling (для теста)."""
    n = poll_once()
    return jsonify({"status": "polling_executed", "new_count": n})

@app.route("/clear")
def clear():
    """Очистить state для нового polling."""
    try:
        save_json(SENT_FILE, {})
        save_json(PENDING_FILE, {})
        return jsonify({"status": "cleared"})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/tg-webhook", methods=["POST"])
def tg_webhook():
    """Принимает обновления от Telegram (для ответов Ильи)."""
    update = request.json
    handle_tg_update(update)
    return jsonify({"ok": True})

# === Polling thread ===
def polling_loop():
    while True:
        try:
            poll_once()
        except Exception as e:
            print(f"polling error: {e}")
        time.sleep(60)

# Запускаем polling в фоне
threading.Thread(target=polling_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
