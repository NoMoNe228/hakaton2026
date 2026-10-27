"""Очередь обработки лекций: скачивание → звук → расшифровка → индекс → конспект → перевод.

Два фоновых потока. Поток подготовки скачивает видео и извлекает звук — ему нужна сеть, а не видеокарта,
поэтому следующая лекция готовится, пока текущая распознаётся. Основной поток берёт подготовленные
лекции по одной: расшифровка, индекс, конспект. Уже сделанные шаги при перезапуске пропускаются,
поэтому прерванная обработка продолжается с места остановки.
Перевод — задача второй очереди: лекция уже «готова», а новая загрузка его прерывает
и идёт первой; перевод потом продолжается с той же фразы.
"""
import heapq
import itertools
import queue
import shutil
import threading
import traceback

import numpy as np

from . import db, llm, media, outline, search, translate
from .config import CHUNK_OVERLAP_SEGMENTS, CHUNK_TARGET_SEC, VIDEOS_DIR

# Доля общей полосы прогресса на каждый шаг
STAGES = {"downloading": (0, 10), "extracting": (10, 14), "transcribing": (14, 75), "indexing": (75, 82),
          "summarizing": (82, 100)}

# (важность, номер, лекция, задача): 0 — распознавание и индекс, 1 — конспект, 2 — перевод.
# Конспекты ждут, пока распознаются все скачанные лекции: так каждая раньше становится доступной для поиска
_q: "queue.PriorityQueue[tuple[int, int, str, str]]" = queue.PriorityQueue()
# Подготовка (скачивание и звук) — своя очередь, по порядку добавления
_prep: "queue.Queue[str]" = queue.Queue()
_prep_queued = set()
_seq = itertools.count()
PRIORITY = {"full": 0, "summary": 1, "translate": 2}
_tr_queued = set()
_cancelled = set()  # удалённые лекции: их обработку бросаем на первом же шаге
_running = {"lecture_id": None, "job": None}  # что сейчас делает основной поток — для статуса перевода


class Cancelled(Exception):
    """Лекцию удалили, пока она обрабатывалась."""


def _gone(lecture_id) -> bool:
    return lecture_id in _cancelled or db.get_lecture(lecture_id) is None


def _check(lecture_id):
    if _gone(lecture_id):
        raise Cancelled(lecture_id)


def _stage(lecture_id, stage, frac=0.0):
    # Ход шага сообщается часто (каждая фраза Whisper, каждый кусок скачивания) — заодно проверяем,
    # не удалили ли лекцию, чтобы не распознавать и не качать её зря
    _check(lecture_id)
    a, b = STAGES[stage]
    db.update_lecture(lecture_id, status=stage, progress=round(a + (b - a) * frac, 1))


def cancel(lecture_id: str):
    """Лекцию удаляют: убрать её задачи из очереди, а идущую обработку остановить."""
    _cancelled.add(lecture_id)
    _tr_queued.discard(lecture_id)
    _prep_queued.discard(lecture_id)  # поток подготовки пропустит её, когда дойдёт
    with _q.mutex:
        kept = [item for item in _q.queue if item[2] != lecture_id]
        removed = len(_q.queue) - len(kept)
        _q.queue[:] = kept
        heapq.heapify(_q.queue)
        _q.unfinished_tasks -= removed


def enqueue(lecture_id: str, job: str = "full", first: bool = False):
    """first — в начало своей очереди (прерванный перевод продолжается раньше остальных)."""
    if job == "full":
        # Сначала подготовка: видео и звук; в основную очередь лекция попадёт уже готовой к распознаванию
        if lecture_id not in _prep_queued:
            _prep_queued.add(lecture_id)
            _prep.put(lecture_id)
        return
    if job == "translate":
        if lecture_id in _tr_queued:
            return
        _tr_queued.add(lecture_id)
    n = next(_seq)
    _q.put((PRIORITY.get(job, 0), -n if first else n, lecture_id, job))


def _urgent() -> bool:
    """Ждёт ли в очереди новая лекция или конспект — тогда перевод уступает им место."""
    with _q.mutex:
        return any(item[0] < PRIORITY["translate"] for item in _q.queue)


