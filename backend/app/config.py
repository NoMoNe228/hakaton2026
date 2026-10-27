"""Настройки сервиса. Любую можно поменять переменной окружения."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("SUT_DATA", ROOT / "data"))
VIDEOS_DIR = DATA_DIR / "videos"
# Вход в YouTube, выгруженный из браузера (scripts/export_youtube_cookies.py); нет файла — качаем без входа
YT_COOKIES = Path(os.getenv("SUT_YT_COOKIES", ROOT / "data" / "youtube_cookies.txt"))
DB_PATH = DATA_DIR / "sut.db"
FRONTEND_DIST = ROOT / "frontend" / "dist"

MODELS_DIR = Path(os.getenv("SUT_MODELS", ROOT / "data" / "models"))


def _model(env, local_name, hub_name):
    """Модель из data/models (скачана scripts/download_models.py), иначе — с HuggingFace."""
    if os.getenv(env):
        return os.getenv(env)
    local = MODELS_DIR / local_name
    # Недокачанная модель (есть файлы *.parts / *.part) не годится
    ready = (local / "config.json").exists() and not any(local.glob("*.part*"))
    return str(local) if ready else hub_name


# Модели. Все работают локально, без интернета (после первой загрузки весов).
WHISPER_MODEL = _model("SUT_WHISPER", "faster-whisper-large-v3-turbo", "large-v3-turbo")
EMBED_MODEL = _model("SUT_EMBED", "bge-m3", "BAAI/bge-m3")
# Модель-«судья» необязательна: пока она не скачана в data/models, поиск работает без неё
RERANK_MODEL = _model("SUT_RERANK", "bge-reranker-v2-m3", "")
OLLAMA_URL = os.getenv("SUT_OLLAMA", "http://127.0.0.1:11434")
LLM_MODEL = os.getenv("SUT_LLM", "qwen-instruct:4b")
DEVICE = os.getenv("SUT_DEVICE", "auto")  # auto | cuda | cpu

# Нарезка текста для поиска: куски ~30 секунд с захватом соседних фраз.
CHUNK_TARGET_SEC = 30.0
CHUNK_OVERLAP_SEGMENTS = 1

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


def device() -> str:
    if DEVICE != "auto":
        return DEVICE
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"
