"""Поиск по смыслу.

Как ищем:
1. Векторный поиск: запрос и куски лекций превращаются в векторы (модель bge-m3, понимает русский и
   английский, в том числе запрос на одном языке и лекцию на другом).
2. Поиск по словам (BM25 по основам слов) — ловит точные термины, формулы, имена.
3. Два списка объединяются (RRF), лучшие кандидаты заново упорядочивает модель-«судья» (reranker),
   которая читает запрос и кусок вместе и оценивает, отвечает ли кусок на запрос.
4. Внутри найденного куска выбирается самая подходящая фраза — к её началу и ведёт таймкод.
"""
import math
import os
import threading
from collections import Counter, defaultdict

import numpy as np

from . import db
from .config import EMBED_MODEL, RERANK_MODEL, device
from .textutil import WORD, distance, highlight_spans, is_cyrillic, sound_key, tokens

_gpu_lock = threading.Lock()
_models = {}
_models_ready = threading.Event()
_models_error = None


def load_models():
    global _models_error
    try:
        _load_models()
    except Exception as e:
        _models_error = f"Не удалось загрузить модели поиска: {e}"
        print(f"[search] {_models_error}")
        _models_ready.set()


def _check():
    _models_ready.wait()
    if _models_error:
        raise RuntimeError(_models_error)


def _load_models():
    import torch
    from sentence_transformers import CrossEncoder, SentenceTransformer

    dev = device()
    emb = SentenceTransformer(EMBED_MODEL, device=dev)
    if dev == "cuda":
        emb.half()
    # Модель-«судья» улучшает порядок результатов, но поиск работает и без неё
    try:
        if not RERANK_MODEL:
            raise FileNotFoundError("не скачана в data/models")
        ce = CrossEncoder(RERANK_MODEL, device=dev, max_length=512)
        if dev == "cuda":
            ce.model.half()
    except Exception as e:
        ce = None
        print(f"[search] модель-«судья» не загрузилась ({e}), ищу без неё")
    _models["emb"], _models["ce"], _models["dev"] = emb, ce, dev
    _models_ready.set()
    print(f"[search] модели загружены на {dev}, torch {torch.__version__}")


def models_ready() -> bool:
    return _models_ready.is_set() and not _models_error


def models_error() -> str | None:
    return _models_error


def embed(texts: list[str], batch_size=32) -> np.ndarray:
    _check()
    with _gpu_lock:
        v = _models["emb"].encode(texts, batch_size=batch_size, normalize_embeddings=True,
                                  convert_to_numpy=True, show_progress_bar=False)
    return v.astype(np.float32)


def has_reranker() -> bool:
    return _models.get("ce") is not None


def rerank(query: str, texts: list[str]) -> np.ndarray:
    _check()
    with _gpu_lock:
        # Для модели с одной оценкой CrossEncoder сам переводит её в вероятность 0..1
        probs = _models["ce"].predict([(query, t) for t in texts], batch_size=16,
                                      show_progress_bar=False, convert_to_numpy=True)
    return np.asarray(probs, dtype=np.float32)


def _to_blob(v: np.ndarray) -> bytes:
    return v.astype(np.float16).tobytes()


def _from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float16).astype(np.float32)


# ---------- Нарезка и индексация ----------

def make_chunks(segments, target=30.0, overlap=1):
    """Склеивает фразы в куски ~target секунд; соседние куски перекрываются на `overlap` фраз."""
    chunks, i, n = [], 0, len(segments)
    while i < n:
        start = segments[i]["start"]
        j = i + 1
        while j < n and segments[j - 1]["end"] - start < target:
            j += 1
        part = segments[i:j]
        chunks.append({"start": part[0]["start"], "end": part[-1]["end"],
                       "text": " ".join(s["text"] for s in part)})
        if j >= n:
            break
        i = max(i + 1, j - overlap)
    return chunks


def index_lecture(lecture_id: str, segments: list[dict], target: float, overlap: int):
    chunks = make_chunks(segments, target, overlap)
    seg_emb = embed([s["text"] for s in segments])
    chunk_emb = embed([c["text"] for c in chunks], batch_size=16)
    db.execute("DELETE FROM chunks WHERE lecture_id = ?", (lecture_id,))
    db.executemany(
        "INSERT INTO chunks (lecture_id, idx, start, end, text, embedding) VALUES (?, ?, ?, ?, ?, ?)",
        [(lecture_id, k, c["start"], c["end"], c["text"], _to_blob(chunk_emb[k])) for k, c in enumerate(chunks)],
    )
    db.executemany(
        "UPDATE segments SET embedding = ? WHERE lecture_id = ? AND idx = ?",
        [(_to_blob(seg_emb[k]), lecture_id, k) for k in range(len(segments))],
    )
    INDEX.rebuild()
    return chunks, chunk_emb


# ---------- BM25 ----------

