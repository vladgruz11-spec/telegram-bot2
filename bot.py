import os
import sqlite3
from pathlib import Path

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN не найден!")

MEDIA_DIR = Path("media")
MEDIA_DIR.mkdir(exist_ok=True)

DB_PATH = "users.db"

user_states = {}


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
    cur.execute(
        "UPDATE users SET free_used = free_used + 1 WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 Привет! Я Tarantino 2.0\n\n"
        "Я могу сделать AI-видео из картинки и описания.\n\n"
        "У тебя есть 2 бесплатные генерации.\n\n"
        "Шаг 1: отправь мне картинку."
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    free_used, paid_credits = get_user(user_id)

    if free_used >= 2 and paid_credits <= 0:
        await update.message.reply_text(
            "💳 Бесплатные генерации закончились.\n\n"
            "Следующим этапом мы подключим оплату, и здесь будет кнопка оплаты."
        )
        return

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    image_path = MEDIA_DIR / f"{user_id}.jpg"
    await file.download_to_drive(str(image_path))

    user_states[user_id] = {
        "image_path": str(image_path)
    }

    await update.message.reply_text(
        "✅ Картинку получил.\n\n"
        "Теперь отправь описание видео.\n\n"
        "Например:\n"
        "Сделай кинематографичное видео, девушка идет по ночному Токио под дождём."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    if user_id not in user_states:
        await update.message.reply_text(
            "Сначала отправь картинку, потом описание."
        )
        return

    free_used, paid_credits = get_user(user_id)

    if free_used >= 2 and paid_credits <= 0:
        await update.message.reply_text(
            "💳 Бесплатные генерации закончились.\n\n"
            "Следующим этапом подключим оплату."
        )
        return

    image_path = user_states[user_id]["image_path"]

    await update.message.reply_text(
        "🎥 Отлично!\n\n"
        "Я получил:\n"
        f"🖼 Картинку: {image_path}\n"
        f"📝 Описание: {text}\n\n"
        "Сейчас здесь будет запуск нейросети для генерации видео.\n\n"
        "Пока это тестовый режим."
    )

    increment_free_used(user_id)

    free_used_after, paid_credits_after = get_user(user_id)
    free_left = max(0, 2 - free_used_after)

    await update.message.reply_text(
        f"✅ Тестовая генерация засчитана.\n\n"
        f"Осталось бесплатных генераций: {free_left}"
    )

    user_states.pop(user_id, None)


def main():
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
