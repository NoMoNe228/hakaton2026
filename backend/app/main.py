"""HTTP-сервер: API для интерфейса, отдача видео и собранного интерфейса."""
import json
import re
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, knowledge, llm, pipeline, search, translate
from .config import FRONTEND_DIST, LLM_MODEL, VIDEOS_DIR, device
from .textutil import fmt_time

VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}


@asynccontextmanager
async def lifespan(_app):
    # Модели поиска грузятся в фоне: сервер отвечает сразу, поиск включается через полминуты
    def warm():
        search.load_models()
        search.INDEX.rebuild()

    threading.Thread(target=warm, daemon=True).start()
    pipeline.start()
    yield


app = FastAPI(title="Суть — поиск по видеолекциям", lifespan=lifespan)
# Расширение браузера обращается к серверу со своей страницы chrome-extension://…
# (и стенд расширения с локального адреса — только этот компьютер)
app.add_middleware(CORSMiddleware, allow_origin_regex=r"^((chrome|moz)-extension://.*|http://(127\.0\.0\.1|localhost):\d+)$",
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(knowledge.router)  # база знаний курса: /api/knowledge


def _lecture_or_404(lecture_id):
    lec = db.get_lecture(lecture_id)
    if not lec:
        raise HTTPException(404, "Лекция не найдена")
    return lec


# ---------- Состояние ----------

@app.get("/api/health")
def health():
    return {"device": device(), "search_ready": search.models_ready(), "search_error": search.models_error(),
            "reranker": search.has_reranker(), "llm": LLM_MODEL, "llm_ready": llm.available()}


# ---------- Лекции ----------

def _translation(lec: dict) -> dict:
    return {**translate.state(lec), **pipeline.translation_queue_state(lec["id"])}


@app.get("/api/lectures")
def lectures():
    items = db.list_lectures()
    # У готовых лекций — ещё и ход перевода: «Готово» не значит, что перевод уже есть
    for item in items:
        if item["status"] == "ready":
            full = db.get_lecture(item["id"])
            if full:
                item["translation"] = _translation(full)
    return items


@app.post("/api/lectures/upload")
async def upload(file: UploadFile = File(...), title: str = Form("")):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(400, "Поддерживаются видео MP4, WebM, MOV, MKV, AVI")
    lecture_id = uuid.uuid4().hex[:12]
    folder = VIDEOS_DIR / lecture_id
    folder.mkdir(parents=True)
    dst = folder / f"source{ext}"
    with dst.open("wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
    if ext not in (".mp4", ".webm"):
        from . import media

        dst = media.to_browser_format(dst)
    else:
        dst = dst.rename(folder / f"video{ext}")
    db.create_lecture(lecture_id, title.strip() or Path(file.filename).stem, "file", video_file=dst.name)
    pipeline.enqueue(lecture_id)
    return db.get_lecture(lecture_id)


class UrlIn(BaseModel):
    url: str
    title: str = ""


@app.post("/api/lectures/url")
def add_url(body: UrlIn):
    url = body.url.strip()
    if not re.match(r"^https?://", url):
        raise HTTPException(400, "Нужна ссылка, начинающаяся с http:// или https://")
    from . import media

    key = media.source_key(url)
    # Это видео уже есть — не обрабатываем второй раз
    if key and (lec := db.find_by_source_key(key)):
        return lec
    lecture_id = uuid.uuid4().hex[:12]
    db.create_lecture(lecture_id, body.title.strip() or url, "url", source_url=url, source_key=key)
    pipeline.enqueue(lecture_id)
    return db.get_lecture(lecture_id)


@app.get("/api/lookup")
def lookup(url: str):
    """Для расширения браузера: есть ли у нас лекция для видео на этой странице."""
    from . import media

    key = media.source_key(url)
    return {"key": key, "supported": key is not None, "lecture": db.find_by_source_key(key) if key else None}


@app.get("/api/lectures/{lecture_id}")
def lecture(lecture_id: str):
    lec = _lecture_or_404(lecture_id)
    lec["translation"] = _translation(lec)
    return lec


class LecturePatch(BaseModel):
    title: str


@app.patch("/api/lectures/{lecture_id}")
def rename(lecture_id: str, body: LecturePatch):
    _lecture_or_404(lecture_id)
    db.update_lecture(lecture_id, title=body.title.strip() or "Без названия")
    search.INDEX.rebuild()
    return db.get_lecture(lecture_id)


@app.delete("/api/lectures/{lecture_id}")
def delete(lecture_id: str):
    _lecture_or_404(lecture_id)
    pipeline.cancel(lecture_id)  # снять из очереди и остановить обработку, если она идёт
    db.delete_lecture(lecture_id)
    shutil.rmtree(VIDEOS_DIR / lecture_id, ignore_errors=True)
    search.INDEX.rebuild()
    return {"ok": True}


@app.post("/api/lectures/{lecture_id}/summarize")
def resummarize(lecture_id: str):
    lec = _lecture_or_404(lecture_id)
    if lec["status"] not in db.SEARCHABLE:
        raise HTTPException(409, "Лекция ещё обрабатывается")
    db.update_lecture(lecture_id, summary=None, summary_error=None, status="summarizing")
    pipeline.enqueue(lecture_id, "summary")
    return {"ok": True}


@app.post("/api/lectures/{lecture_id}/translate")
def retranslate(lecture_id: str):
    """Догнать перевод (например, после ошибки Ollama). Уже переведённое не переводится заново."""
    lec = _lecture_or_404(lecture_id)
    if lec["status"] != "ready":
        raise HTTPException(409, "Лекция ещё обрабатывается")
    db.update_lecture(lecture_id, tr_error=None)
    pipeline.enqueue(lecture_id, "translate")
    return {"ok": True}


@app.post("/api/lectures/{lecture_id}/retry")
def retry(lecture_id: str):
    _lecture_or_404(lecture_id)
    db.update_lecture(lecture_id, status="queued", error=None, progress=0)
    pipeline.enqueue(lecture_id)
    return {"ok": True}


@app.get("/api/lectures/{lecture_id}/segments")
def segments(lecture_id: str):
    _lecture_or_404(lecture_id)
    return db.get_segments(lecture_id)


@app.api_route("/api/lectures/{lecture_id}/video", methods=["GET", "HEAD"])
def video(lecture_id: str):
    lec = _lecture_or_404(lecture_id)
    if not lec["video_file"]:
        raise HTTPException(404, "Видео ещё не загружено")
    path = VIDEOS_DIR / lecture_id / lec["video_file"]
    if not path.exists():
        raise HTTPException(404, "Видео не найдено")
    return FileResponse(path, media_type="video/webm" if path.suffix == ".webm" else "video/mp4")


@app.get("/api/lectures/{lecture_id}/thumb.jpg")
def thumb(lecture_id: str):
    lec = _lecture_or_404(lecture_id)
    folder = VIDEOS_DIR / lecture_id
    out = folder / "thumb.jpg"
    if not out.exists():
        if not lec["video_file"] or not (folder / lec["video_file"]).exists():
            raise HTTPException(404, "Видео ещё не загружено")
        from . import media

        # Кадр на 10% длительности: заставка в начале обычно пустая
        at = (lec["duration"] or 0) * 0.1 or 5.0
        try:
            media.thumbnail(folder / lec["video_file"], out, at)
        except RuntimeError:
            media.thumbnail(folder / lec["video_file"], out, 0)
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


def _vtt_time(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


@app.get("/api/lectures/{lecture_id}/subtitles.vtt")
def subtitles(lecture_id: str, lang: str = "orig"):
    """lang=tr — субтитры в переводе (где перевода ещё нет — оригинал)."""
    _lecture_or_404(lecture_id)
    lines = ["WEBVTT", ""]
    segs = db.get_segments(lecture_id)
    for s in translate.merged(segs) if lang == "tr" else segs:
        lines += [f"{_vtt_time(s['start'])} --> {_vtt_time(s['end'])}", s["text"], ""]
    return PlainTextResponse("\n".join(lines), media_type="text/vtt; charset=utf-8")


# ---------- Поиск и вопросы ----------

@app.get("/api/search")
def do_search(q: str, lecture_id: str | None = None, k: int = 10):
    if not search.models_ready():
        raise HTTPException(503, search.models_error() or "Модели поиска ещё загружаются, подождите несколько секунд")
    return {"query": q, "results": search.INDEX.search(q, lecture_id or None, k=min(max(k, 1), 30))}


class AskIn(BaseModel):
    question: str
    lecture_id: str | None = None
    history: list[dict] = []


@app.post("/api/ask")
def ask(body: AskIn):
    """Ответ на вопрос по лекции (или по всему курсу) с опорой на найденные фрагменты.
    Отдаётся построчно: сначала источники, затем текст ответа по кусочкам."""
    if not search.models_ready():
        raise HTTPException(503, "Модели поиска ещё загружаются")
    found = search.INDEX.search(body.question, body.lecture_id, k=6, min_score=0.01)
    many = body.lecture_id is None
    context = "\n\n".join(
        f"[{i + 1}] " + (f"Лекция «{r['lecture_title']}», " if many else "")
        + f"{fmt_time(r['start'])}–{fmt_time(r['end'])}: {r['text']}"
        for i, r in enumerate(found)
    )
    system = (
        "Ты отвечаешь на вопросы студента по видеолекциям. Используй только приведённые фрагменты лекций. "
        "Отвечай на языке вопроса, кратко и по делу. После утверждений ставь ссылку на фрагмент в виде [1], [2]. "
        "Если во фрагментах нет ответа — честно скажи, что в лекции об этом не говорится."
    )
    messages = [{"role": "system", "content": system}]
    for h in body.history[-6:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
            messages.append({"role": h["role"], "content": h["content"][:2000]})
    messages.append({"role": "user", "content": f"Фрагменты лекций:\n\n{context or '(ничего не найдено)'}"
                                                f"\n\nВопрос: {body.question}"})

    def gen():
        yield json.dumps({"sources": found}, ensure_ascii=False) + "\n"
        try:
            for piece in llm.chat_stream(messages):
                if piece:
                    yield json.dumps({"delta": piece}, ensure_ascii=False) + "\n"
        except llm.LLMUnavailable as e:
            yield json.dumps({"error": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


# ---------- Интерфейс ----------

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = FRONTEND_DIST / path
        if path and f.is_file() and FRONTEND_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
