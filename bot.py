import os
import json
import time
import sqlite3
import requests
from pathlib import Path

from telegram import Update, LabeledPrice, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
KIE_API_KEY = os.getenv("KIE_API_KEY")

YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN не найден!")

if not KIE_API_KEY:
    raise RuntimeError("KIE_API_KEY не найден!")

if not YOOKASSA_SHOP_ID:
    raise RuntimeError("YOOKASSA_SHOP_ID не найден!")

if not YOOKASSA_SECRET_KEY:
    raise RuntimeError("YOOKASSA_SECRET_KEY не найден!")

MEDIA_DIR = Path("media")
MEDIA_DIR.mkdir(exist_ok=True)

DB_PATH = "/var/data/users.db"
user_states = {}

ADMIN_IDS = {
    6164104276
}
VIDEO_PRICES = {
    "5": 99,
    "10": 155,
}
def paid_menu():
    keyboard = [
        ["💳 Пополнить баланс: /buy"],
        ["🎁 БЕСПЛАТНЫЕ генерации: /ref"],
        ["🚀 Запустить бота"],
        ["📘 Инструкция: /help"],
        ["👤 Мой баланс: /profile"],
        ["🆘 Связаться с поддержкой"]
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )
def duration_menu():
    keyboard = [
        ["5 секунд", "10 секунд"]
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )
def duration_menu_5_only():
    keyboard = [
        ["5 секунд"]
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )
def topup_menu():
    keyboard = [
        ["💳 Пополнить баланс на 199 ₽"],
        ["💳 Пополнить баланс на 399 ₽"],
        ["💳 Пополнить баланс на 699 ₽"],
        ["🚀 Запустить бота"]
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )
def inline_menu():
    keyboard = [
        [InlineKeyboardButton("💳 Пополнить баланс", callback_data="buy")],
        [InlineKeyboardButton("🎁 БЕСПЛАТНЫЕ генерации", callback_data="ref")],
        [InlineKeyboardButton("🚀 Запустить бота", callback_data="start")],
        [InlineKeyboardButton("📘 Инструкция", callback_data="help")],
        [InlineKeyboardButton("👤 Мой баланс", callback_data="profile")],
        [InlineKeyboardButton("🆘 Связаться с поддержкой", url="https://t.me/Vlad101ss")]
    ]

    return InlineKeyboardMarkup(keyboard)
def add_paid_credit(user_id: int, amount: int = 1):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET paid_credits = paid_credits + ? WHERE user_id = ?",
        (amount, user_id)
    )
    conn.commit()
    conn.close()


def decrement_paid_credit(user_id: int, amount: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET paid_credits = paid_credits - ? WHERE user_id = ? AND paid_credits >= ?",
        (amount, user_id, amount)
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

    try:
        cur.execute("ALTER TABLE users ADD COLUMN username TEXT")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()
    
    
def get_user(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "SELECT free_used, paid_credits FROM users WHERE user_id = ?",
        (user_id,)
    )
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


def save_username(user_id: int, username):
    if not username:
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, free_used, paid_credits, username) VALUES (?, 0, 0, ?)",
        (user_id, username.lower())
    )

    cur.execute(
        "UPDATE users SET username = ? WHERE user_id = ?",
        (username.lower(), user_id)
    )

    conn.commit()
    conn.close()


def get_user_id_by_username(username: str):
    username = username.replace("@", "").lower()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id FROM users WHERE username = ?",
        (username,)
    )

    row = cur.fetchone()
    conn.close()

    if row is None:
        return None

    return row[0]
    
def give_balance(user_id: int, amount: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, free_used, paid_credits) VALUES (?, 0, 0)",
        (user_id,)
    )

    cur.execute(
        "UPDATE users SET paid_credits = paid_credits + ? WHERE user_id = ?",
        (amount, user_id)
    )

    conn.commit()
    conn.close()


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

        response = requests.post(url, headers=headers, files=files, data=data, timeout=3600)

    response.raise_for_status()
    result = response.json()

    if not result.get("success"):
        raise RuntimeError(f"Ошибка загрузки картинки в Kie: {result}")

    download_url = result["data"]["downloadUrl"]
    return download_url


