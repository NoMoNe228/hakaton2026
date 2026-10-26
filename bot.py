"""Telegram bot entry point for the Video Lecture Search Mini App.

Required environment variables:
  BOT_TOKEN      Token from @BotFather
  MINI_APP_URL   Public HTTPS URL of the FastAPI web app
"""
import asyncio
import os
import logging
from dotenv import load_dotenv
from pathlib import Path
from aiogram import Bot, Dispatcher, F

load_dotenv(Path(__file__).resolve().parent / ".env")
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MINI_APP_URL = os.getenv("MINI_APP_URL", "").strip()


def app_keyboard():
    if not MINI_APP_URL.startswith("https://"):
        return None
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔎 Открыть поиск по лекциям", web_app=WebAppInfo(url=MINI_APP_URL))]],
        resize_keyboard=True,
        input_field_placeholder="Откройте поиск по видеолекциям",
    )


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Укажите BOT_TOKEN в переменных окружения (токен от @BotFather).")
    if not MINI_APP_URL.startswith("https://"):
        raise RuntimeError("MINI_APP_URL должен быть публичным HTTPS-адресом Mini App.")

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def start(message: Message):
        await message.answer(
            "Привет! Я помогу искать нужные моменты в видеолекциях по смыслу.\n\n"
            "Откройте Mini App, загрузите лекцию и дождитесь обработки. Затем задайте вопрос "
            "обычным языком — я покажу подходящие фрагменты с таймкодами.",
            reply_markup=app_keyboard(),
        )

    @dp.message(Command("help"))
    async def help_command(message: Message):
        await message.answer(
            "Как пользоваться:\n"
            "1. Нажмите «Открыть поиск по лекциям».\n"
            "2. Загрузите MP4/WebM.\n"
            "3. Дождитесь окончания транскрибации.\n"
            "4. Введите вопрос по содержанию лекции.\n"
            "5. Нажмите на найденный фрагмент, чтобы перейти к таймкоду.",
            reply_markup=app_keyboard(),
        )

    @dp.message(F.video)
    async def video_received(message: Message):
        await message.answer(
            "Видео получено в чате. В текущей версии загрузите его через Mini App, "
            "чтобы оно попало в индекс семантического поиска.",
            reply_markup=app_keyboard(),
        )

    @dp.message()
    async def fallback(message: Message):
        await message.answer(
            "Для поиска по лекциям откройте Mini App кнопкой ниже.",
            reply_markup=app_keyboard(),
        )

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
