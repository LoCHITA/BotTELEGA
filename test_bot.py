#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import subprocess
import tempfile

import requests
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

BOT_TOKEN = "8371527070:AAEZogSITpmU6Ttcnrj-gujMflxFWEj9GcQ"
SCHEDULE_URL = "https://kis.vgltu.ru/schedule?date=2026-02-08&group=%D0%98%D0%A11-237-%D0%9E%D0%A2"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}


def find_wkhtmltoimage():
    possible_paths = [
        "wkhtmltoimage",
        "C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltoimage.exe",
        "C:\\Program Files (x86)\\wkhtmltopdf\\bin\\wkhtmltoimage.exe",
    ]
    
    for path in possible_paths:
        try:
            result = subprocess.run([path, "--version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return path
        except:
            continue
    
    return None


def split_image_into_parts(image_path: str, num_parts: int = 3) -> list:
    try:
        img = Image.open(image_path)
        width, height = img.size
        
        part_height = height // num_parts
        part_paths = []
        temp_dir = os.path.dirname(image_path)
        
        for i in range(num_parts):
            top = i * part_height
            bottom = (i + 1) * part_height if i < num_parts - 1 else height
            
            part_img = img.crop((0, top, width, bottom))
            part_path = os.path.join(temp_dir, f"schedule_part_{i+1}.png")
            part_img.save(part_path, 'PNG', optimize=True)
            part_paths.append(part_path)
        
        return part_paths
        
    except Exception as e:
        logger.error(f"Ошибка разделения: {e}")
        return []


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # При /start сразу загружаем и отправляем расписание по статичной ссылке
    status_msg = await update.message.reply_text("⏳ Загружаю расписание по статичной ссылке...")

    try:
        wkhtmltoimage_path = find_wkhtmltoimage()
        if not wkhtmltoimage_path:
            await status_msg.edit_text("❌ wkhtmltoimage не найден!")
            return

        await status_msg.edit_text(f"⏳ Скачиваю: {SCHEDULE_URL}")
        response = requests.get(SCHEDULE_URL, timeout=15)
        response.raise_for_status()

        temp_dir = tempfile.mkdtemp()
        html_path = os.path.join(temp_dir, "schedule.html")
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(response.text)

        png_path = os.path.join(temp_dir, "schedule.png")
        await status_msg.edit_text("⏳ Конвертирую HTML → PNG...")

        result = subprocess.run([
            wkhtmltoimage_path, "--width", "1000", html_path, png_path
        ], capture_output=True, timeout=60)

        if result.returncode != 0 or not os.path.exists(png_path):
            await status_msg.edit_text("❌ Ошибка конвертации в изображение")
            return

        img = Image.open(png_path).convert('RGB')
        img.save(png_path, 'PNG', optimize=True)

        part_paths = split_image_into_parts(png_path, num_parts=3)
        if not part_paths:
            await status_msg.edit_text("❌ Ошибка разделения изображения")
            return

        await status_msg.edit_text("⏳ Отправляю расписание одним сообщением...")
        media_group = []
        for part_path in part_paths:
            with open(part_path, 'rb') as f:
                photo_bytes = f.read()
            media_group.append(InputMediaPhoto(media=photo_bytes))

        await context.bot.send_media_group(chat_id=update.effective_chat.id, media=media_group)
        await status_msg.edit_text("✅ Расписание отправлено")

        import shutil
        shutil.rmtree(temp_dir)

    except Exception as e:
        logger.error(f"Ошибка в /start: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)[:150]}")
        except:
            pass


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    try:
        wkhtmltoimage_path = find_wkhtmltoimage()
        if not wkhtmltoimage_path:
            await query.edit_message_text("❌ wkhtmltoimage не найден!")
            return
        
        await query.edit_message_text("⏳ Загружаю расписание...")
        
        url = "https://kis.vgltu.ru/schedule?date=2026-02-08&group=%D0%98%D0%A11-237-%D0%9E%D0%A2"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        
        temp_dir = tempfile.mkdtemp()
        html_path = os.path.join(temp_dir, "schedule.html")
        
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(response.text)
        
        png_path = os.path.join(temp_dir, "schedule.png")
        
        result = subprocess.run(
            [wkhtmltoimage_path, "--width", "1000", html_path, png_path],
            capture_output=True,
            timeout=60
        )
        
        if result.returncode != 0:
            await query.edit_message_text("❌ Ошибка конвертации!")
            return
        
        img = Image.open(png_path)
        img = img.convert('RGB')
        img.save(png_path, 'PNG', optimize=True)
        
        part_paths = split_image_into_parts(png_path, num_parts=3)
        
        if not part_paths:
            await query.edit_message_text("❌ Ошибка разделения!")
            return
        
        await query.edit_message_text("⏳ Отправляю одним сообщением...")
        
        media_group = []
        for i, part_path in enumerate(part_paths):
            with open(part_path, 'rb') as f:
                photo_bytes = f.read()
            media_group.append(InputMediaPhoto(media=photo_bytes))
        
        await context.bot.send_media_group(chat_id=update.effective_chat.id, media=media_group)
        
        await query.edit_message_text("✅ Готово!")
        
        import shutil
        shutil.rmtree(temp_dir)
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        try:
            await query.edit_message_text(f"❌ Ошибка: {str(e)[:100]}")
        except:
            pass


def main():
    logger.info("🤖 Бот запускается...")
    
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^get_week$"))
    
    logger.info("✅ Бот готов")
    application.run_polling()


if __name__ == "__main__":
    main()
