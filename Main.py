#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging
import os
import subprocess
import tempfile
import requests
from datetime import datetime, timedelta
from PIL import Image

from telegram import (
    Update,
    InputMediaPhoto,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8371527070:AAEZogSITpmU6Ttcnrj-gujMflxFWEj9GcQ"
BASE_URL = "https://kis.vgltu.ru/schedule"
GROUP_ENCODED = "%D0%98%D0%A11-237-%D0%9E%D0%A2"  # И1-237-ОТ

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Постоянная клавиатура внизу экрана
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("📅 Эта неделя")],
        [KeyboardButton("➡️ Следующая неделя")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
    is_persistent=True,
    input_field_placeholder="Выбери неделю…"
)


def get_monday(date: datetime.date) -> datetime.date:
    return date - timedelta(days=date.weekday())


def get_current_monday() -> str:
    return get_monday(datetime.now().date()).isoformat()


def get_next_monday() -> str:
    return (get_monday(datetime.now().date()) + timedelta(days=7)).isoformat()


def build_url(monday: str) -> str:
    return f"{BASE_URL}?date={monday}&group={GROUP_ENCODED}"


def schedule_exists(monday_str: str) -> bool:
    url = build_url(monday_str)
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        logger.info(f"Проверка {monday_str} → статус {r.status_code}, длина {len(r.text)}")

        if r.status_code != 200:
            return False

        text_lower = r.text.lower()

        if "проверьте правильно ли введены данные" in text_lower:
            logger.info(f"Обнаружена фраза ошибки для {monday_str}")
            return False

        error_markers = ["не найдено", "расписание отсутствует", "ошибка", "пусто"]
        if any(m in text_lower for m in error_markers):
            return False

        has_indicators = any(word in text_lower for word in [
            "понедельник", "вторник", "среда", "четверг", "пятница", "суббота",
            "пара", "занятие", "ауд.", "аудитория", "дисциплина", "преподаватель",
            "<table", "№ пары"
        ])

        logger.info(f"{monday_str} → есть признаки расписания: {has_indicators}")
        return has_indicators

    except Exception as e:
        logger.warning(f"Ошибка при проверке {monday_str}: {e}")
        return False


def find_wkhtmltoimage() -> str | None:
    paths = [
        "wkhtmltoimage",
        "/usr/bin/wkhtmltoimage",
        "/usr/local/bin/wkhtmltoimage",
        r"C:\Program Files\wkhtmltopdf\bin\wkhtmltoimage.exe",
        r"C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltoimage.exe",
    ]
    for p in paths:
        try:
            if subprocess.run([p, "--version"], capture_output=True, timeout=4).returncode == 0:
                return p
        except:
            pass
    return None


def split_image(image_path: str, max_h: int = 980, max_parts: int = 5) -> list[str]:
    try:
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        if h <= max_h:
            return [image_path]

        parts = []
        tmp = os.path.dirname(image_path)
        y = 0
        part_count = 0

        while y < h and part_count < max_parts:
            y2 = min(y + max_h, h)
            part_img = img.crop((0, y, w, y2))
            ppath = os.path.join(tmp, f"part_{len(parts)+1}.png")
            part_img.save(ppath, "PNG", optimize=True)
            parts.append(ppath)
            y = y2
            part_count += 1

        if y < h:
            logger.warning(f"Изображение обрезано: отправлено только {max_parts} частей")

        return parts
    except Exception as e:
        logger.error(f"split error: {e}")
        return []


async def generate_and_send_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, monday_str: str, status_msg):
    wk = find_wkhtmltoimage()
    if not wk:
        await status_msg.edit_text("❌ wkhtmltoimage не найден на сервере")
        return

    url = build_url(monday_str)
    await status_msg.edit_text(f"⏳ Загружаю расписание на {monday_str} ...")

    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Ошибка загрузки {url}: {e}")
        await status_msg.edit_text("❌ Не удалось загрузить страницу расписания")
        return

    with tempfile.TemporaryDirectory() as tmp:
        html = os.path.join(tmp, "s.html")
        png  = os.path.join(tmp, "s.png")

        with open(html, "w", encoding="utf-8") as f:
            f.write(r.text)

        await status_msg.edit_text("⏳ Конвертирую страницу в изображение...")

        cmd = [
            wk,
            "--width", "920",
            "--zoom", "1.15",
            "--quality", "82",
            "--format", "png",
            html, png
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, timeout=50)
            if res.returncode != 0 or not os.path.exists(png):
                err_msg = res.stderr.decode(errors="replace")[:200]
                logger.error(f"wkhtmltoimage ошибка: {err_msg}")
                await status_msg.edit_text("❌ Ошибка при создании изображения")
                return
        except subprocess.TimeoutExpired:
            await status_msg.edit_text("❌ Конвертация слишком долгая (таймаут)")
            return
        except Exception as e:
            await status_msg.edit_text(f"❌ Ошибка рендера: {str(e)[:120]}")
            return

        parts = split_image(png, max_h=980, max_parts=5)

        if not parts:
            await status_msg.edit_text("❌ Не удалось нарезать изображение")
            return

        await status_msg.edit_text(f"⏳ Отправляю расписание ({len(parts)} частей)...")

        media = [InputMediaPhoto(media=open(p, "rb").read()) for p in parts]

        await context.bot.send_media_group(
            chat_id=update.effective_chat.id,
            media=media
        )

        await status_msg.edit_text(f"✅ Расписание с {monday_str} отправлено")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я показываю расписание группы И1-237-ОТ.\n\n"
        "Выбирай неделю кнопками внизу экрана ⬇️",
        reply_markup=MAIN_KEYBOARD
    )
    msg = await update.message.reply_text("⌛ Определяю актуальную неделю...")
    monday = get_current_monday()
    await generate_and_send_schedule(update, context, monday, msg)


async def handle_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if "Эта неделя" in text or "текущ" in text.lower():
        monday = get_current_monday()
        status = await update.message.reply_text("⌛ Загружаю эту неделю...")
        await generate_and_send_schedule(update, context, monday, status)

    elif "Следующая" in text or "след" in text.lower():
        monday = get_next_monday()
        status = await update.message.reply_text("⌛ Загружаю следующую неделю...")
        await generate_and_send_schedule(update, context, monday, status)

    else:
        await update.message.reply_text(
            "Пожалуйста, используй кнопки внизу:\n"
            "📅 Эта неделя\n"
            "➡️ Следующая неделя",
            reply_markup=MAIN_KEYBOARD
        )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyboard))

    logger.info("Бот запущен")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()