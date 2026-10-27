#!/bin/sh
set -e

# Модели: при первом запуске скачиваются в /data/models (~6 ГБ, плюс языковая модель для Ollama ~2,5 ГБ),
# при следующих запусках этот шаг занимает секунду и в интернет не ходит.
python /app/scripts/download_models.py --if-missing \
    || echo "Не все модели скачались — сервис запустится, недостающее докачается при следующем запуске"

exec python -m uvicorn app.main:app --app-dir /app/backend --host 0.0.0.0 --port 8000
