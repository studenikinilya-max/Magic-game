#!/usr/bin/env python3
"""
Webhook server for Avito + Polling trigger.
Render cron job pings /poll every 1 min to check new messages.
"""
import os
import time
import json
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# === Config ===
CLIENT_ID = os.environ.get("AVITO_CLIENT_ID", "37JdRroSViO7DszyZokh")
CLIENT_SECRET = os.environ.get("AVITO_CLIENT_SECRET", "cpLQcyFUcDCi94UDB9oUQz0afFc-64VAtHOIWzXl")
USER_ID = int(os.environ.get("AVITO_USER_ID", "220388146"))
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8850826923:AAEquMIf3KIYbBjwKxNHWyRjI-lFELjn0ns")
TELEGRAM_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "1046557548"))

# === Prices ===
PS5_TITLES = {
    8303523403: "PS5 + Подписка Deluxe",
    8303837408: "PS5 Slim с дисководом",
    8303089089: "PS5 Slim без дисковода",
    8302978306: "PS5 с дисководом",
    8335432496: "PS5 без дисковода",
}

# === Skip ===
SKIP_NAMES = ["GameShOp - PlayStation", "Moonqueen Store"]
SKIP_CHATS = ["u2i-n~ofJ4ijZkxJP6meVWIAcw"]

# === State ===
processed_messages = set()
last_check_time = 0


def first_name(full_name: str) -> str:
    if not full_name or full_name == "Пользователь":
        return ""
    name = full_name.split()[0] if full_name else ""
    if not name:
        return ""
    first = name[0]
    rest = name[1:]
    if first.isupper() and all('А' <= c <= 'я' or c in 'ёЁ' for c in rest):
        return name
    return ""


def get_token():
    r = requests.post(
        "https://api.avito.ru/token",
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={"grant_type": "client_credentials"}
    )
    return r.json().get("access_token")


