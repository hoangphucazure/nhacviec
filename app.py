import datetime
import json
import os
import pytz
import requests
from flask import Flask, request
from upstash_redis import Redis

app = Flask(__name__)

# Đọc biến môi trường trên Vercel (hỗ trợ cả BOT_TOKEN hoặc TELEGRAM_TOKEN)
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
CRON_SECRET = os.environ.get("CRON_SECRET", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TIMEZONE = pytz.timezone("Asia/Ho_Chi_Minh")

# Tự động kết nối Upstash Redis qua Environment Variables của Vercel
redis = Redis.from_env()


def send_message(chat_id: str, text: str):
    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=5
    )


@app.route("/", methods=["GET"])
def home():
    return "Bot nhắc việc đang hoạt động!", 200


@app.route("/api/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}
    if "message" in update and "text" in update["message"]:
        chat_id = str(update["message"]["chat"]["id"])
        text = update["message"]["text"].strip()
        handle_command(chat_id, text)
    return "OK", 200


def handle_command(chat_id: str, text: str):
    redis_key = f"tasks:{chat_id}"
    raw_data = redis.get(redis_key)
    tasks = json.loads(raw_data) if raw_data else {}

    if text.startswith("/start"):
        msg = (
            "👋 **Bot nhắc việc hàng ngày**\n\n"
            "📌 **Các lệnh hỗ trợ:**\n"
            "• `/add HH:MM Nội dung` — Thêm việc (VD: `/add 07:30 Họp nhóm`)\n"
            "• `/list` — Xem danh sách việc\n"
            "• `/del ID` — Xóa việc (VD: `/del 1`)"
        )
        send_message(chat_id, msg)

    elif text.startswith("/add"):
        parts = text.split(" ", 2)
        if len(parts) < 3:
            send_message(chat_id, "⚠️ Sai cú pháp! Nhập: `/add HH:MM Nội dung`")
            return

        time_str, task_text = parts[1], parts[2]
        try:
            hour, minute = map(int, time_str.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
            time_str = f"{hour:02d}:{minute:02d}"
        except ValueError:
            send_message(chat_id, "❌ Giờ không hợp lệ! Nhập dạng 24h (VD: `08:05`, `21:30`).")
            return

        existing_ids = [int(k) for k in tasks.keys()]
        new_id = str(max(existing_ids) + 1 if existing_ids else 1)

        tasks[new_id] = {"time": time_str, "task": task_text}
        redis.set(redis_key, json.dumps(tasks, ensure_ascii=False))
        redis.sadd("active_users", chat_id)

        send_message(
            chat_id,
            f"✅ **Đã lưu nhắc việc mỗi ngày**\n🆔 ID: `{new_id}` | 🕒 `{time_str}`\n📝 {task_text}"
        )

    elif text.startswith("/list"):
        if not tasks:
            send_message(chat_id, "📭 Bạn chưa có lịch nhắc việc nào.")
            return

        sorted_items = sorted(tasks.items(), key=lambda x: x[1]["time"])
        msg = "📋 **DANH SÁCH NHẮC VIỆC HÀNG NGÀY:**\n\n"
        for tid, info in sorted_items:
            msg += f"🔹 **ID {tid}** | 🕒 `{info['time']}` — {info['task']}\n"
        send_message(chat_id, msg)

    elif text.startswith("/del"):
        parts = text.split(" ", 1)
        if len(parts) < 2:
            send_message(chat_id, "⚠️ Nhập ID cần xóa. VD: `/del 1`")
            return

        tid = parts[1].strip()
        if tid in tasks:
            removed = tasks.pop(tid)
            redis.set(redis_key, json.dumps(tasks, ensure_ascii=False))
            send_message(chat_id, f"🗑️ Đã xóa: `{removed['time']}` - {removed['task']}")
        else:
            send_message(chat_id, f"❌ Không tìm thấy ID `{tid}`.")


@app.route("/api/cron", methods=["GET"])
def cron():
    if CRON_SECRET and request.args.get("secret") != CRON_SECRET:
        return "Unauthorized", 401

    now_str = datetime.datetime.now(TIMEZONE).strftime("%H:%M")
    users = redis.smembers("active_users") or []
    sent_count = 0

    for chat_id in users:
        raw_data = redis.get(f"tasks:{chat_id}")
        if not raw_data:
            continue
        tasks = json.loads(raw_data)

        for tid, info in tasks.items():
            if info["time"] == now_str:
                send_message(
                    chat_id,
                    f"⏰ **NHẮC VIỆC HÀNG NGÀY ({now_str})**\n\n📌 **{info['task']}**"
                )
                sent_count += 1

    return f"Checked at {now_str}, sent {sent_count} reminders.", 200


if __name__ == "__main__":
    app.run()