def create_kie_video_task(image_url: str, prompt: str, duration: str) -> str:
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
            "duration": duration,
            "resolution": "720p",
            "nsfw_checker": False
        }
    }

    response = requests.post(url, headers=headers, json=payload, timeout=3600)
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

    for _ in range(3600):
        try:
            response = requests.get(
                url,
                headers=headers,
                params={"taskId": task_id},
                timeout=3600
            )
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.Timeout:
            time.sleep(10)
            continue

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

    response = requests.get(video_url, timeout=3600)
    response.raise_for_status()

    with open(video_path, "wb") as f:
        f.write(response.content)

    return str(video_path)


def create_yookassa_payment(user_id: int, amount: int) -> str:
    url = "https://api.yookassa.ru/v3/payments"

    headers = {
        "Idempotence-Key": f"topup_{user_id}_{amount}_{int(time.time())}",
        "Content-Type": "application/json"
    }

    payload = {
        "amount": {
            "value": f"{amount}.00",
            "currency": "RUB"
        },
        "capture": True,
        "confirmation": {
            "type": "redirect",
            "return_url": "https://t.me/Tarantino2Bot"
        },
        "description": f"Пополнение баланса Telegram-бота на {amount} рублей",
        "metadata": {
            "user_id": str(user_id),
            "amount": str(amount)
        }
    }

    response = requests.post(
        url,
        auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY),
        headers=headers,
        json=payload,
        timeout=60
    )

    response.raise_for_status()
    result = response.json()

    return result["confirmation"]["confirmation_url"], result["id"]
def generate_video_from_image(image_path: str, prompt: str, user_id: int, duration: str) -> str:
    image_url = upload_image_to_kie(image_path)
    task_id = create_kie_video_task(image_url, prompt, duration)
    video_url = wait_kie_video_result(task_id)
    video_path = download_video(video_url, user_id)
    return video_path

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Меню бота",
        reply_markup=inline_menu()
    )

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    save_username(user_id, update.message.from_user.username)
    await update.message.reply_text(
        f"Твой Telegram ID:\n{user_id}"
    )


async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.message.from_user.id

    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Нет доступа.")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Используй:\n"
            "/give USER_ID СУММА\n\n"
            "Пример:\n"
            "/give 123456789 99"
        )
        return

    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
    except:
        await update.message.reply_text("❌ Ошибка формата.")
        return

    give_balance(target_id, amount)

    await update.message.reply_text(
        f"✅ Пользователю {target_id} выдано {amount} ₽"
    )
async def giveuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.message.from_user.id

    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Нет доступа.")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Используй:\n"
            "/giveuser @username СУММА\n\n"
            "Пример:\n"
            "/giveuser @username 99"
        )
        return

    username = context.args[0]

    try:
        amount = int(context.args[1])
    except:
        await update.message.reply_text("❌ Ошибка суммы.")
        return

    target_id = get_user_id_by_username(username)

    if target_id is None:
        await update.message.reply_text(
            "❌ Пользователь не найден.\n"
            "Он должен сначала написать боту /start."
        )
        return

    give_balance(target_id, amount)

    await update.message.reply_text(
        f"✅ @{username.replace('@', '')} выдано {amount} ₽"
    )
def check_yookassa_payment(payment_id: str) -> bool:
    url = f"https://api.yookassa.ru/v3/payments/{payment_id}"

    response = requests.get(
        url,
        auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY),
        timeout=60
    )

    response.raise_for_status()
    result = response.json()

    return result.get("status") == "succeeded"
