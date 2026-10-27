"""Локальная языковая модель через Ollama: конспект, структура лекции, ответы на вопросы."""
import json
import re
import threading

import httpx

from .config import LLM_MODEL, OLLAMA_URL


_thinking = {}

# Видеокарта занята распознаванием речи: Whisper и модели поиска вместе с языковой моделью в 6 ГБ
# не помещаются, Windows вытесняет память в ОЗУ — и распознавание, и ответ замедляются в разы.
# Пока флаг стоит, языковая модель работает на процессоре и выгружается сразу после ответа.
gpu_busy = threading.Event()


class LLMUnavailable(RuntimeError):
    pass


def _body(messages, stream, temperature, num_ctx):
    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": stream,
        "keep_alive": "10m",
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }
    if gpu_busy.is_set():
        body["options"]["num_gpu"] = 0  # ни одного слоя на видеокарту
        body["keep_alive"] = 0
    # У «рассуждающих» моделей отключаем рассуждения вслух — для конспекта они только замедляют
    if _supports_thinking():
        body["think"] = False
    return body


def _supports_thinking() -> bool:
    if LLM_MODEL not in _thinking:
        try:
            r = httpx.post(f"{OLLAMA_URL}/api/show", json={"model": LLM_MODEL}, timeout=5)
            _thinking[LLM_MODEL] = "thinking" in (r.json().get("capabilities") or [])
        except Exception:
            return False
    return _thinking[LLM_MODEL]


def available() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        names = {m["name"] for m in r.json().get("models", [])}
        return LLM_MODEL in names or f"{LLM_MODEL}:latest" in names
    except Exception:
        return False


def unload():
    """Освобождает видеопамять: распознаванию речи нужна вся видеокарта."""
    try:
        httpx.post(f"{OLLAMA_URL}/api/generate", json={"model": LLM_MODEL, "keep_alive": 0}, timeout=10)
    except Exception:
        pass


def chat(messages: list[dict], as_json=False, temperature=0.2, num_ctx=8192, timeout=600) -> str:
    body = _body(messages, False, temperature, num_ctx)
    if as_json:
        body["format"] = "json"
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=timeout)
    except httpx.HTTPError as e:
        raise LLMUnavailable("Ollama не запущена. Запустите её (значок в трее или команда «ollama serve») "
                             "и нажмите «Попробовать снова».") from e
    if r.status_code != 200:
        raise LLMUnavailable(_explain(r.status_code, r.text))
    return r.json()["message"]["content"]


def _explain(code, text) -> str:
    if code == 404 or "not found" in text:
        return (f"Языковая модель {LLM_MODEL} не установлена в Ollama. "
                "Запустите scripts/download_models.py qwen3-4b-instruct и нажмите «Попробовать снова».")
    return f"Ollama ответила ошибкой: {text[:300]}"


def chat_stream(messages: list[dict], temperature=0.3, num_ctx=8192):
    body = _body(messages, True, temperature, num_ctx)
    try:
        with httpx.stream("POST", f"{OLLAMA_URL}/api/chat", json=body, timeout=600) as r:
            if r.status_code != 200:
                raise LLMUnavailable(_explain(r.status_code, r.read().decode("utf-8", "replace")))
            for line in r.iter_lines():
                if line:
                    part = json.loads(line)
                    yield part.get("message", {}).get("content", "")
    except httpx.HTTPError as e:
        raise LLMUnavailable(f"Ollama не отвечает ({e})") from e


def chat_json(messages: list[dict], **kw) -> dict:
    raw = chat(messages, as_json=True, **kw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            return json.loads(m.group())
        raise