class BM25:
    def __init__(self, docs: list[list[str]], k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.dl = np.array([len(d) for d in docs], dtype=np.float32)
        self.avgdl = float(self.dl.mean()) if self.n else 1.0
        post = defaultdict(lambda: ([], []))
        for i, d in enumerate(docs):
            for t, c in Counter(d).items():
                post[t][0].append(i)
                post[t][1].append(c)
        self.post = {t: (np.array(ix), np.array(tf, dtype=np.float32)) for t, (ix, tf) in post.items()}
        self.idf = {t: math.log(1 + (self.n - len(ix) + 0.5) / (len(ix) + 0.5)) for t, (ix, _) in self.post.items()}

    def scores(self, q: list[str]) -> np.ndarray:
        s = np.zeros(self.n, dtype=np.float32)
        for t in set(q):
            if t not in self.post:
                continue
            ix, tf = self.post[t]
            norm = self.k1 * (1 - self.b + self.b * self.dl[ix] / self.avgdl)
            s[ix] += self.idf[t] * tf * (self.k1 + 1) / (tf + norm)
        return s


# ---------- Индекс в памяти ----------

class Index:
    def __init__(self):
        self.lock = threading.RLock()
        self.rows, self.emb, self.bm25 = [], np.zeros((0, 1024), np.float32), BM25([])
        self.words, self.sounds = Counter(), {}
        self.seg_cache = {}

    def rebuild(self):
        rows = db.query(
            "SELECT c.lecture_id, c.idx, c.start, c.end, c.text, c.embedding, l.title FROM chunks c"
            " JOIN lectures l ON l.id = c.lecture_id WHERE c.embedding IS NOT NULL ORDER BY c.lecture_id, c.idx"
        )
        rows = [dict(r) for r in rows]
        emb = np.stack([_from_blob(r.pop("embedding")) for r in rows]) if rows else np.zeros((0, 1024), np.float32)
        # Поиск по словам — и по оригиналу, и по переводу (вектора bge-m3 и так понимают оба языка)
        tr = defaultdict(list)
        for s in db.query("SELECT lecture_id, start, text_tr FROM segments WHERE text_tr IS NOT NULL ORDER BY lecture_id, idx"):
            tr[s["lecture_id"]].append((s["start"], s["text_tr"]))
        bm = BM25([tokens(r["text"] + " " + " ".join(t for st, t in tr.get(r["lecture_id"], ())
                                                       if r["start"] - 0.01 <= st < r["end"]))
                   for r in rows])
        # Словарь лекций: какие слова там встречаются и как они звучат (для «виндовс» → Windows)
        forms = Counter(m.group() for r in rows for m in WORD.finditer(r["text"]))
        words, spelling = Counter(), {}
        for f, n in forms.most_common():
            words[f.lower()] += n
            spelling.setdefault(f.lower(), f)  # самое частое написание: Windows, а не windows
        # Похожие по звучанию слова почти всегда совпадают первой или последней буквой — по ним и раскладываем,
        # чтобы не сравнивать запрос со всем словарём
        sounds = defaultdict(list)
        for w in words:
            if len(w) >= 4 and w.isalpha():
                key = sound_key(w)
                item = (key, spelling[w], is_cyrillic(w))
                sounds[len(key), "^" + key[0]].append(item)
                sounds[len(key), key[-1] + "$"].append(item)
        with self.lock:
            self.rows, self.emb, self.bm25 = rows, emb, bm
            self.words, self.sounds = words, sounds
            self.seg_cache.clear()

    def respell(self, query: str) -> str | None:
        """Запрос, где слова, которых нет в лекциях, заменены на похожие по звучанию слова на другом
        алфавите: «что такое виндовс» → «что такое windows». None — заменять нечего."""
        out, changed = [], False
        for m in WORD.finditer(query):
            w = m.group()
            if len(w) >= 4 and w.lower() not in self.words:
                key, cyr = sound_key(w), is_cyrillic(w)
                limit = 0 if len(key) < 5 else 1 if len(key) < 9 else 2
                near = {item for n in range(len(key) - limit, len(key) + limit + 1)
                        for edge in ("^" + key[0], key[-1] + "$") for item in self.sounds.get((n, edge), ())}
                best = min(((distance(key, k2, limit), -self.words[w2.lower()], w2)
                            for k2, w2, c2 in near if c2 != cyr), default=None)
                if best and best[0] <= limit:
                    out.append(best[2])
                    changed = True
                    continue
            out.append(w)
        return " ".join(out) if changed else None

    def _segments(self, lecture_id):
        if lecture_id not in self.seg_cache:
            segs = db.get_segments(lecture_id, with_embeddings=True)
            for s in segs:
                s["embedding"] = _from_blob(s["embedding"]) if s["embedding"] else None
            self.seg_cache[lecture_id] = segs
        return self.seg_cache[lecture_id]

    def search(self, query: str, lecture_id: str | None = None, k: int = 10, min_score: float = 0.02):
        return self.search_ex(query, lecture_id, k, min_score)[0]

    def search_ex(self, query: str, lecture_id: str | None = None, k: int = 10, min_score: float = 0.02):
        """Результаты и исправленный запрос (если слова запроса пришлось заменить, иначе None)."""
        query = query.strip()
        if not query:
            return [], None
        with self.lock:
            respelled = self.respell(query)
        return self._search(respelled or query, lecture_id, k, min_score), respelled

    def _search(self, query: str, lecture_id: str | None, k: int, min_score: float):
        with self.lock:
            rows, emb, bm = self.rows, self.emb, self.bm25
        if not rows:
            return []
        mask = np.array([lecture_id is None or r["lecture_id"] == lecture_id for r in rows])
        if not mask.any():
            return []

        qv = embed([query])[0]
        dense = emb @ qv
        dense[~mask] = -np.inf
        q_tokens = tokens(query)
        # Слова запроса, которого нет в лекциях, ищем по родственным словам с той же основой:
        # «планировщик» → «планирование», «планировании» (общее начало «планиров»)
        for t in [t for t in q_tokens if t not in bm.post and len(t) >= 7]:
            q_tokens += [u for u in bm.post if len(u) >= 6 and len(os.path.commonprefix([t, u])) >= max(6, len(t) - 3)]
        lex = bm.scores(q_tokens)
        lex[~mask] = -np.inf

        # Объединение двух списков по местам (Reciprocal Rank Fusion)
        pool = 40
        fused = defaultdict(float)
        for rank, i in enumerate(np.argsort(-dense)[:pool]):
            if np.isfinite(dense[i]):
                fused[i] += 1 / (60 + rank)
        for rank, i in enumerate(np.argsort(-lex)[:pool]):
            if lex[i] > 0 and np.isfinite(lex[i]):
                fused[i] += 1 / (60 + rank)
        # «Судья» на процессоре медленный (~0,3 с на кандидата) — там проверяем только самых вероятных
        cand = sorted(fused, key=fused.get, reverse=True)[:30 if _models.get("dev") == "cuda" else 12]
        # Близость векторов (у bge-m3 ~0.35 — случайный текст, ~0.7 — точное попадание)
        # плюс небольшая прибавка за совпавшие слова. По ней решаем, показывать ли фрагмент вообще.
        lex_max = max((lex[i] for i in cand if np.isfinite(lex[i])), default=0) or 1
        base = np.array([np.clip((dense[i] - 0.35) / 0.35, 0, 1) * 0.85
                         + 0.15 * max(lex[i], 0) / lex_max for i in cand], dtype=np.float32)
        if has_reranker():
            # «Судья» на разговорной речи даёт почти нулевые вероятности даже верным фрагментам,
            # поэтому берём не саму вероятность, а его порядок среди кандидатов (растянутый в 0..1)
            # и смешиваем с близостью векторов. Порог по-прежнему по векторам.
            p = np.clip(rerank(query, [rows[i]["text"] for i in cand]), 1e-6, 1 - 1e-6)
            logit = np.log(p / (1 - p))
            span = float(logit.max() - logit.min())
            judge = (logit - logit.min()) / span if span > 1e-6 else np.zeros_like(logit)
            scores = 0.5 * base + 0.35 * judge + 0.15 * p
            # Слабое по векторам и «судья» уверен, что не то, — не показываем
            keep = (base >= min_score) & ((base >= 0.1) | (p >= 0.01))
        else:
            scores = base
            keep = base >= min_score
        order = np.argsort(-scores)
        best = max((float(scores[o]) for o in order if keep[o]), default=0)

        stems = set(q_tokens)
        results, taken = [], defaultdict(list)
        for o in order:
            i, sc = cand[o], float(scores[o])
            # Хвост, который намного слабее лучшего результата, только мешает
            if not keep[o] or sc < best * 0.45:
                continue
            r = rows[i]
            # Перекрывающиеся куски одной лекции — оставляем лучший
            if any(r["start"] < e and s < r["end"] for s, e in taken[r["lecture_id"]]):
                continue
            taken[r["lecture_id"]].append((r["start"], r["end"]))
            jump = self._best_moment(r, qv)
            results.append({
                "lecture_id": r["lecture_id"],
                "lecture_title": r["title"],
                "start": r["start"],
                "end": r["end"],
                "jump": jump,
                "text": r["text"],
                "score": round(sc, 4),
                "dense": round(float(dense[i]), 4),
                "highlights": highlight_spans(r["text"], stems),
            })
            if len(results) >= k:
                break
        return results

    def _best_moment(self, row, qv) -> float:
        """Начало самой близкой к запросу фразы внутри куска."""
        segs = [s for s in self._segments(row["lecture_id"])
                if s["start"] >= row["start"] - 0.01 and s["end"] <= row["end"] + 0.01 and s["embedding"] is not None]
        if not segs:
            return row["start"]
        best = max(segs, key=lambda s: float(s["embedding"] @ qv))
        return best["start"]


INDEX = Index()
