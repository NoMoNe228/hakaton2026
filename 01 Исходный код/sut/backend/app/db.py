"""Хранилище SQLite: лекции, фразы расшифровки, куски для поиска."""
import json
import sqlite3
import threading
import time

from .config import DB_PATH

_lock = threading.RLock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode=WAL")

_conn.executescript(
    """
CREATE TABLE IF NOT EXISTS lectures (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,          -- file | url
    source_url TEXT,
    video_file TEXT,
    duration REAL,
    language TEXT,
    status TEXT NOT NULL,               -- queued | downloading | extracting | waiting | transcribing | indexing | indexed | summarizing | ready | error
    progress REAL DEFAULT 0,
    error TEXT,
    summary TEXT,                       -- JSON: краткий конспект, главные мысли
    outline TEXT,                       -- JSON: разделы и подразделы с таймкодами
    terms TEXT,                         -- JSON: ключевые термины
    summary_error TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    lecture_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    text TEXT NOT NULL,
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS segments_lecture ON segments(lecture_id, idx);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    lecture_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    text TEXT NOT NULL,
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS chunks_lecture ON chunks(lecture_id, idx);
"""
)
_conn.commit()

# Новые столбцы для уже созданной базы
_cols = {r[1] for r in _conn.execute("PRAGMA table_info(lectures)")}
if "source_key" not in _cols:
    _conn.execute("ALTER TABLE lectures ADD COLUMN source_key TEXT")  # «сайт:номер видео» для расширения
    _conn.commit()
for col in ("outline_alt", "tr_error"):  # заголовки оглавления на втором языке (JSON) и ошибка перевода
    if col not in _cols:
        _conn.execute(f"ALTER TABLE lectures ADD COLUMN {col} TEXT")
if "text_tr" not in {r[1] for r in _conn.execute("PRAGMA table_info(segments)")}:
    _conn.execute("ALTER TABLE segments ADD COLUMN text_tr TEXT")  # перевод фразы на второй язык
_conn.execute("CREATE INDEX IF NOT EXISTS lectures_source_key ON lectures(source_key)")
_conn.commit()

SEARCHABLE = ("indexed", "summarizing", "ready")  # indexed — искать можно, конспект в очереди
JSON_FIELDS = ("summary", "outline", "terms", "outline_alt")


def _row(r):
    if r is None:
        return None
    d = dict(r)
    for f in JSON_FIELDS:
        if d.get(f):
            d[f] = json.loads(d[f])
    return d


def query(sql, args=()):
    with _lock:
        return _conn.execute(sql, args).fetchall()


def execute(sql, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur


def executemany(sql, rows):
    with _lock:
        _conn.executemany(sql, rows)
        _conn.commit()


def create_lecture(lecture_id, title, source_type, source_url=None, video_file=None, source_key=None):
    execute(
        "INSERT INTO lectures (id, title, source_type, source_url, video_file, source_key, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)",
        (lecture_id, title, source_type, source_url, video_file, source_key, time.time()),
    )


def find_by_source_key(key):
    rows = query("SELECT id FROM lectures WHERE source_key = ? ORDER BY created_at DESC LIMIT 1", (key,))
    return get_lecture(rows[0]["id"]) if rows else None


def get_lecture(lecture_id):
    rows = query("SELECT * FROM lectures WHERE id = ?", (lecture_id,))
    return _row(rows[0]) if rows else None


def list_lectures():
    rows = query(
        "SELECT id, title, source_type, source_url, duration, language, status, progress, error,"
        " created_at, summary IS NOT NULL AS has_summary FROM lectures ORDER BY created_at DESC"
    )
    return [dict(r) for r in rows]


def update_lecture(lecture_id, **fields):
    if not fields:
        return
    for f in JSON_FIELDS:
        if f in fields and fields[f] is not None and not isinstance(fields[f], str):
            fields[f] = json.dumps(fields[f], ensure_ascii=False)
    cols = ", ".join(f"{k} = ?" for k in fields)
    execute(f"UPDATE lectures SET {cols} WHERE id = ?", (*fields.values(), lecture_id))


def delete_lecture(lecture_id):
    with _lock:
        for t in ("segments", "chunks"):
            _conn.execute(f"DELETE FROM {t} WHERE lecture_id = ?", (lecture_id,))
        _conn.execute("DELETE FROM lectures WHERE id = ?", (lecture_id,))
        _conn.commit()


def get_segments(lecture_id, with_embeddings=False):
    cols = "idx, start, end, text, text_tr" + (", embedding" if with_embeddings else "")
    return [dict(r) for r in query(f"SELECT {cols} FROM segments WHERE lecture_id = ? ORDER BY idx", (lecture_id,))]


def get_chunks(lecture_id):
    return [dict(r) for r in query("SELECT idx, start, end, text FROM chunks WHERE lecture_id = ? ORDER BY idx",
                                   (lecture_id,))]
