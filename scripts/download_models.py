"""Скачивает модели в data/models многими потоками.

Зачем: при медленном или ограниченном доступе к HuggingFace одно соединение быстро «душится»,
а много коротких запросов по кусочкам файла качают в разы быстрее. Прерванную загрузку можно
просто запустить снова — готовые куски не перекачиваются.

Запуск: .venv\\Scripts\\python.exe scripts\\download_models.py
"""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "data" / "models"
HF = "https://huggingface.co"
PART = 8 << 20
THREADS = 16

FILES = {
    "faster-whisper-large-v3-turbo": ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", [
        "config.json", "preprocessor_config.json", "tokenizer.json", "vocabulary.json", "model.bin"]),
    "bge-m3": ("BAAI/bge-m3", [
        "config.json", "config_sentence_transformers.json", "modules.json", "sentence_bert_config.json",
        "1_Pooling/config.json", "sentencepiece.bpe.model", "special_tokens_map.json", "tokenizer.json",
        "tokenizer_config.json", "pytorch_model.bin"]),
    "bge-reranker-v2-m3": ("BAAI/bge-reranker-v2-m3", [
        "config.json", "sentencepiece.bpe.model", "special_tokens_map.json", "tokenizer.json",
        "tokenizer_config.json", "model.safetensors"]),
    "qwen3-4b-instruct": ("unsloth/Qwen3-4B-Instruct-2507-GGUF", ["Qwen3-4B-Instruct-2507-Q4_K_M.gguf"]),
}

done_bytes = 0
lock = threading.Lock()


def size_of(client, url):
    r = client.get(url, headers={"Range": "bytes=0-0"})
    r.raise_for_status()
    return int(r.headers["Content-Range"].split("/")[1])


def fetch_part(url, dest, a, b, state_file, state):
    global done_bytes
    for attempt in range(20):
        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(20, read=20)) as c:
                r = c.get(url, headers={"Range": f"bytes={a}-{b}"})
                r.raise_for_status()
                data = r.content
            if len(data) != b - a + 1:
                raise IOError("неполный кусок")
            with lock:
                with dest.open("r+b") as f:
                    f.seek(a)
                    f.write(data)
                state.add(a)
                state_file.write_text(json.dumps(sorted(state)))
                done_bytes += len(data)
            return
        except Exception as e:
            time.sleep(min(10, 1 + attempt))
            last = e
    raise RuntimeError(f"кусок {a}-{b}: {last}")


def download(repo, name, folder):
    url = f"{HF}/{repo}/resolve/main/{name}"
    final = folder / name
    final.parent.mkdir(parents=True, exist_ok=True)
    # Качаем во временный файл и переименовываем в конце: недокачанный файл не должен выглядеть готовым
    dest = final.with_name(final.name + ".part")
    state_file = final.with_name(final.name + ".parts")
    with httpx.Client(follow_redirects=True, timeout=30) as c:
        total = size_of(c, url)
    if final.exists() and final.stat().st_size == total and not state_file.exists():
        return 0
    if final.exists() and state_file.exists() and not dest.exists():
        final.rename(dest)  # докачка файла, начатого прежней версией загрузчика
    if not dest.exists() or dest.stat().st_size != total:
        with dest.open("wb") as f:
            f.truncate(total)
        state_file.unlink(missing_ok=True)
    state = set(json.loads(state_file.read_text())) if state_file.exists() else set()
    parts = [(a, min(a + PART, total) - 1) for a in range(0, total, PART) if a not in state]
    if total < PART:  # мелкие файлы — одним запросом
        parts = [(0, total - 1)] if 0 not in state else []
    with ThreadPoolExecutor(THREADS) as ex:
        for f in [ex.submit(fetch_part, url, dest, a, b, state_file, state) for a, b in parts]:
            f.result()
    dest.replace(final)
    state_file.unlink(missing_ok=True)
    return total


def ollama_has(name="qwen-instruct:4b") -> bool:
    try:
        return any(m["name"] == name for m in httpx.get("http://127.0.0.1:11434/api/tags", timeout=3).json()["models"])
    except Exception:
        return False


def main():
    only = set(sys.argv[1:])
    skip = {"qwen3-4b-instruct"} if ollama_has() else set()
    if skip:
        print("Языковая модель уже подключена к Ollama — пропускаю")
    jobs = [(k, repo, f) for k, (repo, files) in FILES.items()
            if (not only or k in only) and k not in skip for f in files]
    t0 = time.time()

    def report():
        while not stop.is_set():
            mb = done_bytes / 2**20
            print(f"  скачано {mb:,.0f} МБ, {mb / max(time.time() - t0, 1):.1f} МБ/с", flush=True)
            stop.wait(10)

    stop = threading.Event()
    threading.Thread(target=report, daemon=True).start()
    for key, repo, name in jobs:
        print(f"{key}/{name}", flush=True)
        download(repo, name, MODELS / key)
    stop.set()
    print(f"Готово за {time.time() - t0:.0f} с. Модели в {MODELS}")
    if (not only or "qwen3-4b-instruct" in only) and not skip:
        register_ollama()


def register_ollama(name="qwen-instruct:4b"):
    """Подключает скачанный файл модели к Ollama, без выхода Ollama в интернет."""
    import os
    import shutil
    import subprocess

    folder = MODELS / "qwen3-4b-instruct"
    gguf = next(folder.glob("*.gguf"), None)
    exe = shutil.which("ollama") or os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
    if not gguf or not Path(exe).exists():
        print("Ollama или файл модели не найдены — подключите модель вручную (см. README)")
        return
    (folder / "Modelfile").write_text(f"FROM ./{gguf.name}\nPARAMETER temperature 0.3\n", encoding="utf-8")
    r = subprocess.run([exe, "create", name, "-f", "Modelfile"], cwd=folder)
    print(f"Модель {name} подключена к Ollama" if r.returncode == 0 else "Не удалось подключить модель к Ollama")


if __name__ == "__main__":
    main()