def _prepare(lecture_id: str):
    """Шаги 1–2: видео и звук. Видеокарта не нужна — идут параллельно с распознаванием другой лекции."""
    _check(lecture_id)
    lec = db.get_lecture(lecture_id)
    folder = VIDEOS_DIR / lecture_id
    folder.mkdir(exist_ok=True)

    # 1. Видео
    video = folder / lec["video_file"] if lec["video_file"] else None
    if not video or not video.exists():
        if lec["source_type"] != "url":
            raise RuntimeError("Файл видео не найден")
        _stage(lecture_id, "downloading")
        video, title, key = media.download(lec["source_url"], folder,
                                           lambda f: _stage(lecture_id, "downloading", f))
        fields = {"video_file": video.name}
        if key:
            fields["source_key"] = key
        if lec["title"] in ("", lec["source_url"]):
            fields["title"] = title
        _check(lecture_id)
        db.update_lecture(lecture_id, **fields)
        lec = db.get_lecture(lecture_id)

    # 2. Звук
    _check(lecture_id)
    audio = folder / "audio.wav"
    if not audio.exists():
        _stage(lecture_id, "extracting")
        part = folder / "audio.part.wav"  # недописанный звук не должен выглядеть готовым
        media.extract_audio(video, part)
        part.replace(audio)
        db.update_lecture(lecture_id, duration=media.duration(audio))
    return audio


def _process(lecture_id: str):
    _check(lecture_id)
    # Обычно подготовка уже сделана потоком подготовки; если нет (старая очередь) — делаем здесь
    audio = _prepare(lecture_id)

    # 3. Расшифровка
    segments = db.get_segments(lecture_id)
    if not segments:
        _stage(lecture_id, "transcribing")
        llm.unload()
        segs, lang, dur = _transcribe(audio, lambda f: _stage(lecture_id, "transcribing", f))
        if not segs:
            raise RuntimeError("В видео не найдено речи")
        _check(lecture_id)
        db.executemany("INSERT INTO segments (lecture_id, idx, start, end, text) VALUES (?, ?, ?, ?, ?)",
                       [(lecture_id, i, s["start"], s["end"], s["text"]) for i, s in enumerate(segs)])
        db.update_lecture(lecture_id, language=lang, duration=dur)
        segments = db.get_segments(lecture_id)

    # 4. Индекс для поиска
    if not db.query("SELECT 1 FROM chunks WHERE lecture_id = ? LIMIT 1", (lecture_id,)):
        _stage(lecture_id, "indexing")
        search.index_lecture(lecture_id, segments, CHUNK_TARGET_SEC, CHUNK_OVERLAP_SEGMENTS)

    # 5. Конспект — отдельной задачей после распознавания остальных скачанных лекций;
    #    по лекции уже можно искать
    if not db.get_lecture(lecture_id).get("summary"):
        db.update_lecture(lecture_id, status="indexed", progress=STAGES["indexing"][1])
        enqueue(lecture_id, "summary")
        return
    db.update_lecture(lecture_id, status="ready", progress=100)
    # 6. Перевод расшифровки и заголовков — отдельной задачей, лекцией уже можно пользоваться
    enqueue(lecture_id, "translate")


def _transcribe(audio, on_progress):
    from . import transcribe  # тяжёлый импорт — только когда нужен

    return transcribe.transcribe(audio, on_progress)


def summarize(lecture_id: str):
    lec = db.get_lecture(lecture_id)
    _stage(lecture_id, "summarizing")
    segments = db.get_segments(lecture_id, with_embeddings=True)
    for s in segments:
        s["vec"] = np.frombuffer(s.pop("embedding"), dtype=np.float16).astype(np.float32) if s["embedding"] else None
    rows = db.query("SELECT start, end, text, embedding FROM chunks WHERE lecture_id = ? ORDER BY idx",
                    (lecture_id,))
    chunks = [{"start": r["start"], "end": r["end"], "text": r["text"]} for r in rows]
    emb = np.stack([np.frombuffer(r["embedding"], dtype=np.float16).astype(np.float32) for r in rows])
    try:
        res = outline.build(lec["title"], segments, chunks, emb,
                            lambda f: _stage(lecture_id, "summarizing", f))
        # Оглавление новое — его заголовки на втором языке переведём заново
        db.update_lecture(lecture_id, summary=res["summary"], outline=res["outline"], terms=res["terms"],
                          summary_error=None, outline_alt=None)
    except Cancelled:
        raise
    except llm.LLMUnavailable as e:
        db.update_lecture(lecture_id, summary_error=str(e))
    except Exception as e:
        traceback.print_exc()
        db.update_lecture(lecture_id, summary_error=f"Не удалось составить конспект: {e}")


