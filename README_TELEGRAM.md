# Telegram-бот + Mini App (внешние ИИ API)

Проект использует Python, FastAPI, aiogram и OpenAI API. Локальные `torch`, `sentence-transformers` и `faster-whisper` больше не нужны: транскрибация, эмбеддинги и конспект выполняются через API.

## Что реализовано

- Telegram-бот с кнопкой открытия Mini App.
- Mini App для загрузки и просмотра видеолекций.
- Извлечение аудио через FFmpeg.
- Транскрибация через OpenAI Audio API с сегментами и таймкодами. Аудио делится на части по 10 минут, чтобы ограничить размер отправляемого файла.
- Семантический поиск с помощью `text-embedding-3-small`; векторы хранятся в SQLite.
- Конспект через `gpt-4o-mini`, с резервным извлекающим конспектом при ошибке API.

## 1. Создайте Telegram-бота

1. Откройте `@BotFather` в Telegram.
2. Выполните `/newbot` и сохраните токен.

## 2. Настройте OpenAI API

Создайте API-ключ в https://platform.openai.com/api-keys и настройте биллинг, если он требуется вашему аккаунту. API оплачивается отдельно от подписки ChatGPT.

Скопируйте `.env.example` в `.env` и заполните значения:

```dotenv
BOT_TOKEN=токен_от_BotFather
MINI_APP_URL=https://ваш-публичный-домен.example
OPENAI_API_KEY=ваш_OpenAI_API_ключ
OPENAI_TRANSCRIPTION_MODEL=whisper-1
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_SUMMARY_MODEL=gpt-4o-mini
MAX_UPLOAD_MB=1024
```

Не публикуйте `.env`, API-ключ или токен бота и не добавляйте их в Git.

## 3. Установите FFmpeg

FFmpeg нужен для извлечения звука и разбиения аудио на части.

Windows: установите FFmpeg и добавьте его `bin`-папку в `PATH`. Проверьте:

```powershell
ffmpeg -version
```

## 4. Установите Python-зависимости

В PowerShell из папки проекта:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

В requirements больше нет PyTorch, NumPy, `sentence-transformers` или `faster-whisper`, поэтому эти пакеты не должны устанавливаться.

## 5. Запустите приложение

Первый терминал — веб-сервер:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Второй терминал, в той же папке и активированном окружении — Telegram-бот:

```powershell
python bot.py
```

Проверьте сервер локально: http://127.0.0.1:8000/api/health

## 6. Подключите Mini App

Telegram требует публичный HTTPS URL для Mini App. Локальный `http://127.0.0.1:8000` не подходит для кнопки в Telegram. Разверните FastAPI на хостинге с HTTPS или используйте HTTPS-туннель для тестирования, затем укажите корневой адрес в `MINI_APP_URL` и перезапустите бота.

## Важные ограничения

- Для транскрибации, эмбеддингов и конспекта нужен интернет и действующий OpenAI API-ключ; запросы могут тарифицироваться.
- Большие видео занимают место на диске. Настройте лимиты загрузки и reverse proxy на хостинге.
- Бот пока не импортирует видео, присланные непосредственно в чат: загрузка выполняется через Mini App.
- Перед публичным использованием необходимо добавить проверку подписи Telegram `initData`, привязать записи к Telegram-пользователям и изолировать данные разных пользователей. Текущая версия предназначена для локальной разработки/демонстрации, а не для публичного многопользовательского развёртывания.
