# «Суть» в Docker: сервер, интерфейс и модели поиска. Ollama — на компьютере (см. DOCKER.md).
# Два варианта: sut:cpu (docker-compose.yml) и sut:gpu с CUDA (docker-compose.gpu.yml) — различаются только TORCH_INDEX.

# ---------- 1. Сборка интерфейса ----------
# Свежий Node нужен yt-dlp: с Node 20 он не решает проверку YouTube и видео не скачивается
FROM node:24-bookworm-slim AS node

FROM node AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. Сервис ----------
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# PyTorch с поддержкой видеокарты (без неё тоже работает, на процессоре).
# Для образа только под процессор: --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cpu
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu128
RUN pip install torch --index-url ${TORCH_INDEX}

COPY backend/requirements.txt backend/requirements.txt
# В образе только для процессора библиотеки NVIDIA (~1,3 ГБ) не нужны
RUN if echo "$TORCH_INDEX" | grep -q "/cpu"; then grep -v "^nvidia-" backend/requirements.txt > /tmp/req.txt; \
    else cp backend/requirements.txt /tmp/req.txt; fi \
    && pip install -r /tmp/req.txt

# Node нужен yt-dlp: YouTube отдаёт видео только после выполнения своего JavaScript.
# Копируется после библиотек, чтобы обновление Node не заставляло перекачивать PyTorch.
COPY --from=node /usr/local/bin/node /usr/local/bin/node

COPY backend/ backend/
COPY scripts/download_models.py scripts/export_youtube_cookies.py scripts/
COPY --from=web /web/dist frontend/dist
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Данные (база, видео, модели, вход в YouTube) — в томе /data, переживают пересоздание контейнера.
# Библиотеки CUDA из pip-пакетов nvidia — для распознавания речи на видеокарте.
ENV SUT_DATA=/data \
    SUT_MODELS=/data/models \
    SUT_YT_COOKIES=/data/youtube_cookies.txt \
    SUT_OLLAMA=http://host.docker.internal:11434 \
    SUT_DROP_GGUF=1 \
    LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib

VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

ENTRYPOINT ["/entrypoint.sh"]