def run_translation(lecture_id: str):
    lec = db.get_lecture(lecture_id)
    if not lec or not translate.needed(lec):
        return
    try:
        if not translate.translate_segments(lecture_id, lambda: _urgent() or _gone(lecture_id)):
            if not _gone(lecture_id):
                enqueue(lecture_id, "translate", first=True)  # уступили место новой лекции — продолжим сразу после неё
            return
        lec = db.get_lecture(lecture_id)
        if lec.get("outline") and not lec.get("outline_alt"):
            translate.translate_titles(lecture_id)
        db.update_lecture(lecture_id, tr_error=None)
        search.INDEX.rebuild()  # поиск по словам перевода
    except llm.LLMUnavailable as e:
        db.update_lecture(lecture_id, tr_error=str(e))
    except Exception as e:
        traceback.print_exc()
        db.update_lecture(lecture_id, tr_error=f"Не удалось перевести: {e}")


def _prep_worker():
    while True:
        lecture_id = _prep.get()
        try:
            if lecture_id not in _prep_queued or _gone(lecture_id):
                continue
            _prepare(lecture_id)
            _check(lecture_id)
            db.update_lecture(lecture_id, status="waiting", progress=STAGES["extracting"][1])
            n = next(_seq)
            _q.put((0, n, lecture_id, "full"))
        except Exception as e:
            if not isinstance(e, Cancelled) and not _gone(lecture_id):
                traceback.print_exc()
                db.update_lecture(lecture_id, status="error", error=str(e)[:500])
        finally:
            _prep_queued.discard(lecture_id)
            if _gone(lecture_id):
                _forget(lecture_id)
            _prep.task_done()


def translation_queue_state(lecture_id: str) -> dict:
    """Переводится ли лекция прямо сейчас или ждёт своей очереди."""
    active = _running["lecture_id"] == lecture_id and _running["job"] == "translate"
    return {"active": active, "queued": not active and lecture_id in _tr_queued}


def _worker():
    while True:
        _, _, lecture_id, job = _q.get()
        _running.update(lecture_id=lecture_id, job=job)
        try:
            if job == "translate":
                _tr_queued.discard(lecture_id)
            if not db.get_lecture(lecture_id):
                continue
            if job == "summary":
                summarize(lecture_id)
                db.update_lecture(lecture_id, status="ready", progress=100)
                enqueue(lecture_id, "translate")
            elif job == "translate":
                run_translation(lecture_id)
            else:
                _process(lecture_id)
        except Exception as e:
            # Удалённую лекцию бросаем молча (скачивание оборачивает нашу остановку в свою ошибку — поэтому _gone)
            if not isinstance(e, Cancelled) and not _gone(lecture_id):
                traceback.print_exc()
                db.update_lecture(lecture_id, status="error", error=str(e)[:500])
        finally:
            _running.update(lecture_id=None, job=None)
            if _gone(lecture_id):
                _forget(lecture_id)
            _q.task_done()


def _forget(lecture_id: str):
    """Убрать следы удалённой лекции: обработка могла записать фразы и заново создать папку с видео."""
    print(f"[pipeline] лекция {lecture_id} удалена — обработка остановлена")
    db.delete_lecture(lecture_id)
    shutil.rmtree(VIDEOS_DIR / lecture_id, ignore_errors=True)
    _cancelled.discard(lecture_id)


def start():
    # Ошибки скачивания, сохранённые до понятных сообщений, переписываем по-русски
    for r in db.query("SELECT id, error FROM lectures WHERE status = 'error' AND error LIKE 'ERROR:%'"):
        db.update_lecture(r["id"], error=media.explain_download_error(r["error"]))
    # Лекциям по ссылке, добавленным до появления ключа, проставляем его
    for r in db.query("SELECT id, source_url FROM lectures WHERE source_url IS NOT NULL AND source_key IS NULL"):
        key = media.source_key(r["source_url"])
        if key:
            db.update_lecture(r["id"], source_key=key)
    threading.Thread(target=_worker, daemon=True, name="pipeline").start()
    threading.Thread(target=_prep_worker, daemon=True, name="pipeline-prep").start()
    # Продолжить то, что прервалось при прошлом запуске
    for r in db.query("SELECT id FROM lectures WHERE status NOT IN ('ready', 'error') ORDER BY created_at"):
        enqueue(r["id"])
    # Догнать перевод у лекций, обработанных раньше (или прерванный при прошлом запуске)
    for r in db.query("SELECT id FROM lectures WHERE status = 'ready' ORDER BY created_at"):
        if translate.needed(db.get_lecture(r["id"])):
            enqueue(r["id"], "translate")
