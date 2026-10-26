# Семантический поиск по видеолекциям — Telegram Mini App

Прототип для хакатона «Киберрывок 2026». Пользователь открывает Mini App из Telegram-бота, загружает видеолекцию и ищет фрагменты по смыслу с переходом к таймкоду.

## Стек

- Python + FastAPI
- Telegram-бот на aiogram 3
- SQLite
- FFmpeg для извлечения аудио и разбиения на части
- OpenAI Audio API для транскрибации с таймкодами
- OpenAI Embeddings API (`text-embedding-3-small`) для семантического поиска
- OpenAI Chat Completions API (`gpt-4o-mini`) для конспекта
- HTML/CSS/JavaScript для Mini App

Локальные PyTorch, `faster-whisper` и `sentence-transformers` не используются.

## Запуск

См. полную инструкцию в `README_TELEGRAM.md`. Кратко:

1. Установить FFmpeg и проверить `ffmpeg -version`.
2. Скопировать `.env.example` в `.env`, заполнить `BOT_TOKEN`, `MINI_APP_URL` и `OPENAI_API_KEY`.
3. Установить зависимости: `python -m pip install -r requirements.txt`.
4. Запустить веб-приложение: `python -m uvicorn main:app --host 127.0.0.1 --port 8000`.
5. В отдельном терминале запустить бота: `python bot.py`.
6. Указать публичный HTTPS URL в `MINI_APP_URL`: Telegram Mini App не открывает локальный localhost.

API-транскрибации, эмбеддингов и конспектов требует интернета и может тарифицироваться отдельно от ChatGPT.