async def menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    action = query.data

    if action.startswith("checkpay_"):
        parts = action.split("_")
        payment_id = parts[1]
        amount = int(parts[2])

        try:
            paid = check_yookassa_payment(payment_id)
        except Exception as e:
            await query.message.reply_text(
                f"❌ Не удалось проверить оплату:\n\n{e}"
            )
            return

        if not paid:
            await query.message.reply_text(
                "⏳ Оплата пока не найдена.\n\n"
                "Если ты уже оплатил — подожди 10–20 секунд и нажми кнопку ещё раз."
            )
            return

        add_paid_credit(user_id, amount)
        _, paid_credits = get_user(user_id)

        await query.message.reply_text(
            f"✅ Оплата получена!\n\n"
            f"Баланс пополнен на {amount} ₽.\n"
            f"Текущий баланс: {paid_credits} ₽.\n\n"
            f"Теперь отправь картинку."
        )
        return

    if action == "buy":
        await query.message.reply_text(
            "💳 Пополнение баланса:\n\n"
            "Стоимость генераций:\n"
            "5 секунд — 99 ₽\n"
            "10 секунд — 155 ₽\n"
            "Выбери сумму пополнения:",
            reply_markup=topup_menu()
        )
        return

    if action == "ref":
        await query.message.reply_text("🎁 Реферальную программу подключим следующим этапом.")
        return

    if action == "start":
        save_username(user_id, query.from_user.username)

        await query.message.reply_text(
            "Шаг 1: Перед тем как начать, подпишись на канал https://t.me/Tarantino2Baza, чтобы нас не потерять, если бота заблокируют!\n\n"
            "Затем возвращайся, и приступим к СОЗДАНИЮ ВИДЕО",
            disable_web_page_preview=True
    )

        await query.message.reply_text(
            "Шаг 2: отправь мне картинку, которую хочешь оживить!"
    )
    return

    if action == "help":
        await query.message.reply_text(
            "📘 Инструкция:\n\n"
            "1. Нажми /start (запустить бота)\n"
            "2. Отправь картинку (если вы хотите оживить человека, отправляйте фото, на котором хорошо видно его лицо, желательно в анфас)\n"
            "3. Выбери длительность видео:\n"
            "На данный момент, оптимальное время роликов -  5 и 10 секунд. При увеличении длительности, нейросеть начинает искажать лица, движения и структуру происходящего, делает анимацию менее реалистичной.\n"
            "Если вы хотите создавать более длительные ролики с вашими персонажами, лучшим решением будет техника first picture-last picture, при которой вы создаете много коротких роликов, в которых первый кадр последующего является последним кадром предыдущего. Простыми словами:\n"
            "а) загружаете картинку,\n"
            "б) получаете первый ролик,\n"
            "в) делаете скриншот последнего кадра этого ролика,\n"
            "г) загружаете скриншот,\n"
            "д) получаете второй ролик,\n"
            "е) повторяете, пока длительность вас не устроит,\n"
            "ж) склеиваете получившиеся короткие ролики в один длинный при помощи любого приложения для монтажа\n"
            "з) наслаждаетесь результатом!\n"
            "4. Внимание! Нажимая /start, вы соглашаетесь с условиями использования бота "Тарантино 2.0"\n"
            "Условия:\n"
            "Пользователь самостоятельно несёт ответственность за загружаемые изображения, текстовые описания и созданные материалы.\n"
            "Запрещается использовать бот для создания с целью распространения контента, нарушающего законодательство или права третьих лиц, включая:\n\n"

            "• незаконный контент\n"
            "• материалы сексуального характера с несовершеннолетними\n"
            "• экстремизм, терроризм, разжигание ненависти\n"
            "• мошенничество и введение в заблуждение\n"
            "• клевету и нарушение репутации\n"
            "• незаконное использование чужих изображений, лиц или авторских материалов\n"
            "• иной запрещённый контент.\n\n"

            "Администрация бота не одобряет и не поощряет нарушение закона!\n"
            "Бот является автоматическим инструментом генерации контента. Ответственность за использование результатов несёт пользователь."
        )
        return

    if action == "profile":
        free_used, paid_credits = get_user(user_id)
        free_left = max(0, 1 - free_used)

        await query.message.reply_text(
            f"👤 Твой баланс:\n\n"
            f"Бесплатных генераций: {free_left}\n"
            f"Баланс: {paid_credits} ₽\n\n"
            f"Стоимость:\n"
            f"5 секунд — {VIDEO_PRICES['5']} ₽\n"
            f"10 секунд — {VIDEO_PRICES['10']} ₽"
        )
        return
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    save_username(user_id, update.message.from_user.username)
    
    await update.message.reply_text(
        "Шаг 1: Перед тем как начать, подпишись на канал https://t.me/Tarantino2Baza, чтобы нас не потерять, если бота заблокируют!\n\n"
        "Затем возвращайся, и приступим к СОЗДАНИЮ ВИДЕО",
        disable_web_page_preview=True
    )

    await update.message.reply_text(
        "Шаг 2: отправь мне картинку, которую хочешь оживить!"
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    free_used, paid_credits = get_user(user_id)

    if free_used >= 1 and paid_credits < VIDEO_PRICES["5"]:
        await update.message.reply_text(
            "💳Недостаточно средств для генерации.\n\n"
            "👇Пополнить баланс или получить БЕСПЛАТНО👇"
        )

        await update.message.reply_text(
            "Меню бота",
            reply_markup=inline_menu()
        )
        return

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    image_path = MEDIA_DIR / f"{user_id}_{photo.file_unique_id}.jpg"
    await file.download_to_drive(str(image_path))

    user_states[user_id] = {"image_path": str(image_path)}

    if free_used < 1:
        user_states[user_id]["duration"] = "5"

        await update.message.reply_text(
            "✅ Картинку получил.\n\n"
            "Теперь отправь описание видео."
        )
        return

    if paid_credits < VIDEO_PRICES["10"]:
        await update.message.reply_text(
            "✅ Картинку получил.\n\n"
            "Выбери длительность видео:",
            reply_markup=duration_menu_5_only()
        )
        return

    await update.message.reply_text(
        "✅ Картинку получил.\n\n"
        "Выбери длительность видео:",
        reply_markup=duration_menu()
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    prompt = update.message.text

    if prompt == "💳 Купить генерации: /buy":
        await buy(update, context)
        return

    if prompt.startswith("💳 Пополнить баланс на "):
        amount_text = (
            prompt
            .replace("💳 Пополнить баланс на ", "")
            .replace(" ₽", "")
            .strip()
        )
        amount = int(amount_text)

        payment_url, payment_id = create_yookassa_payment(user_id, amount)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Оплатить", url=payment_url)],
            [InlineKeyboardButton("✅ Проверить оплату", callback_data=f"checkpay_{payment_id}_{amount}")]
        ])

        await update.message.reply_text(
            f"💳 Пополнение баланса на {amount} ₽\n\n"
            f"1. Нажми «Оплатить»\n"
            f"2. После оплаты вернись сюда\n"
            f"3. Нажми «✅ Проверить оплату»",
            reply_markup=keyboard
        )
        return

    if prompt == "🎁 БЕСПЛАТНЫЕ генерации: /ref":
        await update.message.reply_text("🎁 Реферальную программу подключим следующим этапом.")
        return

    if prompt == "🚀 Запустить бота":
        await menu(update, context)
        return

    if prompt == "📘 Инструкция: /help":
        await update.message.reply_text(
            "📘 Инструкция:\n\n"
            "1. Нажми /start (запустить бота)\n"
            "2. Отправь картинку (если вы хотите оживить человека, отправляйте фото, на котором хорошо видно его лицо, желательно в анфас)\n"
            "3. Выбери длительность видео:\n"
            "На данный момент, оптимальное время роликов -  5 и 10 секунд. При увеличении длительности, нейросеть начинает искажать лица, движения и структуру происходящего, делает анимацию менее реалистичной.\n"
            "Если вы хотите создавать более длительные ролики с вашими персонажами, лучшим решением будет техника first picture-last picture, при которой вы создаете много коротких роликов, в которых первый кадр последующего является последним кадром предыдущего. Простыми словами:\n"
            "а) загружаете картинку,\n"
            "б) получаете первый ролик,\n"
            "в) делаете скриншот последнего кадра этого ролика,\n"
            "г) загружаете скриншот,\n"
            "д) получаете второй ролик,\n"
            "е) повторяете, пока длительность вас не устроит,\n"
            "ж) склеиваете получившиеся короткие ролики в один длинный при помощи любого приложения для монтажа\n"
            "з) наслаждаетесь результатом!\n"
            "4. Внимание! Нажимая /start, вы соглашаетесь с условиями использования бота "Тарантино 2.0"\n"
            "Условия:\n"
            "Пользователь самостоятельно несёт ответственность за загружаемые изображения, текстовые описания и созданные материалы.\n"
            "Запрещается использовать бот для создания с целью распространения контента, нарушающего законодательство или права третьих лиц, включая:\n\n"

            "• незаконный контент\n"
            "• материалы сексуального характера с несовершеннолетними\n"
            "• экстремизм, терроризм, разжигание ненависти\n"
            "• мошенничество и введение в заблуждение\n"
            "• клевету и нарушение репутации\n"
            "• незаконное использование чужих изображений, лиц или авторских материалов\n"
            "• иной запрещённый контент.\n\n"

            "Администрация бота не одобряет и не поощряет нарушение закона!\n"
            "Бот является автоматическим инструментом генерации контента. Ответственность за использование результатов несёт пользователь."
        )
        return

    if prompt == "👤 Мой баланс: /profile":
        free_used, paid_credits = get_user(user_id)
        free_left = max(0, 1 - free_used)

        await update.message.reply_text(
            f"👤 Твой баланс:\n\n"
            f"Бесплатных генераций: {free_left}\n"
            f"Баланс: {paid_credits} ₽\n\n"
            f"Стоимость:\n"
            f"5 секунд — {VIDEO_PRICES['5']} ₽\n"
            f"10 секунд — {VIDEO_PRICES['10']} ₽\n"
        )
        return

    if prompt == "🆘 Связаться с поддержкой":
        await update.message.reply_text(
            "🆘 Написать в поддержку: https://t.me/Vlad101ss",
            disable_web_page_preview=True
        )
        return

    if prompt in ["5 секунд", "10 секунд"]:
        if user_id not in user_states:
            await update.message.reply_text("Сначала отправь картинку.")
            return

        free_used, paid_credits = get_user(user_id)
        selected_duration = prompt.replace(" секунд", "")
        selected_cost = VIDEO_PRICES[selected_duration]

        if free_used >= 1 and paid_credits < selected_cost:
            await update.message.reply_text(
                "💳Недостаточно средств для генерации.\n\n"
                "👇Пополнить баланс или получить БЕСПЛАТНО👇"
            )

            await update.message.reply_text(
                "Меню бота",
                reply_markup=inline_menu()
            )
            return

        user_states[user_id]["duration"] = selected_duration

        await update.message.reply_text("✍️ Теперь отправь описание видео.")
        return

    if user_id not in user_states:
        await update.message.reply_text("Сначала отправь картинку.")
        return

    if "duration" not in user_states[user_id]:
        await update.message.reply_text(
            "Сначала выбери длительность видео:",
            reply_markup=duration_menu()
        )
        return

    free_used, paid_credits = get_user(user_id)

    image_path = user_states[user_id]["image_path"]
    duration = user_states[user_id]["duration"]
    video_cost = VIDEO_PRICES[duration]

    if free_used >= 1 and paid_credits < video_cost:
        await update.message.reply_text(
            f"Баланс: {paid_credits} ₽"
        )

        await update.message.reply_text(
            "💳Недостаточно средств для генерации.\n\n"
            "👇Пополнить баланс или получить БЕСПЛАТНО👇"
        )

        await update.message.reply_text(
            "Меню бота",
            reply_markup=inline_menu()
        )
        return

    await update.message.reply_text(
        "🎥 Запускаю нейросеть.\n\n"
        "Генерация видео может занять 2–10 минут. Не отправляй новую картинку, пока я работаю."
    )

    try:
        video_path = generate_video_from_image(image_path, prompt, user_id, duration)

        if free_used < 1:
            increment_free_used(user_id)
        else:
            decrement_paid_credit(user_id, video_cost)

        try:
            with open(video_path, "rb") as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption="✅ Готово! Вот твоё AI-видео.",
                    read_timeout=3600,
                    write_timeout=3600,
                    connect_timeout=60,
                    pool_timeout=3600
                )
        except Exception:
            await update.message.reply_text(
                "⚠️ Видео было сгенерировано, но Telegram не смог его отправить.\n\n"
                "Напиши в поддержку:\n"
                "https://t.me/Vlad101ss",
                disable_web_page_preview=True
            )

        free_used_after, paid_credits_after = get_user(user_id)

        await update.message.reply_text(
            f"Баланс: {paid_credits_after} ₽"
        )

        if paid_credits_after <= 0:
            await update.message.reply_text(
                "💳Недостаточно средств для генерации.\n\n"
                "👇Пополнить баланс или получить БЕСПЛАТНО👇"
            )

            await update.message.reply_text(
                "Меню бота",
                reply_markup=inline_menu()
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Ошибка генерации видео:\n\n{e}"
        )

    user_states.pop(user_id, None)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 Пополнение баланса:\n\n"
        "Стоимость генераций:\n"
        "5 секунд — 99 ₽\n"
        "10 секунд — 155 ₽\n"
        "Выбери сумму пополнения:",
        reply_markup=topup_menu()
    )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    payload = update.message.successful_payment.invoice_payload

    if payload.startswith("topup_"):
        amount = int(payload.replace("topup_", ""))
        add_paid_credit(user_id, amount)

        _, paid_credits = get_user(user_id)

        await update.message.reply_text(
            f"✅ Баланс пополнен на {amount} ₽.\n\n"
            f"Текущий баланс: {paid_credits} ₽.\n\n"
            f"Теперь отправь картинку."
        )

def main():
    init_db()

    app = (
    ApplicationBuilder()
    .token(TELEGRAM_TOKEN)
    .connect_timeout(60)
    .read_timeout(3600)
    .write_timeout(3600)
    .pool_timeout(3600)
    .build()
)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("give", give))
    app.add_handler(CommandHandler("giveuser", giveuser))
    app.add_handler(CallbackQueryHandler(menu_button))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":    
    main()
