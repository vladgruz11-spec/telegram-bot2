import os
import json
import time
import sqlite3
import requests
from pathlib import Path

from telegram import Update, LabeledPrice
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
KIE_API_KEY = os.getenv("KIE_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN не найден!")

if not KIE_API_KEY:
    raise RuntimeError("KIE_API_KEY не найден!")

MEDIA_DIR = Path("media")
MEDIA_DIR.mkdir(exist_ok=True)

DB_PATH = "users.db"
user_states = {}
def add_paid_credit(user_id: int, amount: int = 1):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET paid_credits = paid_credits + ? WHERE user_id = ?",
        (amount, user_id)
    )
    conn.commit()
    conn.close()


def decrement_paid_credit(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET paid_credits = paid_credits - 1 WHERE user_id = ? AND paid_credits > 0",
        (user_id,)
    )
    conn.commit()
    conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            free_used INTEGER DEFAULT 0,
            paid_credits INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def get_user(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT free_used, paid_credits FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()

    if row is None:
        cur.execute(
            "INSERT INTO users (user_id, free_used, paid_credits) VALUES (?, 0, 0)",
            (user_id,)
        )
        conn.commit()
        free_used = 0
        paid_credits = 0
    else:
        free_used, paid_credits = row

    conn.close()
    return free_used, paid_credits


def increment_free_used(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET free_used = free_used + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def upload_image_to_kie(image_path: str) -> str:
    url = "https://kieai.redpandaai.co/api/file-stream-upload"

    headers = {
        "Authorization": f"Bearer {KIE_API_KEY}"
    }

    with open(image_path, "rb") as f:
        files = {
            "file": (Path(image_path).name, f, "image/jpeg")
        }
        data = {
            "uploadPath": "images/tarantino-bot",
            "fileName": Path(image_path).name
        }

        response = requests.post(url, headers=headers, files=files, data=data, timeout=600)

    response.raise_for_status()
    result = response.json()

    if not result.get("success"):
        raise RuntimeError(f"Ошибка загрузки картинки в Kie: {result}")

    download_url = result["data"]["downloadUrl"]
    return download_url


def create_kie_video_task(image_url: str, prompt: str) -> str:
    url = "https://api.kie.ai/api/v1/jobs/createTask"

    headers = {
        "Authorization": f"Bearer {KIE_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "wan/2-6-image-to-video",
        "input": {
            "prompt": prompt,
            "image_urls": [image_url],
            "duration": "5",
            "resolution": "720p",
            "nsfw_checker": False
        }
    }

    response = requests.post(url, headers=headers, json=payload, timeout=600)
    response.raise_for_status()
    result = response.json()

    if result.get("code") != 200:
        raise RuntimeError(f"Ошибка создания видео-задачи Kie: {result}")

    return result["data"]["taskId"]


def wait_kie_video_result(task_id: str) -> str:
    url = "https://api.kie.ai/api/v1/jobs/recordInfo"

    headers = {
        "Authorization": f"Bearer {KIE_API_KEY}"
    }

    for _ in range(600):
        response = requests.get(
            url,
            headers=headers,
            params={"taskId": task_id},
            timeout=600
        )
        response.raise_for_status()
        result = response.json()

        data = result.get("data", {})
        state = data.get("state")

        if state == "success":
            result_json_raw = data.get("resultJson")
            result_json = json.loads(result_json_raw)

            video_urls = (
                result_json.get("resultUrls")
                or result_json.get("videoUrls")
                or result_json.get("videos")
                or []
            )

            if not video_urls:
                raise RuntimeError(f"Видео готово, но ссылка не найдена: {result_json}")

            return video_urls[0]

        if state == "fail":
            raise RuntimeError(f"Kie не смог сгенерировать видео: {data.get('failMsg')}")

        time.sleep(10)

    raise RuntimeError("Видео генерировалось слишком долго. Попробуй позже.")


def download_video(video_url: str, user_id: int) -> str:
    video_path = MEDIA_DIR / f"{user_id}_result.mp4"

    response = requests.get(video_url, timeout=180)
    response.raise_for_status()

    with open(video_path, "wb") as f:
        f.write(response.content)

    return str(video_path)


def generate_video_from_image(image_path: str, prompt: str, user_id: int) -> str:
    image_url = upload_image_to_kie(image_path)
    task_id = create_kie_video_task(image_url, prompt)
    video_url = wait_kie_video_result(task_id)
    video_path = download_video(video_url, user_id)
    return video_path


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Шаг 1: Перед тем как начать, подпишись на канал https://t.me/+dFJBLVKcU_BkNTY6, чтобы нас не потерять, если бота заблокируют!\n\n"
        "Затем возвращайся, и приступим к СОЗДАНИЮ ВИДЕО\n\n"
        "Шаг 1: отправь мне картинку."
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    free_used, paid_credits = get_user(user_id)

    if free_used >= 1 and paid_credits <= 0:
        await update.message.reply_text(
            "💳 Бесплатная генерация закончилась.\n\n"
"Чтобы создать ещё видео, напиши /buy и купи 1 генерацию."
        )
        return

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    image_path = MEDIA_DIR / f"{user_id}_{photo.file_unique_id}.jpg"
    await file.download_to_drive(str(image_path))

    user_states[user_id] = {"image_path": str(image_path)}

    await update.message.reply_text(
        "✅ Картинку получил.\n\n"
        "Теперь отправь описание видео."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    prompt = update.message.text

    if user_id not in user_states:
        await update.message.reply_text("Сначала отправь картинку, потом описание.")
        return

    free_used, paid_credits = get_user(user_id)

    if free_used >= 1 and paid_credits <= 0:
        await update.message.reply_text(
            "💳 Бесплатные генерации закончились.\n\n"
            "Следующим этапом подключим оплату."
        )
        return

    image_path = user_states[user_id]["image_path"]

    await update.message.reply_text(
        "🎥 Запускаю нейросеть.\n\n"
        "Генерация видео может занять 2–10 минут. Не отправляй новую картинку, пока я работаю."
    )

    try:
        video_path = generate_video_from_image(image_path, prompt, user_id)

        await update.message.reply_video(
            video=open(video_path, "rb"),
            caption="✅ Готово! Вот твоё AI-видео."
        )

        if free_used < 1:
            increment_free_used(user_id)
        else:
            decrement_paid_credit(user_id)

        free_used_after, _ = get_user(user_id)
        free_left = max(0, 1 - free_used_after)

        await update.message.reply_text(
            f"Осталось бесплатных генераций: {free_left}"
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка генерации видео:\n\n{e}"
        )

    user_states.pop(user_id, None)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prices = [LabeledPrice("1 AI-видео", 50)]

    await update.message.reply_invoice(
        title="1 AI-видео",
        description="Оплата одной генерации AI-видео",
        payload=f"video_generation_{update.message.from_user.id}",
        provider_token="",
        currency="XTR",
        prices=prices,
    )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    add_paid_credit(user_id, 1)

    await update.message.reply_text(
        "✅ Оплата прошла успешно!\n\n"
        "Тебе добавлена 1 платная генерация.\n\n"
        "Теперь отправь картинку."
    )

def main():
    init_db()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":    
    main()