def send_telegram(text: str):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            params={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def check_chat(chat, token, H):
    cid = chat["id"]
    if cid in SKIP_CHATS:
        return None
    users = chat.get("users", [])
    other = next((u for u in users if u.get("id") != USER_ID), {})
    name = other.get("name", "")
    if name in SKIP_NAMES:
        return None
    try:
        r = requests.get(
            f"https://api.avito.ru/messenger/v3/accounts/{USER_ID}/chats/{cid}/messages",
            headers=H, params={"limit": 5}, timeout=5
        )
        msgs = r.json().get("messages", [])
        if not msgs:
            return None
        last = msgs[0]
        msg_id = last.get("id", "")
        if msg_id in processed_messages:
            return None
        if last.get("author_id") == USER_ID:
            processed_messages.add(msg_id)
            return None
        text = last.get("content", {}).get("text", "")
        if not text:
            return None
        if "Системное сообщение" in text or "Ассистент Авито" in text:
            processed_messages.add(msg_id)
            return None
        t = text.lower()
        if any(w in t for w in ["купил", "уже купил", "спасибо", "успехов", "понял", "принял"]):
            processed_messages.add(msg_id)
            return None
        digits = text.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if digits.isdigit() and len(digits) >= 10:
            processed_messages.add(msg_id)
            return {
                "chat_id": cid, "name": name, "user_id": other.get("id"),
                "text": text, "type": "phone", "fname": first_name(name)
            }
        ctx = chat.get("context", {})
        item_id = ctx.get("value", {}).get("id") if isinstance(ctx.get("value"), dict) else None
        last_ilya = None
        for m in msgs:
            if m.get("author_id") == USER_ID:
                last_ilya = m.get("content", {}).get("text", "")
                break
        processed_messages.add(msg_id)
        return {
            "chat_id": cid, "name": name, "user_id": other.get("id"),
            "text": text[:500], "item_id": item_id, "type": "message",
            "last_ilya": last_ilya[:200] if last_ilya else None,
            "fname": first_name(name)
        }
    except Exception:
        return None


def make_draft(p):
    name = p.get("name", "?")
    fname = p.get("fname", "")
    text = p.get("text", "")
    item_id = p.get("item_id")
    msg_type = p.get("type", "message")
    last_ilya = p.get("last_ilya")

    item_title = PS5_TITLES.get(item_id, "?")
    item_price_map = {8303523403: 79990, 8303837408: 58990, 8303089089: 55490,
                      8302978306: 54990, 8335432496: 51490, 8111685512: 590}
    item_price = item_price_map.get(item_id, 0)

    if msg_type == "phone":
        return f"{fname + ', ' if fname else ''}хорошо, принял 👍\n\nНомер записал, жду деталей по комплекту."

    if not last_ilya or "Здравствуйте" not in last_ilya:
        if item_id in PS5_TITLES:
            return f"""{fname + ', ' if fname else ''}здравствуйте 🤝

Вас приветствует команда MAGIC | GAME

На связи Илья — готов помочь и ответить на любой вопрос! 🎮

Немного расскажу про нас ⚡

Работаем в сфере PS давно, на 3 города 🏙

🎮 Что предлагаем:
▫️ PS5 Fat / Slim / Pro — с дисководом и без
▫️ Геймпады, док-станции, диски, игры
▫️ Подписки PS Plus
▫️ Соберём комплект под вас 🔧

🤝 Как работаем:
1️⃣ Обсуждаем комплект заранее
2️⃣ Готовлю всё к встрече
3️⃣ Приезжаете — всё настроено и проверено
4️⃣ После покупки — на связи 24/7

Что интересует? Напишите, подберём комплект 👍

---

По объявлению, на которое вы написали — {item_title}, цена {item_price} ₽ ✅

Подскажите, какой комплект рассматриваете?"""
        else:
            return f"""{fname + ', ' if fname else ''}здравствуйте 🤝

Вас приветствует команда MAGIC | GAME

На связи Илья — готов помочь и ответить на любой вопрос! 🎮

Какой вопрос вас интересует?"""

    t = text.lower()
    if any(w in t for w in ["цена", "стоит", "сколько", "прайс", "стоит ли"]):
        if item_id in PS5_TITLES:
            return f"По объявлению, на которое вы написали — {item_title}, цена {item_price} ₽ ✅\n\nЧто-то добавим или базовый комплект?"
    if any(w in t for w in ["доставка", "отправить", "привезти"]):
        return "Доставка возможна, стоимость зависит от адреса 📦\n\nУточните, пожалуйста, ваш район — посчитаю?"
    if any(w in t for w in ["гарантия", "возврат"]):
        return "Гарантия 14 дней на проверку ✅\n\nЕсли что-то не понравится — возврат без вопросов."
    if "подписка" in t or "ps plus" in t.lower() or any(w in t for w in ["essential", "extra", "deluxe"]):
        return """🎮 Что входит в тарифы

▫️ Extra (440 игр) — сюжетные:
GTA V, Mortal Kombat, God of War
Horizon, Detroit, Spider-Man, The Last of Us

▫️ Deluxe (770 игр) — максимум:
Всё что в Extra + классика PS1/PS2 + стриминг облака

Оба тарифа дают возможность играть по сети ✅

Что интересует?"""
    if any(w in t for w in ["ревизия", "ревизии", "китайская"]):
        return """В наличии у нас много приставок. Ревизии тоже бывают разные. Между собой ревизии особо ничем не отличаются. Единственный момент: есть китайские ревизии, которые мы не закупаем, потому что там с трудностью добавляются аккаунты и приносят неудобства ✅"""
    if any(w in t for w in ["состояние", "разбиралас", "вскрывалас", "ремонт"]):
        return "Приставка в отличном состоянии, не вскрывалась, не ремонтировалась. Гарантию на неё мы предоставляем 👍"

    return f"{fname + ', ' if fname else ''}понял 👍\n\nПодскажите, что хотите уточнить?"


def do_poll():
    """Check all chats for new messages"""
    global last_check_time
    token = get_token()
    if not token:
        return {"error": "no token"}

    H = {"Authorization": f"Bearer {token}"}
    pending_list = []

    all_chats = []
    for offset in [0, 50, 100, 150]:
        r = requests.get(
            f"https://api.avito.ru/messenger/v2/accounts/{USER_ID}/chats",
            headers=H, params={"limit": 50, "offset": offset}
        )
        chats = r.json().get("chats", [])
        if not chats:
            break
        all_chats.extend(chats)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_chat, c, token, H): c for c in all_chats}
        for f in as_completed(futures):
            result = f.result()
            if result:
                pending_list.append(result)

    for p in pending_list:
        draft = make_draft(p)
        msg = f"""📬 <b>Новый чат</b>

<b>Клиент:</b> {p.get('fname', '') or p.get('name', '?')}
<b>Чат:</b> <code>{p.get('chat_id')}</code>
<b>Объявление:</b> {p.get('item_id')}

<b>Клиент написал:</b>
{p.get('text', '')}

<b>Черновик ответа:</b>
{draft}

Утверждаешь — отправлю. Скажи «да»."""
        send_telegram(msg)

    last_check_time = time.time()
    return {"pending": len(pending_list), "total_checked": len(all_chats)}


# === Flask ===
from flask import Flask, request, jsonify
app = Flask(__name__)


@app.route("/")
def home():
    return "Avito Webhook Server for MAGIC | GAME is running", 200


@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()}), 200


@app.route("/avito-webhook", methods=["POST"])
def avito_webhook():
    """Handle incoming webhook from Avito"""
    data = request.json
    print(f"📥 Webhook received: {data}")
    send_telegram(f"🔔 Avito webhook: {json.dumps(data, ensure_ascii=False)[:500]}")
    return jsonify({"status": "ok"}), 200


@app.route("/poll", methods=["GET", "POST"])
def poll():
    """Triggered by cron job to check for new messages"""
    try:
        result = do_poll()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
