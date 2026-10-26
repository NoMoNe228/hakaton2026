from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from typing import Iterator
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data"
VIDEO_DIR = DATA_DIR / "videos"
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "lectures.db"
ALLOWED_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "1024"))

for directory in (VIDEO_DIR, AUDIO_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Семантический поиск по видеолекциям", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# External AI APIs avoid local PyTorch / faster-whisper dependencies.
_openai_client = None

def get_openai_client() -> OpenAI:
    global _openai_client
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Не задан OPENAI_API_KEY. Добавьте ключ в файл .env.")
    if _openai_client is None:
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client

def create_embeddings(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    client = get_openai_client()
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    vectors: list[list[float]] = []
    for offset in range(0, len(texts), 64):
        response = client.embeddings.create(model=model, input=texts[offset:offset + 64])
        vectors.extend(item.embedding for item in response.data)
    return vectors

def transcribe_audio(audio_path: Path) -> tuple[list[dict], str | None]:
    """Split extracted WAV into 10-minute chunks and transcribe with timestamps."""
    client = get_openai_client()
    chunk_dir = AUDIO_DIR / f"chunks_{uuid.uuid4().hex}"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    pattern = chunk_dir / "chunk_%03d.wav"
    cmd = ["ffmpeg", "-y", "-i", str(audio_path), "-f", "segment", "-segment_time", "600",
           "-ac", "1", "-ar", "16000", str(pattern)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60)
    if result.returncode != 0:
        shutil.rmtree(chunk_dir, ignore_errors=True)
        raise RuntimeError("Не удалось разбить аудио на части: " + (result.stderr[-1000:] or "ошибка FFmpeg"))
    all_segments: list[dict] = []
    language = None
    try:
        chunks = sorted(chunk_dir.glob("chunk_*.wav"))
        if not chunks:
            raise RuntimeError("FFmpeg не создал аудиофрагменты.")
        for index, chunk in enumerate(chunks):
            with chunk.open("rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1"),
                    file=audio_file, response_format="verbose_json",
                    timestamp_granularities=["segment"]
                )
            language = language or getattr(response, "language", None)
            offset_seconds = index * 600
            for seg in getattr(response, "segments", []) or []:
                text = (getattr(seg, "text", "") or "").strip()
                if text:
                    all_segments.append({"start": float(seg.start) + offset_seconds,
                                         "end": float(seg.end) + offset_seconds, "text": text})
        return all_segments, language
    finally:
        shutil.rmtree(chunk_dir, ignore_errors=True)


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'uploaded',
            error TEXT,
            duration REAL,
            language TEXT,
            transcript TEXT,
            summary TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
            start REAL NOT NULL,
            end REAL NOT NULL,
            text TEXT NOT NULL,
            embedding TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_segments_video ON segments(video_id);
        """)


init_db()


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def make_summary(segments: list[dict]) -> str:
    """Generate a concise lecture summary through the configured LLM API."""
    transcript = "\n".join(f"[{format_time(s['start'])}] {s['text']}" for s in segments)
    # Avoid sending an arbitrarily long transcript in one request.
    transcript = transcript[:50000]
    try:
        response = get_openai_client().chat.completions.create(
            model=os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "Ты помощник преподавателя. Составь краткий структурированный конспект лекции на русском языке. Сохраняй факты из исходного текста, не выдумывай сведения. Включи основные тезисы и термины. Если язык лекции английский, всё равно пиши конспект на русском."},
                {"role": "user", "content": "Составь конспект по транскрипции с таймкодами:\n\n" + transcript}
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content
        if content and content.strip():
            return content.strip()
    except Exception as exc:
        # Preserve a usable result even if the summary endpoint is temporarily unavailable.
        print(f"Summary API warning: {exc}")
    sentences = []
    for seg in segments:
        for sentence in seg["text"].replace("!", ".").replace("?", ".").split("."):
            sentence = sentence.strip()
            if len(sentence) >= 45:
                sentences.append((seg["start"], sentence))
    if not sentences:
        return "Текст слишком короткий для автоматического конспекта. Откройте транскрипцию ниже."
    step = max(1, len(sentences) // 8)
    return "\n\n".join(f"[{format_time(t)}] {sentence}." for t, sentence in sentences[::step][:10])


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def process_video(video_id: str) -> None:
    with db() as conn:
        video = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if not video:
        return
    video_path = VIDEO_DIR / video["filename"]
    audio_path = AUDIO_DIR / f"{video_id}.wav"
    try:
        if not ffmpeg_available():
            raise RuntimeError("Не найден FFmpeg. Установите FFmpeg и добавьте его в PATH.")
        with db() as conn:
            conn.execute("UPDATE videos SET status='processing', error=NULL WHERE id=?", (video_id,))
        cmd = ["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", str(audio_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60)
        if result.returncode != 0:
            raise RuntimeError("Не удалось извлечь аудио: " + (result.stderr[-1000:] or "ошибка FFmpeg"))

        segments, language = transcribe_audio(audio_path)
        if not segments:
            raise RuntimeError("Речь не распознана. Проверьте качество аудио и настройки API.")

        texts = [s["text"] for s in segments]
        embeddings = create_embeddings(texts)
        transcript = "\n".join(f"[{format_time(s['start'])}] {s['text']}" for s in segments)
        summary = make_summary(segments)
        duration = max(s["end"] for s in segments)
        with db() as conn:
            conn.execute("DELETE FROM segments WHERE video_id=?", (video_id,))
            conn.executemany(
                "INSERT INTO segments(video_id,start,end,text,embedding) VALUES(?,?,?,?,?)",
                [(video_id, s["start"], s["end"], s["text"], json.dumps(emb.tolist())) for s, emb in zip(segments, embeddings)],
            )
            conn.execute(
                "UPDATE videos SET status='ready', duration=?, language=?, transcript=?, summary=?, error=NULL WHERE id=?",
                (duration, language, transcript, summary, video_id),
            )
    except Exception as exc:
        with db() as conn:
            conn.execute("UPDATE videos SET status='error', error=? WHERE id=?", (str(exc)[:2000], video_id))
    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass


class SearchRequest(BaseModel):
    query: str
    video_id: Optional[str] = None
    limit: int = 10


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "ffmpeg_available": ffmpeg_available()}


@app.post("/api/videos")
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    original_name = file.filename or "lecture.mp4"
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Поддерживаются MP4, WebM, MOV и M4V.")
    video_id = str(uuid.uuid4())
    stored_name = f"{video_id}{suffix}"
    destination = VIDEO_DIR / stored_name
    size = 0
    try:
        with destination.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(413, f"Файл превышает лимит {MAX_UPLOAD_MB} МБ.")
                out.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    title = Path(original_name).stem
    with db() as conn:
        conn.execute(
            "INSERT INTO videos(id,filename,original_name,title,status) VALUES(?,?,?,?,?)",
            (video_id, stored_name, original_name, title, "queued"),
        )
    background_tasks.add_task(process_video, video_id)
    return {"id": video_id, "title": title, "status": "queued"}


@app.get("/api/videos")
def list_videos():
    with db() as conn:
        rows = conn.execute("SELECT id,title,status,error,duration,created_at FROM videos ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


@app.get("/api/videos/{video_id}")
def get_video(video_id: str):
    with db() as conn:
        row = conn.execute("SELECT id,title,original_name,status,error,duration,language,summary,transcript FROM videos WHERE id=?", (video_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Лекция не найдена")
    item = dict(row)
    item["video_url"] = f"/media/{video_id}"
    return item


@app.get("/media/{video_id}")
def media(video_id: str):
    with db() as conn:
        row = conn.execute("SELECT filename FROM videos WHERE id=?", (video_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Видео не найдено")
    path = VIDEO_DIR / row["filename"]
    if not path.exists():
        raise HTTPException(404, "Файл видео не найден")
    return FileResponse(path)


@app.get("/api/videos/{video_id}/segments")
def get_segments(video_id: str):
    with db() as conn:
        exists = conn.execute("SELECT 1 FROM videos WHERE id=?", (video_id,)).fetchone()
        if not exists:
            raise HTTPException(404, "Лекция не найдена")
        rows = conn.execute("SELECT id,start,end,text FROM segments WHERE video_id=? ORDER BY start", (video_id,)).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/search")
def search(request: SearchRequest):
    query = request.query.strip()
    if not query:
        raise HTTPException(400, "Введите поисковый запрос")
    with db() as conn:
        if request.video_id:
            rows = conn.execute("""SELECT s.id,s.video_id,s.start,s.end,s.text,s.embedding,v.title
                FROM segments s JOIN videos v ON v.id=s.video_id
                WHERE s.video_id=? AND v.status='ready' AND s.embedding IS NOT NULL""", (request.video_id,)).fetchall()
        else:
            rows = conn.execute("""SELECT s.id,s.video_id,s.start,s.end,s.text,s.embedding,v.title
                FROM segments s JOIN videos v ON v.id=s.video_id
                WHERE v.status='ready' AND s.embedding IS NOT NULL""").fetchall()
    if not rows:
        return {"results": [], "message": "Пока нет обработанных лекций для поиска."}
    q_embedding = create_embeddings([query])[0]
    scored = []
    for row in rows:
        emb = json.loads(row["embedding"])
        score = sum(float(a) * float(b) for a, b in zip(q_embedding, emb))
        scored.append({"segment_id": row["id"], "video_id": row["video_id"], "title": row["title"],
                       "start": row["start"], "end": row["end"], "text": row["text"], "score": score})
    scored.sort(key=lambda item: item["score"], reverse=True)
    return {"results": scored[:max(1, min(request.limit, 30))]}


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: str):
    with db() as conn:
        row = conn.execute("SELECT filename FROM videos WHERE id=?", (video_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Лекция не найдена")
        conn.execute("DELETE FROM videos WHERE id=?", (video_id,))
    (VIDEO_DIR / row["filename"]).unlink(missing_ok=True)
    return {"deleted": True}
